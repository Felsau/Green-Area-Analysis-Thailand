"""Step1: actual local GoTrue/PostgREST custom-role identity proof.

Only the attested OPERATOR provisions the new role/probe/account. All permission
proofs use the worker's actual Auth-issued JWT, never SET ROLE/postgres/service.
No original env/signing secrets or credential persistence. Worker tokens stay in
memory and are returned only to the caller's private process object.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import secrets
import sys
import time
from uuid import UUID, uuid4

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('t3_identity_local_t2',HERE.parent/'gis_local/t2_local.py')
t2=importlib.util.module_from_spec(spec);sys.modules[spec.name]=t2;spec.loader.exec_module(t2)
ROLE='gis_native_worker'
ISSUER='http://127.0.0.1:55421/auth/v1'


class IdentityProofFailure(RuntimeError):
    pass


@dataclass(repr=False)
class WorkerIdentity:
    subject: str
    anon_key: str=field(repr=False)
    access_token: str=field(repr=False)
    refresh_token: str=field(repr=False)
    client: object=field(repr=False)
    # This object must never be serialized or logged; no password is retained.


def _probe_state(local):
    """Operator-only catalog snapshot; contains no auth users or credentials."""
    raw=local.db.query('postgres',"""
SELECT jsonb_build_object(
 'probe',(SELECT jsonb_build_object('definition',pg_get_functiondef(p.oid),
   'owner',pg_get_userbyid(p.proowner),'comment',obj_description(p.oid,'pg_proc'),
   'acl',(SELECT jsonb_agg(jsonb_build_array(COALESCE(r.rolname,'PUBLIC'),a.privilege_type,a.is_grantable)
             ORDER BY COALESCE(r.rolname,'PUBLIC'),a.privilege_type,a.is_grantable)
          FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
          LEFT JOIN pg_roles r ON r.oid=a.grantee))
   FROM pg_proc p WHERE p.oid=to_regprocedure('public.gis_identity_probe_t3()')),
 'role',(SELECT jsonb_build_array(rolsuper,rolbypassrls,rolcanlogin,rolcreatedb,rolcreaterole,
     rolreplication,rolinherit,shobj_description(oid,'pg_authid'))
   FROM pg_roles WHERE rolname='gis_native_worker'),
 'memberships',(SELECT jsonb_agg(jsonb_build_array(r.rolname,m.rolname,a.admin_option,
     a.inherit_option,a.set_option) ORDER BY r.rolname,m.rolname)
   FROM pg_auth_members a JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON m.oid=a.member
   WHERE r.rolname='gis_native_worker' OR m.rolname='gis_native_worker'));
""").stdout
    state=json.loads(raw)
    role=state.get('role')
    probe=state.get('probe') or {}
    memberships=state.get('memberships') or []
    expected_grant=['gis_native_worker','authenticator',False,False,True]
    # Only an existing operator's automatic creator membership may accompany the
    # PostgREST SET grant; the worker is never a member of any other SQL role.
    if (role!=[False]*7+['gis-t3-native-worker-v1']
       or probe.get('owner')!='postgres' or probe.get('comment')!='gis-t3-native-probe-v1'
       or expected_grant not in memberships
       or any(row[0]!='gis_native_worker' or row[1] not in ('postgres','authenticator') for row in memberships)
       or sorted(probe.get('acl') or [])!=[['gis_native_worker','EXECUTE',False],['postgres','EXECUTE',False]]):
        raise IdentityProofFailure('IDENTITY_SETUP_STATE_DRIFT')
    return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply_probe(local,review_path:Path):
    local.attest()
    source=(HERE/'identity_probe.sql').read_bytes()
    checksum=hashlib.sha256(source).hexdigest()
    review=json.loads(review_path.read_text(encoding='utf-8'))
    if (review.get('independent_review') is not True or review.get('unresolved_high_critical')!=0
       or review.get('files')!={'identity_probe.sql':checksum}):
        raise IdentityProofFailure('EXACT_IDENTITY_SQL_REVIEW_REQUIRED')
    checkpoint=local.db.runtime.root/'t3/identity-probe-setup.json'
    if checkpoint.exists():
        record=json.loads(checkpoint.read_text(encoding='utf-8'))
        if record.get('instance')!=local.db.instance or record.get('sha256')!=checksum:
            raise IdentityProofFailure('IDENTITY_SETUP_CHECKPOINT_MISMATCH')
        # Exact definition/owner/ACL/role/membership fingerprint prevents accepting
        # a drifted probe merely because its comment marker still matches.
        if record.get('catalog_sha256')!=_probe_state(local):
            raise IdentityProofFailure('IDENTITY_SETUP_STATE_DRIFT')
        return checksum
    local.attest()
    sql=("BEGIN;SET LOCAL lock_timeout='5s';SET LOCAL statement_timeout='30s';"
      +"SELECT set_config('gis.runtime_instance',"+t2.t1.literal(local.db.instance)+",true);"
      +"SELECT set_config('gis.baseline_fingerprint',"+t2.t1.literal(t2.t1.legacy_fingerprint())+",true);\n"
      +source.decode('utf-8-sig')+'\nCOMMIT;')
    local.db.transport('postgres',sql)
    checkpoint.parent.mkdir(exist_ok=True)
    checkpoint.write_text(json.dumps({'sha256':checksum,'instance':local.db.instance,
      'catalog_sha256':_probe_state(local),
      'operator_provisioning_only':True,'ledger_unchanged':True},indent=2)+'\n',encoding='utf-8',newline='\n')
    return checksum


def provision(local)->WorkerIdentity:
    """Create ONE new synthetic worker Auth account; secrets never leave memory.

    The returned client has only anon apikey + worker JWT. The operator's service
    client and random password are not returned or inherited by worker processes.
    This operator helper is not worker implementation and must not run in a worker.
    """
    local.attest()
    anon,service=local.local_keys()
    operator=local.client(service)
    email='gis-t3-worker-'+uuid4().hex+'@example.invalid'
    password=secrets.token_urlsafe(30)
    created=operator.auth.admin.create_user({'email':email,'password':password,'email_confirm':True,
      'role':ROLE,'user_metadata':{'display_name':'T3 synthetic worker','role':'admin','gis_officer':True}})
    subject=str(UUID(str(created.user.id)))
    worker=local.client(anon)
    response=worker.auth.sign_in_with_password({'email':email,'password':password})
    session=response.session
    if session is None or str(response.user.id)!=subject:raise IdentityProofFailure('WORKER_SIGNIN_FAILED')
    import jwt
    # These are metadata consistency checks only; the actual probe below proves
    # that PostgREST accepts Auth's signature and chooses the restricted SQL role.
    claims=jwt.decode(session.access_token,options={'verify_signature':False})
    if claims.get('role')!=ROLE or claims.get('sub')!=subject or claims.get('iss')!=ISSUER:
        raise IdentityProofFailure('CUSTOM_AUTH_ROLE_NOT_ISSUED')
    return WorkerIdentity(subject,anon,session.access_token,session.refresh_token,worker)


def prove(local,identity:WorkerIdentity):
    """All probes below are actual worker-JWT HTTP calls, never operator SQL."""
    rows=[]
    def record(name,passed,**safe):
        row={'name':name,'status':'Pass' if passed else 'Fail',**safe};rows.append(row)
        print(json.dumps(row),flush=True)
    local.attest()
    probe=None
    for _ in range(10):
        try:
            probe=identity.client.rpc('gis_identity_probe_t3',{}).execute().data
            break
        except Exception as error:
            if str(getattr(error,'code',''))!='PGRST202':raise
            time.sleep(.3)
    expected={'sql_role':ROLE,'session_role':'authenticator','jwt_role':ROLE,
      'database_name':'postgres','cluster_name':'green-area-gis-t0'}
    record('actual_worker_jwt_selects_restricted_sql_role',isinstance(probe,dict)
      and all(probe.get(k)==v for k,v in expected.items()) and probe.get('subject')==identity.subject)
    record('worker_role_has_no_privileged_membership',isinstance(probe,dict)
      and all(probe.get(k) is False for k in ('superuser','bypass_rls','can_create_role','can_create_database',
        'owner_member','service_member','legacy_worker_member')))
    def denied(name,call,codes):
        try:call();record(name,False)
        except Exception as error:record(name,str(getattr(error,'code','')) in codes)
    denied('backend_readiness_rpc_denied',lambda:identity.client.rpc('gis_readiness',{}).execute(),{'42501'})
    denied('backend_read_rpc_denied',lambda:identity.client.rpc('gis_read',{'p_actor':identity.subject,'p_kind':'me','p_payload':{}}).execute(),{'42501'})
    denied('admin_command_rpc_denied',lambda:identity.client.rpc('gis_command',{'p_actor':identity.subject,
      'p_request_id':str(uuid4()),'p_operation':'grant_officer','p_payload':{'user_id':identity.subject,'reason':'denied synthetic self grant'},'p_backend_sandbox':False}).execute(),{'42501'})
    denied('legacy_worker_rpc_denied',lambda:identity.client.rpc('gis_worker',{'p_action':'claim','p_payload':{'worker_id':str(uuid4())}}).execute(),{'42501'})
    denied('private_gis_table_denied',lambda:identity.client.schema('gis').table('datasets').select('id').limit(1).execute(),{'42501','PGRST106','PGRST205'})
    denied('direct_profile_read_denied',lambda:identity.client.table('profiles').select('id').limit(1).execute(),{'42501'})
    # Contradictory filters ensure that an unexpected grant still changes ZERO rows.
    denied('legacy_cache_write_denied',lambda:identity.client.table('ndvi_annual').update({'ndvi_mean':0}).eq('id',0).neq('id',0).execute(),{'42501'})
    denied('direct_auth_table_denied',lambda:identity.client.schema('auth').table('users').select('id').limit(1).execute(),{'42501','PGRST106','PGRST205'})
    try:
        identity.client.auth.admin.list_users(page=1,per_page=1)
        record('auth_admin_api_denied',False)
    except Exception as error:
        status=getattr(error,'status',None) or getattr(error,'status_code',None)
        record('auth_admin_api_denied',str(status) in {'401','403'})
    import httpx
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=5) as client:
        response=client.post('http://127.0.0.1:55421/rest/v1/rpc/gis_identity_probe_t3',
            headers={'apikey':identity.anon_key},json={})
        record('anon_cannot_execute_probe',response.status_code in (401,403))
    # No alternate privileged identity is accepted as a worker proof.
    return {'type':'actual_local_gotrue_postgrest_worker_identity',
      'counts':{state:sum(r['status']==state for r in rows) for state in ('Pass','Fail')},'results':rows,
      'worker_role':ROLE,'worker_used_service_key':False,'worker_used_postgres_or_set_role':False,
      'operator_provisioned_role_probe_and_one_auth_account':True,'signing_secret_read':False,
      'credentials_persisted':False,'auth_account_retained':True,
      'not_tested':['Native Worker RPC/Queue E2E (requires031)','Linux worker process identity/refresh lifecycle']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--review',type=Path,required=True)
    args=parser.parse_args()
    logging.disable(logging.CRITICAL)
    local=t2.LocalT2(args.runtime_dir)
    try:
        checksum=apply_probe(local,args.review)
        identity=provision(local)
        report=prove(local,identity)
        report['identity_sql_sha256']=checksum
    except Exception as error:
        report={'type':'actual_local_worker_identity','counts':{'Pass':0,'Fail':1},
          'error_type':type(error).__name__,'credentials_persisted':False,'worker_used_service_key':False}
    output=local.db.runtime.root/'t3';output.mkdir(exist_ok=True)
    (output/'identity-proof.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'counts':report['counts'],'report':'identity-proof.json'}))
    return 1 if report['counts']['Fail'] else 0


if __name__=='__main__':sys.exit(main())

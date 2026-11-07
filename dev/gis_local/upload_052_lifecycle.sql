-- 052 rolled-back lifecycle (caller: BEGIN; migration; ledger; this; ROLLBACK).
-- Settings t.actor (officer), t.worker (another profile), t.admin (an admin) and t.province come from the caller.
-- Two LDD datasets go through validation -> preparation -> verification -> activation -> Dashboard read:
-- one validated by the policy-v2 validator (LDD_POLICY_V2 marker) and one with a report of the earlier shape.
-- The prepare worker needs a native JWT identity, so its claim/complete rows are written here exactly as
-- gis.ldd_prepare_worker writes them; the deferred catalog triggers then check them like any worker row.
SET LOCAL ROLE gis_owner;
DO $t$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid;
 adm uuid:=current_setting('t.admin')::uuid; p text:=current_setting('t.province');
 v1 text:='ldd-source-area-v1'; v2 text:='ldd-geometry-area-v2';
 gadm text:='ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21';
 ldd text:='1b6cf62b8f43504078c51c9ca3e94f6fffe56c2ca1b3765674d5aa2d7c62e1ac';
 i integer; year integer; method text; other text; sha text; ds jsonb; up jsonb; job jsonb; vrep jsonb; r jsonb;
 pj uuid; packet jsonb; rep jsonb; tok uuid; att integer; cert jsonb; payload jsonb; proof jsonb; pk jsonb; failed boolean;
 ed gis.editions; d gis.datasets; role_name text; bad jsonb;
BEGIN
 FOR i IN 1..2 LOOP
  year:=2002+i; method:=CASE i WHEN 1 THEN v2 ELSE v1 END; other:=CASE i WHEN 1 THEN v1 ELSE v2 END;
  sha:=repeat(CASE i WHEN 1 THEN 'a' ELSE 'b' END,64);
  -- Validation, as a real worker completes it.
  ds:=gis.command(a,('dddddddd-0520-4000-8000-00000000000'||i)::uuid,'create_dataset',jsonb_build_object('province',p,'data_year',year,'month',0,
   'kind','ldd_shapefile','purpose','landuse','title','t052-'||i),false)->'body';
  up:=gis.ldd_command(a,('dddddddd-0521-4000-8000-00000000000'||i)::uuid,'upload',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision',
   'upload_id','dddddddd-0522-4000-8000-0000000000a'||i,'sha256',sha,'byte_size',10,'crs','EPSG:32647','encoding','utf-8','source_label','t052'),false);
  PERFORM gis.ldd_command(a,('dddddddd-0523-4000-8000-00000000000'||i)::uuid,'enqueue',jsonb_build_object('edition_id',up->'body'->>'edition_id','expected_revision',1),false);
  job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'ldd')->'job';
  IF job->>'upload_id' IS DISTINCT FROM up->'body'->>'upload_id' THEN RAISE EXCEPTION 'T_CLAIM %',job; END IF;
  vrep:=jsonb_build_object('schema_version',1,'provider_build','ldd-local-v1','upload_id',job->>'upload_id','artifact_sha256',sha,'observed_sha256',sha,'byte_size',10,
   'input_hash',job->>'input_hash','input_revision',job->'input_revision','province',p,'data_year',year,'crs','EPSG:32647','encoding','utf-8','valid',true,
   'checks','["source_hash_match","archive_safety","components","crs","geometry","attributes","encoding","ldd_codes","province_bounds","dataset_association"]'::jsonb,
   'errors','[]'::jsonb,'error_code',NULL::text,
   'statistics','{"feature_count":3,"total_area_m2":100,"unknown_area_m2":0,"unknown_code_count":0,"composite_feature_count":0,"geometry_error_count":0,"area_by_main_m2":{"U":100,"A":0,"F":0,"W":0,"M":0}}'::jsonb);
  IF i=1 THEN
   vrep:=vrep||jsonb_build_object('boundary_sha256',ldd,'warnings','[{"code":"BOUNDARY_FROM_DATA_PRODUCER","count":1},{"code":"DATA_YEAR_METADATA_DECLARED","count":1},{"code":"LDD_POLICY_V2","count":1},{"code":"FIELD_PROFILE_LDD_LU_TEXT_V1","count":1}]'::jsonb,
    'audit','{"policy_version":"ldd-policy-v2","outcome":"accepted","field_profile":"ldd-lu-text-v1","field_mapping":{"main_code":"LUL1_CODE","lu_code":"LU_CODE","declared_area":"Shape_Area"},"declared_area_units":"m2","feature_outcomes":{"accepted":3,"accepted_with_warnings":0,"review_required":0,"rejected":0},"boundary":{"minor":0,"review":0,"fatal":0,"outside_area_m2":0},"unknown_samples":[],"repairs":[],"repairs_total":0}'::jsonb);
  ELSE
   vrep:=vrep||jsonb_build_object('boundary_sha256',gadm,'warnings','[{"code":"BOUNDARY_APPROXIMATE","count":1},{"code":"DATA_YEAR_METADATA_DECLARED","count":1}]'::jsonb);
  END IF;
  r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',vrep),'ldd');
  IF r->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'T_VALIDATION_STATE %',r; END IF;
  SELECT * INTO ed FROM gis.editions WHERE id=(up->'body'->>'edition_id')::uuid;
  SELECT * INTO d FROM gis.datasets WHERE id=ed.dataset_id;
  IF ed.state<>'validated' OR gis.publication_validation(ed.id) IS NULL THEN RAISE EXCEPTION 'T_NOT_VALIDATED %',ed.state; END IF;

  -- Preparation: the request takes the method of the validation, never one from the caller.
  r:=gis.ldd_prepare_command(a,('dddddddd-0524-4000-8000-00000000000'||i)::uuid,'enqueue',jsonb_build_object('edition_id',ed.id,
   'expected_dataset_revision',d.revision,'expected_input_revision',ed.input_revision,'input_hash',ed.input_hash,'province',p,'data_year',year));
  pj:=(r->'body'->>'id')::uuid;
  IF (SELECT method_version FROM gis.ldd_prepare_requests WHERE job_id=pj) IS DISTINCT FROM method THEN RAISE EXCEPTION 'T_REQUEST_METHOD %',i; END IF;
  packet:=gis.ldd_prepare_packet(pj);
  IF packet->>'method_version' IS DISTINCT FROM method THEN RAISE EXCEPTION 'T_PACKET_METHOD %',packet->>'method_version'; END IF;
  -- Claim, as gis.ldd_prepare_worker writes it.
  tok:=gen_random_uuid();
  UPDATE gis.jobs SET state='running',worker_id=w,lease_token=tok,lease_until=clock_timestamp()+interval '60 seconds',
   attempt_count=attempt_count+1,progress=0,error_code=NULL WHERE id=pj RETURNING attempt_count INTO att;
  INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,started_at) VALUES(pj,att,w,tok,'running',clock_timestamp());
  rep:=jsonb_build_object('schema_version',1,'method_version',method,'valid',true,'error_code',NULL::text,
   'dataset_id',packet->>'dataset_id','edition_id',packet->>'edition_id','job_id',packet->>'job_id','validation_result_id',packet->>'validation_result_id',
   'source_sha256',packet#>>'{validation,manifest,sha256}','input_hash',packet#>>'{validation,input_hash}','input_revision',packet#>'{validation,input_revision}',
   'artifacts',jsonb_build_object('ldd_geometry',jsonb_build_object('sha256',repeat('1',63)||i,'byte_size',1000),
                                  'ldd_summary',jsonb_build_object('sha256',repeat('2',63)||i,'byte_size',100)));
  -- A report must name the method of its request; every earlier rule still applies to v2.
  PERFORM gis.ldd_prepare_report(pj,rep);
  FOR bad IN SELECT x FROM unnest(ARRAY[jsonb_set(rep,'{method_version}',to_jsonb(other)),jsonb_set(rep,'{method_version}','"ldd-other-v9"'),
    rep-'method_version',jsonb_set(rep,'{input_hash}',to_jsonb(repeat('0',64))),rep||'{"extra":1}'::jsonb,
    jsonb_set(rep,'{artifacts,ldd_geometry,byte_size}','20971521'),jsonb_set(rep,'{schema_version}','2')]) x LOOP
   failed:=false;
   BEGIN PERFORM gis.ldd_prepare_report(pj,bad); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_BAD_REPORT_ACCEPTED % %',i,left(bad::text,160); END IF;
  END LOOP;
  failed:=false;
  BEGIN PERFORM gis.ldd_prepare_report(pj,'"text"'::jsonb); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
  IF NOT failed THEN RAISE EXCEPTION 'T_NON_OBJECT_REPORT_ACCEPTED'; END IF;
  -- Complete, as gis.ldd_prepare_worker writes it; the deferred catalog triggers check it now.
  UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=clock_timestamp(),validation_report=rep WHERE job_id=pj AND attempt_no=att;
  INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,provider,valid,report)
   VALUES(pj,ed.id,ed.input_revision,ed.input_hash,'ldd-prepare-v1',att,tok,'local_ldd_prepare',true,rep);
  UPDATE gis.jobs SET state='succeeded',progress=100,finished_at=clock_timestamp(),worker_id=NULL,lease_token=NULL,lease_until=NULL WHERE id=pj;
  SET CONSTRAINTS ALL IMMEDIATE;
  SET CONSTRAINTS ALL DEFERRED;

  -- Verification registers the artifacts under the request's method.
  failed:=false;
  BEGIN PERFORM gis.ldd_verify_complete(a,gen_random_uuid(),pj,jsonb_set(rep,'{method_version}',to_jsonb(other))||'{"verifier_version":"ldd-trusted-bytes-v1"}'::jsonb);
  EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
  IF NOT failed THEN RAISE EXCEPTION 'T_PROOF_WITH_OTHER_METHOD_ACCEPTED %',i; END IF;
  cert:=gis.ldd_verify_complete(a,('dddddddd-0525-4000-8000-00000000000'||i)::uuid,pj,rep||'{"verifier_version":"ldd-trusted-bytes-v1"}'::jsonb);
  IF cert->'ready_for_publication' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'T_VERIFY %',cert; END IF;
  IF (SELECT count(*) FROM gis.publication_artifacts WHERE edition_id=ed.id AND method_version=method)<>2
   OR EXISTS(SELECT 1 FROM gis.publication_artifacts WHERE edition_id=ed.id AND method_version=other) THEN RAISE EXCEPTION 'T_ARTIFACT_METHOD %',i; END IF;
  IF NOT gis.publication_ready(ed.id,d.id) THEN RAISE EXCEPTION 'T_NOT_READY %',i; END IF;
  IF public.gis_publication_read(a,ed.id,method)->'ready_for_publication' IS DISTINCT FROM 'true'::jsonb
   OR public.gis_publication_read(a,ed.id,other)->'ready_for_publication' IS DISTINCT FROM 'false'::jsonb
   OR public.gis_publication_read(a,ed.id,'ldd-other-v9')->'ready_for_publication' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'T_CATALOG_READ %',i; END IF;
  IF (gis.ldd_prepare_read(a,ed.id))->'ready_for_publication' IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'T_PREPARE_READ %',i; END IF;

  -- Activation: the payload must name the Edition's own method; the audit records it.
  SELECT * INTO d FROM gis.datasets WHERE id=d.id;
  payload:=jsonb_build_object('dataset_id',d.id,'edition_id',ed.id,'expected_dataset_revision',d.revision,'expected_active_edition_id',NULL,
   'expected_input_revision',ed.input_revision,'input_hash',ed.input_hash,'validation_result_id',ed.validated_result_id,
   'source_sha256',ed.manifest->>'sha256','province',p,'data_year',year,'method_version',method,'coverage_mode','validated_source_footprint','reason','t052');
  proof:=jsonb_build_object('certificate_id',cert->>'certificate_id','report',rep||'{"verifier_version":"ldd-publication-bytes-v1"}'::jsonb);
  FOR bad IN SELECT x FROM unnest(ARRAY[jsonb_set(payload,'{method_version}',to_jsonb(other)),jsonb_set(payload,'{method_version}','"ldd-other-v9"'),
    jsonb_set(payload,'{method_version}','null')]) x LOOP
   failed:=false;
   BEGIN PERFORM gis.ldd_publication_command(adm,gen_random_uuid(),'activate',bad,proof,true,false);
   EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_ACTIVATION_WITH_WRONG_METHOD_ACCEPTED % %',i,bad->'method_version'; END IF;
  END LOOP;
  r:=gis.ldd_publication_command(adm,('dddddddd-0526-4000-8000-00000000000'||i)::uuid,'activate',payload,proof,true,false);
  IF r->>'status' IS DISTINCT FROM '200' OR (SELECT active_edition_id FROM gis.datasets WHERE id=d.id) IS DISTINCT FROM ed.id THEN RAISE EXCEPTION 'T_ACTIVATE %',r; END IF;
  IF (SELECT detail->>'method_version' FROM gis.audit WHERE id=(r->'body'->>'event_id')::uuid) IS DISTINCT FROM method THEN RAISE EXCEPTION 'T_AUDIT_METHOD %',i; END IF;
  -- Dashboard read names the method of the active certificate.
  pk:=gis.ldd_published_packet(adm,p,year,NULL);
  IF pk#>>'{source_identity,method_version}' IS DISTINCT FROM method OR pk->>'certificate_id' IS DISTINCT FROM cert->>'certificate_id'
   OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(pk->'source_identity') k)
      IS DISTINCT FROM ARRAY['data_year','dataset_id','edition_id','input_hash','method_version','month','namespace','product','province','scope','source_sha256','validation_result_id']
   OR gis.ldd_published_packet(adm,p,year,pk->>'snapshot_id')->>'snapshot_id' IS DISTINCT FROM pk->>'snapshot_id' THEN
   RAISE EXCEPTION 'T_PUBLISHED_PACKET %',left(pk::text,300); END IF;

  -- Withdrawal of the v2 Edition: wrong method refused, right method clears the pointer.
  IF i=1 THEN
   SELECT * INTO d FROM gis.datasets WHERE id=d.id;
   payload:=payload||jsonb_build_object('expected_dataset_revision',d.revision,'expected_active_edition_id',ed.id,'replacement_edition_id',NULL,'reason','t052 withdraw');
   failed:=false;
   BEGIN PERFORM gis.ldd_publication_command(adm,gen_random_uuid(),'withdraw',jsonb_set(payload,'{method_version}',to_jsonb(other)),NULL,true,false);
   EXCEPTION WHEN raise_exception THEN failed:=SQLERRM='GIS_PUBLICATION_METHOD_MISMATCH'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_WITHDRAW_WITH_WRONG_METHOD_ACCEPTED'; END IF;
   r:=gis.ldd_publication_command(adm,'dddddddd-0527-4000-8000-000000000001','withdraw',payload,NULL,true,false);
   IF (SELECT active_edition_id FROM gis.datasets WHERE id=d.id) IS NOT NULL
    OR (SELECT state FROM gis.editions WHERE id=ed.id)<>'withdrawn' THEN RAISE EXCEPTION 'T_WITHDRAW %',r; END IF;
   failed:=false;
   BEGIN PERFORM gis.ldd_published_packet(adm,p,year,NULL); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM='GIS_LDD_NOT_PUBLISHED'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_WITHDRAWN_STILL_PUBLISHED'; END IF;
  END IF;
 END LOOP;

 -- The new and replaced functions stay closed to every API and worker role; the public read keeps its grant.
 FOR role_name IN SELECT unnest(ARRAY['anon','authenticated','service_role','gis_worker','gis_native_worker']) LOOP
  IF has_function_privilege(role_name,'gis.ldd_prepare_report(uuid,jsonb)','EXECUTE')
   OR has_function_privilege(role_name,'gis.u052_previous_ldd_prepare_report(uuid,jsonb)','EXECUTE')
   OR has_function_privilege(role_name,'gis.ldd_prepare_method()','EXECUTE')
   OR has_function_privilege(role_name,'gis.publication_ready(uuid,uuid)','EXECUTE')
   OR has_function_privilege(role_name,'gis.ldd_verify_complete(uuid,uuid,uuid,jsonb)','EXECUTE')
   OR has_function_privilege(role_name,'gis.ldd_publication_command(uuid,uuid,text,jsonb,jsonb,boolean,boolean)','EXECUTE')
   OR has_function_privilege(role_name,'gis.ldd_published_packet(uuid,text,integer,text)','EXECUTE') THEN
   RAISE EXCEPTION 'T_FUNCTION_REACHABLE_BY %',role_name; END IF;
 END LOOP;
 IF NOT has_function_privilege('service_role','public.gis_publication_read(uuid,uuid,text)','EXECUTE')
  OR has_function_privilege('anon','public.gis_publication_read(uuid,uuid,text)','EXECUTE') THEN RAISE EXCEPTION 'T_PUBLIC_READ_GRANT'; END IF;
END $t$;
RESET ROLE;

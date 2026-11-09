-- 051 rolled-back lifecycle (caller: BEGIN; migration; ledger; this; ROLLBACK).
-- Settings t.actor (officer), t.worker (another profile), t.province come from the caller.
SET LOCAL ROLE gis_owner;
DO $t$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 ds jsonb; up jsonb; job jsonb; ok jsonb; bad jsonb; r jsonb; failed boolean; sha text:=repeat('e',64);
 gadm text:='ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21';
 ldd text:='1b6cf62b8f43504078c51c9ca3e94f6fffe56c2ca1b3765674d5aa2d7c62e1ac';
 ed gis.editions; jb gis.jobs; role_name text;
BEGIN
 ds:=gis.command(a,'dddddddd-0000-4000-8000-000000000001','create_dataset',jsonb_build_object('province',p,'data_year',2009,'month',0,'kind','ldd_shapefile','purpose','landuse','title','t051-ldd'),false)->'body';
 up:=gis.ldd_command(a,'dddddddd-0000-4000-8000-000000000002','upload',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','upload_id','dddddddd-0000-4000-8000-0000000000a1','sha256',sha,'byte_size',10,'crs','EPSG:32647','encoding','utf-8','source_label','t051'),false);
 PERFORM gis.ldd_command(a,'dddddddd-0000-4000-8000-000000000003','enqueue',jsonb_build_object('edition_id',up->'body'->>'edition_id','expected_revision',1),false);
 job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'ldd')->'job';
 IF job->>'upload_id'<>up->'body'->>'upload_id' THEN RAISE EXCEPTION 'T_CLAIM %',job; END IF;
 SELECT * INTO ed FROM gis.editions WHERE id=(up->'body'->>'edition_id')::uuid;
 SELECT * INTO jb FROM gis.jobs WHERE id=(job->>'id')::uuid;
 -- An accepted report, the shape a real validation produces, in the form the previous function expects.
 ok:=jsonb_build_object('schema_version',1,'provider_build','ldd-local-v1','upload_id',job->>'upload_id','artifact_sha256',sha,'observed_sha256',sha,'byte_size',10,
   'input_hash',job->>'input_hash','input_revision',job->'input_revision','province',p,'data_year',2009,'crs','EPSG:32647','encoding','utf-8','valid',true,
   'checks','["source_hash_match","archive_safety","components","crs","geometry","attributes","encoding","ldd_codes","province_bounds","dataset_association"]'::jsonb,
   'errors','[]'::jsonb,'warnings','[{"code":"BOUNDARY_FROM_DATA_PRODUCER","count":1},{"code":"DATA_YEAR_METADATA_DECLARED","count":1}]'::jsonb,'error_code',NULL::text,
   'boundary_sha256',gadm,
   'statistics','{"feature_count":3,"total_area_m2":100,"unknown_area_m2":0,"unknown_code_count":0,"composite_feature_count":0,"geometry_error_count":0,"area_by_main_m2":{"U":100,"A":0,"F":0,"W":0,"M":0}}'::jsonb);
 -- Both known assets pass; the 049/050 layers underneath still run (an audit is checked with either hash).
 PERFORM gis.validate_ldd_report(ok,ed,jb);
 PERFORM gis.validate_ldd_report(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),ed,jb);
 PERFORM gis.validate_ldd_report(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd))||jsonb_build_object('audit','{"policy_version":"ldd-policy-v2","outcome":"accepted","field_profile":"ldd-lu-text-v1","field_mapping":{"main_code":"LUL1_CODE","lu_code":"LU_CODE","declared_area":"Shape_Area"},"declared_area_units":"m2","feature_outcomes":{"accepted":3,"accepted_with_warnings":0,"review_required":0,"rejected":0},"boundary":{"minor":0,"review":0,"fatal":0,"outside_area_m2":0},"unknown_samples":[],"repairs":[],"repairs_total":0}'::jsonb),ed,jb);
 -- Nothing else is accepted: another hash, a near miss, a wrong type, a missing key.
 FOR bad IN SELECT x FROM unnest(ARRAY[
   jsonb_set(ok,'{boundary_sha256}',to_jsonb(repeat('0',64))), jsonb_set(ok,'{boundary_sha256}',to_jsonb(upper(ldd))),
   jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd||'0')), jsonb_set(ok,'{boundary_sha256}',to_jsonb(left(ldd,63))),
   jsonb_set(ok,'{boundary_sha256}','null'::jsonb), jsonb_set(ok,'{boundary_sha256}','42'::jsonb), ok-'boundary_sha256']) x LOOP
   failed:=false;
   BEGIN PERFORM gis.validate_ldd_report(bad,ed,jb);
   EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_BAD_BOUNDARY_HASH_ACCEPTED %',bad->'boundary_sha256'; END IF;
 END LOOP;
 -- Every other rule still holds with the new hash.
 FOR bad IN SELECT x FROM unnest(ARRAY[
   jsonb_set(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),'{upload_id}','"dddddddd-0000-4000-8000-0000000000ff"'),
   jsonb_set(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),'{province}','"Not A Province"'),
   jsonb_set(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),'{observed_sha256}',to_jsonb(repeat('f',64))),
   jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd))||'{"extra":1}'::jsonb,
   jsonb_set(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),'{statistics,unknown_code_count}','1'),
   jsonb_set(jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd)),'{checks}','["source_hash_match"]'),
   jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd))||jsonb_build_object('audit','{"outcome":"accepted"}'::jsonb)]) x LOOP
   failed:=false;
   BEGIN PERFORM gis.validate_ldd_report(bad,ed,jb);
   EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT failed THEN RAISE EXCEPTION 'T_OTHER_RULE_NOT_ENFORCED %',left(bad::text,200); END IF;
 END LOOP;
 -- A non-object report is still refused by the previous function, not by a type error of the wrapper.
 failed:=false;
 BEGIN PERFORM gis.validate_ldd_report('"text"'::jsonb,ed,jb); EXCEPTION WHEN raise_exception THEN failed:=SQLERRM LIKE 'GIS_%'; END;
 IF NOT failed THEN RAISE EXCEPTION 'T_NON_OBJECT_ACCEPTED'; END IF;
 -- The queue stores the accepted report with the hash it carried, not the one the previous function saw.
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',jsonb_set(ok,'{boundary_sha256}',to_jsonb(ldd))),'ldd');
 IF r->>'state' IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'T_COMPLETE_STATE %',r; END IF;
 IF (SELECT validation_report->>'boundary_sha256' FROM gis.attempts WHERE job_id=(job->>'id')::uuid)<>ldd THEN RAISE EXCEPTION 'T_STORED_HASH_CHANGED'; END IF;
 -- The functions stay closed to every API and worker role.
 FOR role_name IN SELECT unnest(ARRAY['anon','authenticated','service_role','gis_worker','gis_native_worker']) LOOP
   IF has_function_privilege(role_name,'gis.validate_ldd_report(jsonb,gis.editions,gis.jobs)','EXECUTE')
     OR has_function_privilege(role_name,'gis.u051_previous_validate_ldd_report(jsonb,gis.editions,gis.jobs)','EXECUTE') THEN
     RAISE EXCEPTION 'T_VALIDATOR_REACHABLE_BY %',role_name; END IF;
 END LOOP;
END $t$;
RESET ROLE;

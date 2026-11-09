-- 050 rolled-back lifecycle (caller: BEGIN; migration; ledger; this; ROLLBACK).
-- Settings t.actor (officer), t.worker (another profile), t.province come from the caller.
SET LOCAL ROLE gis_owner;
DO $t$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 ds jsonb; up jsonb; job jsonb; rep jsonb; audit jsonb; bad jsonb; r jsonb; ok boolean; sha text:=repeat('e',64);
BEGIN
 ds:=gis.command(a,'cccccccc-0000-4000-8000-000000000001','create_dataset',jsonb_build_object('province',p,'data_year',2008,'month',0,'kind','ldd_shapefile','purpose','landuse','title','t050-ldd'),false)->'body';
 up:=gis.ldd_command(a,'cccccccc-0000-4000-8000-000000000002','upload',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','upload_id','cccccccc-0000-4000-8000-0000000000a1','sha256',sha,'byte_size',10,'crs','EPSG:32647','encoding','utf-8','source_label','t050'),false);
 PERFORM gis.ldd_command(a,'cccccccc-0000-4000-8000-000000000003','enqueue',jsonb_build_object('edition_id',up->'body'->>'edition_id','expected_revision',1),false);
 job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'ldd')->'job';
 IF job->>'upload_id'<>up->'body'->>'upload_id' THEN RAISE EXCEPTION 'T_CLAIM %',job; END IF;
 rep:=jsonb_build_object('schema_version',1,'provider_build','ldd-local-v1','upload_id',job->>'upload_id','artifact_sha256',sha,'observed_sha256',sha,'byte_size',10,
   'input_hash',job->>'input_hash','input_revision',job->'input_revision','province',p,'data_year',2008,'crs','EPSG:32647','encoding','utf-8','valid',false,
   'checks','["source_hash_match"]'::jsonb,'errors','[{"code":"UNKNOWN_CODE_REVIEW_REQUIRED","count":1}]'::jsonb,'warnings','[]'::jsonb,'error_code','UNKNOWN_CODE_REVIEW_REQUIRED',
   'boundary_sha256','ac2b28255f22861ab644bf083fa40f28dd9da1294648d4b01cfc6f9cdc156a21',
   'statistics','{"feature_count":3,"total_area_m2":100,"unknown_area_m2":10,"unknown_code_count":1,"composite_feature_count":0,"geometry_error_count":0,"area_by_main_m2":{"U":90,"A":0,"F":0,"W":0,"M":0}}'::jsonb);
 audit:='{"policy_version":"ldd-policy-v2","outcome":"review_required","field_profile":"ldd-lu-text-v1","field_mapping":{"main_code":"LUL1_CODE","lu_code":"LU_CODE","declared_area":"Shape_Area"},"declared_area_units":"m2","feature_outcomes":{"accepted":2,"accepted_with_warnings":0,"review_required":1,"rejected":0},"boundary":{"minor":0,"review":0,"fatal":0,"outside_area_m2":0},"unknown_samples":[{"value":"X999","main":"U","reason":"LU_CODE_NOT_IN_LEGEND","count":1,"area_m2":10}],"repairs":[{"feature":1,"reason":"Self-intersection","area_before_m2":10,"area_after_m2":10,"type_before":"Polygon","type_after":"MultiPolygon"}],"repairs_total":1}';
 -- Bad audit objects are rejected before anything is recorded.
 FOR bad IN SELECT x FROM unnest(ARRAY[
   audit||'{"extra":1}', audit-'outcome', audit||'{"outcome":"accepted"}', audit||'{"outcome":"other"}', audit||'{"policy_version":"BAD VERSION"}',
   audit||'{"field_mapping":{"main_code":"A","evil":"B"}}', audit||'{"declared_area_units":"km2"}', audit||'{"repairs_total":0}',
   jsonb_set(audit,'{feature_outcomes,accepted}','5'), jsonb_set(audit,'{feature_outcomes,accepted}','-1'), audit#-'{feature_outcomes,rejected}',
   jsonb_set(audit,'{boundary,minor}','1.5'), jsonb_set(audit,'{unknown_samples,0,value}',to_jsonb(repeat('x',41))), jsonb_set(audit,'{unknown_samples,0,reason}','"bad reason"'),
   jsonb_set(audit,'{unknown_samples,0,count}','0'), jsonb_set(audit,'{repairs,0,type_after}','"<script>"'), jsonb_set(audit,'{repairs,0,area_after_m2}','-1'),
   jsonb_set(audit,'{unknown_samples}',(SELECT jsonb_agg(audit->'unknown_samples'->0) FROM generate_series(1,11))), '"text"'::jsonb]) x LOOP
   ok:=false;
   BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep||jsonb_build_object('audit',bad)),'ldd');
   EXCEPTION WHEN raise_exception THEN ok:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT ok THEN RAISE EXCEPTION 'T_BAD_AUDIT_ACCEPTED %',bad; END IF;
 END LOOP;
 -- A report with a review_required audit is stored and the edition stays unusable.
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep||jsonb_build_object('audit',audit)),'ldd');
 IF r->>'state'<>'failed' THEN RAISE EXCEPTION 'T_REVIEW_STATE %',r; END IF;
 IF (SELECT validation_report->'audit'->>'outcome' FROM gis.attempts WHERE job_id=(job->>'id')::uuid)<>'review_required' THEN RAISE EXCEPTION 'T_AUDIT_NOT_STORED'; END IF;
 IF gis.publication_validation((up->'body'->>'edition_id')::uuid) IS NOT NULL OR gis.eligible((up->'body'->>'edition_id')::uuid,(ds->>'id')::uuid) THEN RAISE EXCEPTION 'T_REVIEW_USABLE'; END IF;
 -- A report without audit, the shape already stored, still passes the same rules.
 PERFORM gis.validate_ldd_report(rep,(SELECT x FROM gis.editions x WHERE id=(up->'body'->>'edition_id')::uuid),(SELECT x FROM gis.jobs x WHERE id=(job->>'id')::uuid));
 -- An accepted report must say so and count every parcel.
 PERFORM gis.validate_ldd_audit(audit||'{"outcome":"accepted"}',rep||'{"valid":true}'||jsonb_build_object('statistics',jsonb_set(rep->'statistics','{feature_count}','3')));
 ok:=false; BEGIN PERFORM gis.validate_ldd_audit(audit||'{"outcome":"review_required"}',rep||'{"valid":true}');
 EXCEPTION WHEN raise_exception THEN ok:=true; END; IF NOT ok THEN RAISE EXCEPTION 'T_VALID_WITH_REVIEW_OUTCOME'; END IF;
 ok:=false; BEGIN PERFORM gis.validate_ldd_audit(audit||'{"outcome":"accepted"}',rep||'{"valid":true}'||jsonb_build_object('statistics',jsonb_set(rep->'statistics','{feature_count}','4')));
 EXCEPTION WHEN raise_exception THEN ok:=true; END; IF NOT ok THEN RAISE EXCEPTION 'T_FEATURE_COUNT_MISMATCH_ACCEPTED'; END IF;
 ok:=false; BEGIN PERFORM gis.validate_ldd_audit(audit,rep||'{"errors":[{"code":"OUTSIDE_PROVINCE","count":1}]}');
 EXCEPTION WHEN raise_exception THEN ok:=true; END; IF NOT ok THEN RAISE EXCEPTION 'T_FATAL_CALLED_REVIEW'; END IF;
END $t$;
RESET ROLE;

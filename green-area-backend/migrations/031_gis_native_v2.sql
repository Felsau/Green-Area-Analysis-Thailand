-- T3 forward-only Native Synthetic V2 contract. The guarded runner owns transaction+ledger.
-- No legacy schema/data, GIS state, queue lease or applied migration is rewritten.
GRANT CREATE ON SCHEMA public TO gis_owner;
SET LOCAL ROLE gis_owner;
SELECT gis.assert_environment();
DO $guard$
BEGIN
 IF current_database() NOT IN ('postgres','gis_t1_upgrade')
    OR NOT gis.target_ok()
    OR current_setting('gis.runtime_instance',true) !~ '^[0-9a-f]{32}$'
    OR current_setting('gis.baseline_fingerprint',true) !~ '^[0-9a-f]{64}$'
    OR current_setting('gis.runtime_instance',true) IS NULL
    OR current_setting('gis.baseline_fingerprint',true) IS NULL
    OR current_setting('server_version_num')::int < 170000 THEN
   RAISE EXCEPTION 'GIS_LOCAL_TARGET_REQUIRED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM gis.environment e WHERE singleton
    AND e.runtime_instance=current_setting('gis.runtime_instance',true)
    AND e.baseline_fingerprint=current_setting('gis.baseline_fingerprint',true))
    OR (SELECT count(*) FROM gis.schema_migrations WHERE
       (version=27 AND sha256='4d1ef87fccc1a484bd4a199b5bd74af2cf7adb4db7e03f55718f6553d43428d0')
       OR (version=28 AND sha256='fcf5d9530b516d93dda0fc2ea5b01158809aad237c1e90863d09bd324c9000d1')
       OR (version=29 AND sha256='7faf7bf6abbd4e52ab8389423c3c1876c94af459fe9d7c5d2a7710ffc0f236a5')
       OR (version=30 AND sha256='6e7cc972d648fe717539c63131f752440c79446a5ffcbe8608b232cd63a4914f'))<>4 THEN
   RAISE EXCEPTION 'GIS_LOCAL_TARGET_REQUIRED'; END IF;
END $guard$;

-- Extend attempts to store bounded validation report
ALTER TABLE gis.attempts ADD COLUMN IF NOT EXISTS validation_report jsonb;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='attempts_report_bounded') THEN
  ALTER TABLE gis.attempts ADD CONSTRAINT attempts_report_bounded CHECK(validation_report IS NULL OR octet_length(validation_report::text) <= 16384);
 END IF;
END $$;

-- Register Synthetic V2 catalog fixtures
INSERT INTO gis.synthetic_fixtures(id, kind, purpose, manifest)
VALUES
 ('t3-ldd-valid-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-ldd-valid-v2","sha256":"6a6494c8b54d4db0304239727f1081403737746cf4094dd150f63fa34e0d6930","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-ldd-cp874-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-ldd-cp874-v2","sha256":"fcd596f1d57856a6b02f1fd8b2d6fb739cf8a9fb2e99e643e67655b87855eb44","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-ldd-composite-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-ldd-composite-v2","sha256":"0a2d12576aa1ca121bc726dc46fb976454308a5e04e4210383d291a478135836","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-unknown-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-unknown-v2","sha256":"792ce3d907dacc83e0ef8db9fc8c0063b5edd22b1b12b75cf15a9f3c0a7c272b","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-zip-unsafe-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-zip-unsafe-v2","sha256":"6265283fdab5bd8a21c727d3989e5123e2bbfab4d2390f4d5b38560605237501","byte_size":135,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-zip-symlink-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-zip-symlink-v2","sha256":"86cdbeb52e9a86be7bd7d4397148f7bf7e7646e0f833a9f3d08dd6a435b0b6df","byte_size":115,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-ldd-missing-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-ldd-missing-v2","sha256":"e89b6ca39a01bc42d4255e2bef5aaa90adeea45fdffe12566474e07e8f76019c","byte_size":1444,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-s2-v2','geotiff','ndvi','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-s2-v2","sha256":"0df2fb44f202d28cc2bbac78c2f55c680a41bd9b2fbc033c4f2433f0c25d3930","byte_size":1526,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"S2_SR_DN","provider_build":"t3-native-v1","bands":["B8","B4","VALID_MASK"],"units":"DN","nodata":65535,"resolution":10,"scales":[0.0001,0.0001,1],"offsets":[0,0,0]}'::jsonb),
 ('t3-lst-v2','geotiff','lst','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-lst-v2","sha256":"0687f39ab001add7a8b20391f78c1edeb9ebd7524f3e15beed8367a4e6846531","byte_size":1357,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"LANDSAT_C2_L2_ST_DN","provider_build":"t3-native-v1","bands":["ST_B10","QA_PIXEL"],"units":"DN","nodata":0,"resolution":30,"scales":[0.00341802,1],"offsets":[149,0]}'::jsonb),
 ('t3-ndvi-ready-v2','geotiff','ndvi','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-ndvi-ready-v2","sha256":"53636d4a2f0e8f7aa61bd528b9e6c6251ff7cd26f79d81f6e3cfd1e3de9de565","byte_size":1045,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"NDVI_FLOAT","provider_build":"t3-native-v1","bands":["NDVI"],"units":"1","nodata":-9999,"resolution":10,"scales":[1],"offsets":[0]}'::jsonb),
 ('t3-lst-ready-v2','geotiff','lst','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-lst-ready-v2","sha256":"3d0e2e98ab7e8e884d4e84cb9b0b8c3025ca77b4fa5fa24b7003f5cc580bcb6f","byte_size":1048,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"LST_CELSIUS","provider_build":"t3-native-v1","bands":["LST"],"units":"degC","nodata":-9999,"resolution":10,"scales":[1],"offsets":[0]}'::jsonb),
 ('t3-kelvin-v2','geotiff','lst','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-kelvin-v2","sha256":"4b1302ac13a776fdad767d3b25304e5b43dbcf2b50524f7732a95f6f89a86920","byte_size":1044,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"LST_KELVIN","provider_build":"t3-native-v1","bands":["LST"],"units":"K","nodata":-9999,"resolution":10,"scales":[1],"offsets":[0]}'::jsonb),
 ('t3-nodata-v2','geotiff','lst','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-nodata-v2","sha256":"5803272a9bc15c8029b4190a3568a75676595fb7da7ca17c16567f015fbb6c26","byte_size":1357,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"raster","profile":"LANDSAT_C2_L2_ST_DN","provider_build":"t3-native-v1","bands":["ST_B10","QA_PIXEL"],"units":"DN","nodata":0,"resolution":30,"scales":[0.00341802,1],"offsets":[149,0]}'::jsonb),
 ('t3-timeout-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-timeout-v2","sha256":"6a6494c8b54d4db0304239727f1081403737746cf4094dd150f63fa34e0d6930","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-oom-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-oom-v2","sha256":"6a6494c8b54d4db0304239727f1081403737746cf4094dd150f63fa34e0d6930","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb),
 ('t3-transient-v2','ldd_shapefile','landuse','{"schema_version":2,"provider":"synthetic","fixture_id":"t3-transient-v2","sha256":"6a6494c8b54d4db0304239727f1081403737746cf4094dd150f63fa34e0d6930","byte_size":2370,"provenance":"synthetic-local-poc-20261026","crs":"EPSG:32647","data_kind":"polygon","profile":"LDD_SYNTHETIC","provider_build":"t3-native-v1","attributes":["LUL1_CODE","LU_CODE","Shape_Area","LU_DES_TH","LU_DES_EN"]}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- Update manifest hash to support Schema V1 and V2
CREATE OR REPLACE FUNCTION gis.manifest_hash(p_manifest jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE ver text;
BEGIN
 IF jsonb_typeof(p_manifest) IS DISTINCT FROM 'object' OR octet_length(p_manifest::text)>65536 THEN
   RAISE EXCEPTION 'GIS_INVALID_PAYLOAD'; END IF;
 ver := p_manifest->>'schema_version';
 IF ver = '1' THEN
   PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','fixture_id','sha256','byte_size','provenance','crs','data_kind','bands','units','nodata','resolution','attributes']);
   IF p_manifest->>'provider' NOT IN ('synthetic','real')
      OR p_manifest->>'provider' IS NULL
      OR COALESCE(p_manifest->>'sha256','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,8}$'
      OR COALESCE(p_manifest->>'provenance','') !~ '^[A-Za-z0-9 _.-]{1,100}$'
      OR COALESCE(p_manifest->>'crs','') !~ '^EPSG:[0-9]{4,6}$'
      OR COALESCE(p_manifest->>'data_kind','') NOT IN ('raster','polygon')
      OR p_manifest::text ~ '(https?://|file:|\\\\|\.\./)' THEN RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   IF p_manifest->>'provider'='real' THEN
    IF p_manifest ? 'fixture_id' OR (p_manifest->>'data_kind'='raster' AND
        (jsonb_typeof(p_manifest->'bands') IS DISTINCT FROM 'array'
         OR jsonb_array_length(p_manifest->'bands') NOT BETWEEN 1 AND 8
         OR COALESCE(p_manifest->>'units','') NOT IN ('celsius','unitless','categories')
         OR jsonb_typeof(p_manifest->'nodata') IS DISTINCT FROM 'number'
         OR jsonb_typeof(p_manifest->'resolution') IS DISTINCT FROM 'number'))
      OR (p_manifest->>'data_kind'='polygon' AND jsonb_typeof(p_manifest->'attributes') IS DISTINCT FROM 'array') THEN
      RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'bands','[]')) value
        WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_manifest->'attributes','[]')) value
        WHERE jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[A-Za-z][A-Za-z0-9_]{0,39}$')
      OR (p_manifest ? 'resolution' AND (p_manifest->>'resolution')::numeric NOT BETWEEN 0.001 AND 10000)
      OR (p_manifest ? 'nodata' AND abs((p_manifest->>'nodata')::numeric)>1e12)
      OR (p_manifest ? 'attributes' AND jsonb_array_length(p_manifest->'attributes')>30) THEN
      RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   END IF;
   IF p_manifest->>'provider'='synthetic' AND NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest) THEN
     RAISE EXCEPTION 'GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED'; END IF;
 ELSIF ver = '2' THEN
   PERFORM gis.keys(p_manifest,ARRAY['schema_version','provider','fixture_id','sha256','byte_size','provenance','crs','data_kind','profile','provider_build','bands','units','nodata','resolution','attributes','scales','offsets']);
   IF p_manifest->>'provider' <> 'synthetic'
      OR COALESCE(p_manifest->>'sha256','') !~ '^[0-9a-f]{64}$'
      OR COALESCE(p_manifest->>'byte_size','') !~ '^[1-9][0-9]{0,8}$'
      OR COALESCE(p_manifest->>'provenance','') !~ '^[A-Za-z0-9 _.-]{1,100}$'
      OR COALESCE(p_manifest->>'crs','') !~ '^EPSG:[0-9]{4,6}$'
      OR COALESCE(p_manifest->>'data_kind','') NOT IN ('raster','polygon')
      OR COALESCE(p_manifest->>'provider_build','') !~ '^[A-Za-z0-9 _.-]{1,60}$'
      OR p_manifest::text ~ '(https?://|file:|\\\\|\.\./)' THEN RAISE EXCEPTION 'GIS_INVALID_MANIFEST'; END IF;
   IF NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=p_manifest) THEN
     RAISE EXCEPTION 'GIS_SYNTHETIC_MANIFEST_NOT_ALLOWLISTED'; END IF;
 ELSE
   RAISE EXCEPTION 'GIS_INVALID_MANIFEST';
 END IF;
 RETURN encode(sha256(convert_to(p_manifest::text,'UTF8')),'hex');
END $f$;

-- Worker V2 Implementation
CREATE OR REPLACE FUNCTION gis.worker_v2(p_action text, p_payload jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE
 candidate record; j record; e record; v_now timestamptz;
 jid uuid; eid uuid; worker uuid; token uuid; rid uuid;
 progress_value integer; report_value jsonb; code text; next_state text; n integer:=0;
BEGIN
 PERFORM gis.assert_environment();
 IF p_action='claim' THEN
  PERFORM gis.keys(p_payload,ARRAY['worker_id']);
  worker:=(p_payload->>'worker_id')::uuid;
  IF worker IS NULL THEN RAISE EXCEPTION 'GIS_WORKER_REQUIRED'; END IF;
  IF NOT pg_try_advisory_xact_lock(hashtextextended('gis-t1-single-claim',0)) THEN RETURN jsonb_build_object('job',NULL); END IF;
  IF (SELECT count(*) FROM gis.jobs WHERE state='running')>=1 THEN
   RETURN jsonb_build_object('job',NULL,'running_limit_reached',true);
  END IF;
  SELECT * INTO j FROM gis.jobs WHERE state='queued' AND attempt_count<3 AND available_at<=clock_timestamp()
   ORDER BY available_at,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1;
  IF NOT FOUND THEN RETURN jsonb_build_object('job',NULL); END IF;
  SELECT * INTO e FROM gis.editions WHERE id=j.edition_id FOR UPDATE;
  IF e.state<>'validating' THEN
   UPDATE gis.jobs SET state='failed',error_code='invalid_data',finished_at=clock_timestamp() WHERE id=j.id;
   RETURN jsonb_build_object('job',NULL);
  END IF;
  v_now:=clock_timestamp();
  token:=gen_random_uuid();
  UPDATE gis.jobs SET state='running',attempt_count=attempt_count+1,worker_id=worker,
   lease_token=token,lease_until=v_now+interval '60 seconds',progress=0,error_code=NULL WHERE id=j.id RETURNING * INTO j;
  INSERT INTO gis.attempts(job_id,attempt_no,worker_id,lease_token,state,progress,started_at)
   VALUES(j.id,j.attempt_count,worker,token,'running',0,v_now);
  INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
   VALUES('worker_v2.claim',e.dataset_id,e.id,j.id,jsonb_build_object('worker_id',worker,'attempt',j.attempt_count));
  RETURN jsonb_build_object('job',jsonb_build_object(
   'id',j.id,
   'job_id',j.id,
   'edition_id',j.edition_id,
   'dataset_id',e.dataset_id,
   'kind',j.kind,
   'input_revision',j.input_revision,
   'input_hash',j.input_hash,
   'validator_version',j.validator_version,
   'attempt_number',j.attempt_count,
   'attempt_no',j.attempt_count,
   'manifest',e.manifest,
   'lease_token',token,
   'lease_until',j.lease_until));
 ELSIF p_action='recover' THEN
  PERFORM gis.keys(p_payload,ARRAY[]::text[]);
  FOR candidate IN SELECT id,edition_id FROM gis.jobs WHERE state='running' AND lease_until<=clock_timestamp()
      ORDER BY lease_until,id LIMIT 20 LOOP
   SELECT * INTO e FROM gis.editions WHERE id=candidate.edition_id FOR UPDATE SKIP LOCKED;
   IF NOT FOUND THEN CONTINUE; END IF;
   SELECT * INTO j FROM gis.jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
   IF NOT FOUND THEN CONTINUE; END IF;
   v_now:=clock_timestamp();
   IF j.state<>'running' OR j.lease_until>v_now THEN CONTINUE; END IF;
   UPDATE gis.attempts SET state='expired',error_code='lease_expired',finished_at=v_now
    WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=j.lease_token AND state='running';
   IF j.attempt_count<3 THEN
    UPDATE gis.jobs SET state='queued',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=0,
     available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int)
     WHERE id=j.id;
   ELSE
    UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,
     error_code='attempts_exhausted',finished_at=v_now WHERE id=j.id;
    UPDATE gis.editions SET state='draft' WHERE id=e.id AND state='validating';
   END IF;
   INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
    VALUES('worker_v2.recover',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'terminal',j.attempt_count=3));
   n:=n+1;
  END LOOP;
  RETURN jsonb_build_object('recovered',n);
 ELSIF p_action IN ('heartbeat','complete','fail') THEN
  PERFORM gis.keys(p_payload,CASE p_action
   WHEN 'heartbeat' THEN ARRAY['job_id','worker_id','lease_token','progress']
   WHEN 'complete' THEN ARRAY['job_id','worker_id','lease_token','report']
   ELSE ARRAY['job_id','worker_id','lease_token','error_code','report'] END);
  jid:=(p_payload->>'job_id')::uuid;worker:=(p_payload->>'worker_id')::uuid;token:=(p_payload->>'lease_token')::uuid;
  IF p_action<>'heartbeat' THEN
   SELECT edition_id INTO eid FROM gis.jobs WHERE id=jid;
   SELECT * INTO e FROM gis.editions WHERE id=eid FOR UPDATE;
  END IF;
  SELECT * INTO j FROM gis.jobs WHERE id=jid FOR UPDATE;
  v_now:=clock_timestamp();
  IF NOT FOUND OR j.state<>'running' OR j.worker_id IS DISTINCT FROM worker
     OR j.lease_token IS DISTINCT FROM token OR j.lease_until<=v_now THEN
   RAISE EXCEPTION 'GIS_STALE_LEASE'; END IF;
  IF p_action='heartbeat' THEN
   progress_value:=(p_payload->>'progress')::integer;
   IF progress_value IS NULL OR progress_value<j.progress OR progress_value>99 THEN RAISE EXCEPTION 'GIS_INVALID_PROGRESS'; END IF;
   UPDATE gis.jobs SET progress=progress_value,lease_until=v_now+interval '60 seconds' WHERE id=j.id;
   UPDATE gis.attempts SET progress=progress_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   RETURN jsonb_build_object('job_id',j.id,'lease_until',v_now+interval '60 seconds','progress',progress_value);
  END IF;
  IF e.state<>'validating' OR e.input_revision<>j.input_revision OR e.input_hash<>j.input_hash THEN
   RAISE EXCEPTION 'GIS_INPUT_CHANGED'; END IF;
  IF p_action='complete' THEN
   report_value:=p_payload->'report';
   IF jsonb_typeof(report_value) IS DISTINCT FROM 'object' OR octet_length(report_value::text)>16384 THEN
     RAISE EXCEPTION 'GIS_INVALID_RESULT'; END IF;
   IF report_value->>'fixture_id' IS DISTINCT FROM e.manifest->>'fixture_id'
      OR report_value->>'input_hash' IS DISTINCT FROM j.input_hash
      OR (report_value->>'input_revision')::integer IS DISTINCT FROM j.input_revision
      OR report_value->>'provider_build' IS DISTINCT FROM 't3-native-v1'
      OR NOT EXISTS(SELECT 1 FROM gis.synthetic_fixtures WHERE manifest=e.manifest) THEN
     RAISE EXCEPTION 'GIS_INVALID_RESULT'; END IF;
   UPDATE gis.attempts SET validation_report=report_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   IF report_value->'valid' = 'true'::jsonb THEN
     INSERT INTO gis.results(job_id,edition_id,input_revision,input_hash,validator_version,attempt_no,lease_token,valid,report)
      VALUES(j.id,e.id,j.input_revision,j.input_hash,j.validator_version,j.attempt_count,token,true,report_value) RETURNING id INTO rid;
     UPDATE gis.editions SET state='validated',validated_result_id=rid WHERE id=e.id;
     UPDATE gis.jobs SET state='succeeded',worker_id=NULL,lease_token=NULL,lease_until=NULL,progress=100,finished_at=v_now WHERE id=j.id;
     UPDATE gis.attempts SET state='succeeded',progress=100,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
      VALUES('worker_v2.complete',e.dataset_id,e.id,j.id,jsonb_build_object('result_id',rid,'attempt',j.attempt_count,'valid',true));
     RETURN jsonb_build_object('job_id',j.id,'state','succeeded','result_id',rid);
   ELSE
     code:=COALESCE(report_value->>'error_code','invalid_data');
     UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
     UPDATE gis.jobs SET state='failed',worker_id=NULL,lease_token=NULL,lease_until=NULL,error_code='invalid_data',progress=0,finished_at=v_now WHERE id=j.id;
     UPDATE gis.editions SET state='draft' WHERE id=e.id;
     INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
      VALUES('worker_v2.fail',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state','failed','valid',false));
     RETURN jsonb_build_object('job_id',j.id,'state','failed','error_code',code);
   END IF;
  END IF;
  -- fail action
  code:=p_payload->>'error_code';
  IF code IS NULL THEN RAISE EXCEPTION 'GIS_INVALID_FAILURE'; END IF;
  report_value:=p_payload->'report';
  IF report_value IS NOT NULL AND report_value<>'null'::jsonb THEN
   IF octet_length(report_value::text)<=16384 THEN
     UPDATE gis.attempts SET validation_report=report_value WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
   END IF;
  END IF;
  next_state:=CASE WHEN code='transient' AND j.attempt_count<3 THEN 'queued' ELSE 'failed' END;
  UPDATE gis.attempts SET state='failed',error_code=code,finished_at=v_now WHERE job_id=j.id AND attempt_no=j.attempt_count AND lease_token=token;
  UPDATE gis.jobs SET state=next_state,worker_id=NULL,lease_token=NULL,lease_until=NULL,
   error_code=CASE WHEN next_state='failed' THEN (CASE WHEN code IN ('invalid_data','transient') THEN code ELSE 'invalid_data' END) ELSE NULL END,progress=0,
   available_at=v_now+make_interval(secs=>CASE j.attempt_count WHEN 1 THEN 5 ELSE 20 END+floor(random()*3)::int),
   finished_at=CASE WHEN next_state='failed' THEN v_now ELSE NULL END WHERE id=j.id;
  IF next_state='failed' THEN UPDATE gis.editions SET state='draft' WHERE id=e.id; END IF;
  INSERT INTO gis.audit(operation,dataset_id,edition_id,job_id,detail)
   VALUES('worker_v2.fail',e.dataset_id,e.id,j.id,jsonb_build_object('attempt',j.attempt_count,'error_code',code,'state',next_state));
  RETURN jsonb_build_object('job_id',j.id,'state',next_state,'error_code',code);
 END IF;
 RAISE EXCEPTION 'GIS_UNKNOWN_WORKER_ACTION';
END $f$;

-- Update API read projection row to include validation_report on attempts
CREATE OR REPLACE FUNCTION gis.api_read_row(p_kind text,p_row jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,gis AS $f$
DECLARE fields text[]; result_value jsonb; checks_value jsonb; fixture text; code text;
BEGIN
 fields:=CASE
  WHEN p_kind IN ('datasets','dataset') THEN ARRAY['id','province','data_year','month','kind','purpose','title','revision','active_edition_id','created_at']
  WHEN p_kind IN ('editions','edition') THEN ARRAY['id','dataset_id','cloned_from_id','state','input_revision','manifest','input_hash','validated_result_id','created_at']
  WHEN p_kind IN ('jobs','job') THEN ARRAY['id','edition_id','parent_job_id','kind','input_revision','input_hash','validator_version','state','attempt_count','available_at','progress','created_at','finished_at']
  WHEN p_kind='attempts' THEN ARRAY['id','job_id','attempt_no','state','progress','started_at','finished_at','validation_report']
  WHEN p_kind='history' THEN ARRAY['id','operation','dataset_id','edition_id','job_id','reason','created_at']
  WHEN p_kind='officers' THEN ARRAY['id','user_id','created_at']
  WHEN p_kind='result' THEN ARRAY['id','job_id','edition_id','input_revision','input_hash','validator_version','attempt_no','provider','valid','created_at']
 END;
 IF fields IS NULL THEN RAISE EXCEPTION 'GIS_UNKNOWN_READ'; END IF;
 IF p_row IS NULL THEN RETURN NULL; END IF;
 result_value:=gis.api_project(p_row,fields);
 IF p_kind IN ('jobs','job','attempts') THEN
  code:=p_row->>'error_code';
  result_value:=result_value||jsonb_build_object('error_code',CASE
   WHEN code IN ('invalid_data','transient','attempts_exhausted','lease_expired') THEN code
   WHEN code IS NULL THEN NULL ELSE 'internal_error' END);
 ELSIF p_kind='history' THEN
  result_value:=result_value||jsonb_build_object('detail',gis.api_project(p_row->'detail',
   ARRAY['result_id','attempt','terminal','error_code','state','worker_id','user_id','previous_edition_id','replacement_edition_id']));
 ELSIF p_kind='result' THEN
  fixture:=p_row->'report'->>'fixture_id';
  checks_value:=p_row->'report'->'checks';
  result_value:=result_value||jsonb_build_object('report',jsonb_build_object(
   'valid',p_row->'report'->'valid',
   'fixture_id',CASE WHEN fixture ~ '^[A-Za-z0-9_-]{1,60}$' THEN fixture ELSE NULL END,
   'checks',CASE WHEN jsonb_typeof(checks_value)='array' THEN checks_value ELSE '[]'::jsonb END));
 END IF;
 RETURN result_value;
END $f$;

-- Public entrypoints and permissions
CREATE OR REPLACE FUNCTION public.gis_worker_v2(p_action text,p_payload jsonb DEFAULT '{}')
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT gis.worker_v2(p_action,p_payload) $f$;

CREATE OR REPLACE FUNCTION public.gis_worker_readiness_v2()
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,gis
AS $f$ SELECT jsonb_build_object('status','ready','contract_version','1.2.0-t3','worker_role','gis_native_worker') $f$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gis FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_worker_v2(text,jsonb) FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;
REVOKE ALL ON FUNCTION public.gis_worker_readiness_v2() FROM PUBLIC,anon,authenticated,service_role,gis_worker,gis_native_worker;

GRANT EXECUTE ON FUNCTION public.gis_worker_v2(text,jsonb) TO gis_native_worker;
GRANT EXECUTE ON FUNCTION public.gis_worker_readiness_v2() TO gis_native_worker;
GRANT USAGE ON SCHEMA public TO gis_native_worker;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM gis_owner;
NOTIFY pgrst, 'reload schema';

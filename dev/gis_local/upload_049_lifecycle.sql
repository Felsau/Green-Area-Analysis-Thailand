-- 049 rolled-back lifecycle (caller: BEGIN; migration; ledger; this; ROLLBACK).
-- Settings t.actor (officer), t.worker (another profile), t.province come from the caller.
SET LOCAL ROLE gis_owner;
DO $t$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 ds jsonb; lddset jsonb; up jsonb; r jsonb; job jsonb; rep jsonb; bad jsonb; ok boolean; sha text:=repeat('b',64); ready jsonb; pre jsonb; u gis.geotiff_uploads%ROWTYPE;
 up_base jsonb; ldd_base jsonb;
BEGIN
 -- Ready manifests are byte-identical to the reviewed 036 shape.
 u.sha256:=sha;u.byte_size:=10;u.crs:='EPSG:4326';u.profile:='lst_kelvin_ready';u.metric:='lst';
 IF gis.geotiff_manifest(u) IS DISTINCT FROM jsonb_build_object('schema_version',4,'provider','local_geotiff','provenance','local-geotiff-upload-v1',
   'sha256',sha,'byte_size',10,'crs','EPSG:4326','data_kind','raster','profile','lst_kelvin_ready','metric','lst','bands',jsonb_build_array('LST'),'units','kelvin') THEN
   RAISE EXCEPTION 'T_READY_MANIFEST_CHANGED'; END IF;

 -- LDD declaration
 lddset:=gis.command(a,'bbbbbbbb-0000-4000-8000-000000000001','create_dataset',jsonb_build_object('province',p,'data_year',2005,'month',0,'kind','ldd_shapefile','purpose','landuse','title','t049-ldd'),false)->'body';
 ldd_base:=jsonb_build_object('dataset_id',lddset->>'id','expected_revision',lddset->'revision','upload_id','bbbbbbbb-0000-4000-8000-0000000000a1','sha256',sha,'byte_size',10,'crs','EPSG:32647','encoding','utf-8');
 FOR bad IN SELECT x FROM unnest(ARRAY[ldd_base, ldd_base||'{"source_label":"   "}', ldd_base||'{"source_label":5}', ldd_base||jsonb_build_object('source_label',repeat('x',256)),
   ldd_base||jsonb_build_object('source_label',E'a\nb')]) x LOOP
   ok:=false; BEGIN PERFORM gis.ldd_command(a,gen_random_uuid(),'upload',bad,false);
   EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_UPLOAD_SOURCE_REQUIRED'; END;
   IF NOT ok THEN RAISE EXCEPTION 'T_LDD_SOURCE_ACCEPTED %',bad; END IF;
 END LOOP;
 r:=gis.ldd_command(a,'bbbbbbbb-0000-4000-8000-000000000002','upload',ldd_base||'{"source_label":"  กรมพัฒนาที่ดิน 2566  "}',false);
 IF r->'status'<>'201'::jsonb OR r->'body'->>'source_label'<>'กรมพัฒนาที่ดิน 2566' OR r->'body'->'acquisition_date'<>'null'::jsonb THEN RAISE EXCEPTION 'T_LDD_UPLOAD %',r; END IF;
 -- A replay returns it; the same key with another source conflicts.
 r:=gis.ldd_command(a,'bbbbbbbb-0000-4000-8000-000000000002','upload',ldd_base||'{"source_label":"กรมพัฒนาที่ดิน 2566"}',false);
 IF r->'body'->>'source_label'<>'กรมพัฒนาที่ดิน 2566' THEN RAISE EXCEPTION 'T_LDD_REPLAY %',r; END IF;
 ok:=false; BEGIN PERFORM gis.ldd_command(a,'bbbbbbbb-0000-4000-8000-000000000002','upload',ldd_base||'{"source_label":"อื่น"}',false);
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_UPLOAD_DECLARATION_CONFLICT'; END; IF NOT ok THEN RAISE EXCEPTION 'T_LDD_CONFLICT'; END IF;
 -- LDD upload rows reach the worker unchanged, and reads show the declaration.
 IF gis.ldd_upload_row((SELECT x FROM gis.ldd_uploads x WHERE id=(ldd_base->>'upload_id')::uuid)) ? 'source_label' THEN RAISE EXCEPTION 'T_WORKER_ROW_CHANGED'; END IF;
 IF public.gis_ldd_read(a,(ldd_base->>'upload_id')::uuid)->>'source_label'<>'กรมพัฒนาที่ดิน 2566' THEN RAISE EXCEPTION 'T_LDD_READ'; END IF;
 -- Declarations cannot be edited or deleted.
 ok:=false; BEGIN UPDATE gis.upload_declarations SET source_label='x' WHERE edition_id=(SELECT edition_id FROM gis.ldd_uploads WHERE id=(ldd_base->>'upload_id')::uuid);
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_UPLOAD_IMMUTABLE'; END; IF NOT ok THEN RAISE EXCEPTION 'T_DECLARATION_EDITED'; END IF;
 ok:=false; BEGIN DELETE FROM gis.upload_declarations WHERE edition_id=(SELECT edition_id FROM gis.ldd_uploads WHERE id=(ldd_base->>'upload_id')::uuid);
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_HARD_DELETE_FORBIDDEN'; END; IF NOT ok THEN RAISE EXCEPTION 'T_DECLARATION_DELETED'; END IF;

 -- GeoTIFF declaration: the date must fall inside the dataset period.
 ds:=gis.command(a,'bbbbbbbb-0000-4000-8000-000000000003','create_dataset',jsonb_build_object('province',p,'data_year',2006,'month',3,'kind','geotiff','purpose','ndvi','title','t049-geo'),false)->'body';
 up_base:=jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','upload_id','bbbbbbbb-0000-4000-8000-0000000000b1','sha256',sha,'byte_size',10,'crs','EPSG:4326','profile','ndvi_bands','source_label','Sentinel-2');
 FOR bad,r IN SELECT x,y FROM (VALUES
   (up_base,'"GIS_UPLOAD_DATE_REQUIRED"'::jsonb),
   (up_base||'{"acquisition_date":"2006-13-01"}','"GIS_UPLOAD_DATE_REQUIRED"'),
   (up_base||'{"acquisition_date":"2006-3-1"}','"GIS_UPLOAD_DATE_REQUIRED"'),
   (up_base||'{"acquisition_date":"2006-04-01"}','"GIS_UPLOAD_DATE_OUTSIDE_PERIOD"'),
   (up_base||'{"acquisition_date":"2005-03-01"}','"GIS_UPLOAD_DATE_OUTSIDE_PERIOD"')) v(x,y) LOOP
   ok:=false; BEGIN PERFORM gis.geotiff_command(a,gen_random_uuid(),'upload',bad,false);
   EXCEPTION WHEN raise_exception THEN ok:=to_jsonb(SQLERRM)=r; END;
   IF NOT ok THEN RAISE EXCEPTION 'T_GEO_DATE_ACCEPTED %',bad; END IF;
 END LOOP;
 -- A band profile must match the dataset metric, and unknown profiles stay rejected.
 ok:=false; BEGIN PERFORM gis.geotiff_command(a,gen_random_uuid(),'preflight',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','profile','lst_st_b10','crs','EPSG:4326'),false);
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_GEOTIFF_DATASET_REQUIRED'; END; IF NOT ok THEN RAISE EXCEPTION 'T_METRIC_MISMATCH'; END IF;
 ok:=false; BEGIN PERFORM gis.geotiff_command(a,gen_random_uuid(),'preflight',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','profile','raw_dn','crs','EPSG:4326'),false);
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_INVALID_PAYLOAD'; END; IF NOT ok THEN RAISE EXCEPTION 'T_UNKNOWN_PROFILE'; END IF;
 up:=gis.geotiff_command(a,'bbbbbbbb-0000-4000-8000-000000000004','upload',up_base||'{"acquisition_date":"2006-03-15"}',false);
 IF up->'status'<>'201'::jsonb OR up->'body'->>'acquisition_date'<>'2006-03-15' OR up->'body'->>'source_label'<>'Sentinel-2' THEN RAISE EXCEPTION 'T_GEO_UPLOAD %',up; END IF;
 IF (SELECT manifest->'bands' FROM gis.editions WHERE id=(up->'body'->>'edition_id')::uuid)<>'["B4","B8"]'::jsonb THEN RAISE EXCEPTION 'T_BANDS_MANIFEST'; END IF;
 IF gis.geotiff_upload_row((SELECT x FROM gis.geotiff_uploads x WHERE id=(up->'body'->>'upload_id')::uuid)) ? 'source_label' THEN RAISE EXCEPTION 'T_WORKER_ROW_CHANGED'; END IF;
 IF public.gis_geotiff_read(a,(up->'body'->>'upload_id')::uuid)->>'acquisition_date'<>'2006-03-15' THEN RAISE EXCEPTION 'T_GEO_READ'; END IF;

 -- The validation job linked to the file computes the result.
 r:=gis.geotiff_command(a,'bbbbbbbb-0000-4000-8000-000000000005','enqueue',jsonb_build_object('edition_id',up->'body'->>'edition_id','expected_revision',1),false);
 IF r->'status'<>'202'::jsonb THEN RAISE EXCEPTION 'T_ENQUEUE %',r; END IF;
 job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'geotiff')->'job';
 IF job->>'upload_id'<>up->'body'->>'upload_id' OR job->'manifest'->>'profile'<>'ndvi_bands' OR job ? 'source_label' THEN RAISE EXCEPTION 'T_CLAIM %',job; END IF;
 rep:=jsonb_build_object('schema_version',1,'provider_build','geotiff-local-v1','upload_id',job->>'upload_id','artifact_sha256',sha,'observed_sha256',sha,'byte_size',10,
   'input_hash',job->>'input_hash','input_revision',job->'input_revision','province',p,'data_year',2006,'valid',true,
   'checks','["source_hash_match","tiff_structure","crs","bands","resolution","dimensions","dtype","nodata","scale_offset","units","coverage","scientific_range","metadata_consistency"]'::jsonb,
   'errors','[]'::jsonb,'warnings','[{"code":"BOUNDARY_APPROXIMATE","count":1}]'::jsonb,'error_code',null,
   'statistics','{"width":4,"height":4,"band_count":2,"total_pixels":16,"valid_pixels":10,"nodata_pixels":2,"nonfinite_pixels":0,"outside_area_pixels":4,"mean":0.5,"min":0.1,"max":0.9}'::jsonb,
   'metadata','{"crs":"EPSG:4326","bands":["B4","B8"],"resolution":[0.001,0.001],"dtype":"uint16","nodata":0,"units":"reflectance","scales":[1,1],"offsets":[0,0],"profile":"ndvi_bands","output_units":"unitless"}'::jsonb,
   'coverage',jsonb_build_object('mode','province_boundary_clip','boundary_sha256',repeat('c',64),'boundary_approximate',true,'fraction_of_province',0.2,'fraction_of_file',0.75));
 FOR bad IN SELECT x FROM unnest(ARRAY[
   rep-'coverage', rep||'{"coverage":null}', rep||'{"extra":1}', rep||'{"province":"Elsewhere"}', rep||'{"data_year":2005}',
   jsonb_set(rep,'{statistics,mean}','2'), jsonb_set(rep,'{statistics,min}','0.6'), jsonb_set(rep,'{statistics,band_count}','1'),
   jsonb_set(rep,'{statistics,valid_pixels}','11'), rep#-'{statistics,outside_area_pixels}', jsonb_set(rep,'{metadata,bands}','["NDVI"]'),
   jsonb_set(rep,'{metadata,profile}','"ndvi_ready"'), jsonb_set(rep,'{metadata,output_units}','"celsius"'), jsonb_set(rep,'{metadata,scales}','[1]'),
   jsonb_set(rep,'{coverage,fraction_of_province}','0'), jsonb_set(rep,'{coverage,fraction_of_file}','1.5'), jsonb_set(rep,'{coverage,boundary_approximate}','false'),
   jsonb_set(rep,'{coverage,mode}','"other"'), rep||jsonb_build_object('checks',(rep->'checks')-'coverage')]) x LOOP
   ok:=false;
   BEGIN PERFORM gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',bad),'geotiff');
   EXCEPTION WHEN raise_exception THEN ok:=SQLERRM LIKE 'GIS_%'; END;
   IF NOT ok THEN RAISE EXCEPTION 'T_BAD_REPORT_ACCEPTED %',bad; END IF;
 END LOOP;
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep),'geotiff');
 IF r->>'state'<>'succeeded' THEN RAISE EXCEPTION 'T_COMPLETE %',r; END IF;
 PERFORM set_config('t.edition',up->'body'->>'edition_id',false);
 PERFORM set_config('t.dataset',ds->>'id',false);
END $t$;
SET CONSTRAINTS ALL IMMEDIATE;
SET CONSTRAINTS ALL DEFERRED;

DO $t2$ DECLARE a uuid:=current_setting('t.actor')::uuid; w uuid:=current_setting('t.worker')::uuid; p text:=current_setting('t.province');
 e uuid:=current_setting('t.edition')::uuid; d uuid:=current_setting('t.dataset')::uuid; r jsonb; ok boolean; sha text:=repeat('d',64); ds jsonb; up jsonb; job jsonb; rep jsonb;
BEGIN
 -- A computed band edition cannot enter the prepare or publication paths and is not active.
 IF gis.publication_validation(e) IS NOT NULL THEN RAISE EXCEPTION 'T_BAND_PREPARABLE'; END IF;
 IF gis.eligible(e,d) OR EXISTS(SELECT 1 FROM gis.datasets WHERE id=d AND active_edition_id IS NOT NULL) THEN RAISE EXCEPTION 'T_BAND_ACTIVE'; END IF;
 ok:=false; BEGIN PERFORM gis.geotiff_prepare_command(a,gen_random_uuid(),'enqueue',jsonb_build_object('edition_id',e,'expected_dataset_revision',1,'expected_input_revision',1,
   'input_hash',(SELECT input_hash FROM gis.editions WHERE id=e),'province',p,'data_year',2006,'month',3,'validation_result_id',(SELECT x.id FROM gis.results x JOIN gis.jobs j ON j.id=x.job_id WHERE j.edition_id=e)));
 EXCEPTION WHEN raise_exception THEN ok:=SQLERRM='GIS_PREPARE_VALIDATION_REQUIRED'; END; IF NOT ok THEN RAISE EXCEPTION 'T_BAND_PREPARE_ACCEPTED'; END IF;
 -- The edition read used by the page shows the declaration.
 r:=gis.api_read_row('edition',to_jsonb((SELECT x FROM gis.editions x WHERE id=e)));
 IF r->'upload'->>'source_label' IS DISTINCT FROM 'Sentinel-2' OR r->'upload'->>'acquisition_date' IS DISTINCT FROM '2006-03-15' THEN RAISE EXCEPTION 'T_EDITION_READ %',r; END IF;
 r:=gis.api_read_row('editions',to_jsonb((SELECT x FROM gis.editions x WHERE id=e)));
 IF r->'upload'->>'source_label' IS DISTINCT FROM 'Sentinel-2' THEN RAISE EXCEPTION 'T_EDITIONS_READ %',r; END IF;

 -- A failed band report records no values and keeps its error code.
 ds:=gis.command(a,'bbbbbbbb-0000-4000-8000-000000000006','create_dataset',jsonb_build_object('province',p,'data_year',2007,'month',0,'kind','geotiff','purpose','lst','title','t049-lst'),false)->'body';
 up:=gis.geotiff_command(a,'bbbbbbbb-0000-4000-8000-000000000007','upload',jsonb_build_object('dataset_id',ds->>'id','expected_revision',ds->'revision','upload_id','bbbbbbbb-0000-4000-8000-0000000000c1',
   'sha256',sha,'byte_size',10,'crs','EPSG:32647','profile','lst_st_b10','source_label','Landsat 9','acquisition_date','2007-06-01'),false);
 IF (SELECT manifest->>'units' FROM gis.editions WHERE id=(up->'body'->>'edition_id')::uuid)<>'landsat_c2_l2_dn' THEN RAISE EXCEPTION 'T_LST_MANIFEST'; END IF;
 PERFORM gis.geotiff_command(a,'bbbbbbbb-0000-4000-8000-000000000008','enqueue',jsonb_build_object('edition_id',up->'body'->>'edition_id','expected_revision',1),false);
 job:=gis.queue_protocol_kind('claim',jsonb_build_object('worker_id',w),'geotiff')->'job';
 rep:=jsonb_build_object('schema_version',1,'provider_build','geotiff-local-v1','upload_id',job->>'upload_id','artifact_sha256',sha,'observed_sha256',sha,'byte_size',10,
   'input_hash',job->>'input_hash','input_revision',job->'input_revision','province',p,'data_year',2007,'valid',false,'checks','["source_hash_match"]'::jsonb,
   'errors','[{"code":"GEOTIFF_OUTSIDE_PROVINCE","count":1}]'::jsonb,'warnings','[]'::jsonb,'error_code','GEOTIFF_OUTSIDE_PROVINCE',
   'statistics','{"width":4,"height":4,"band_count":1,"total_pixels":16,"valid_pixels":0,"nodata_pixels":0,"nonfinite_pixels":0,"outside_area_pixels":0,"mean":null,"min":null,"max":null}'::jsonb,
   'metadata','{"crs":"EPSG:32647","bands":["ST_B10"],"resolution":[30,30],"dtype":"uint16","nodata":0,"units":"landsat_c2_l2_dn","scales":[1],"offsets":[0],"profile":"lst_st_b10","output_units":"celsius"}'::jsonb,
   'coverage',null);
 r:=gis.queue_protocol_kind('complete',jsonb_build_object('job_id',job->>'id','worker_id',w,'lease_token',job->>'lease_token','report',rep),'geotiff');
 IF r->>'state'<>'failed' THEN RAISE EXCEPTION 'T_FAIL %',r; END IF;
END $t2$;
RESET ROLE;

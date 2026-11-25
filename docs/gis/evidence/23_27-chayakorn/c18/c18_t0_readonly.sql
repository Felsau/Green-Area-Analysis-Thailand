-- C18 step 5: READ ONLY look at where T0 stores district names (no writes; the transaction is READ ONLY and rolled back)
BEGIN READ ONLY;
SELECT current_database() AS db, to_regclass('public.districts') AS districts_table;
-- every column in public that holds a district name or a Thai name
SELECT table_name, column_name, data_type FROM information_schema.columns
 WHERE table_schema = 'public' AND (column_name ILIKE '%district%' OR column_name ILIKE '%name_th%')
 ORDER BY table_name, column_name;
-- districts table from migration 007
SELECT count(*) AS districts_rows, count(name_th) AS name_th_not_null FROM public.districts;
SELECT province, name_en, name_th FROM public.districts
 WHERE province = 'Nakhon Sawan' AND name_en IN ('Takhli', 'ThaTako', 'LatYao', 'PhayuhaKhiri') ORDER BY name_en;
-- rows of the district cache tables, and any district value in Thai script (the API caches by English name)
DO $$ DECLARE t text; n bigint; th bigint; BEGIN
 FOR t IN SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables x USING (table_schema, table_name)
           WHERE c.table_schema = 'public' AND c.column_name = 'district' AND x.table_type = 'BASE TABLE' ORDER BY 1 LOOP
  EXECUTE format('SELECT count(*), count(*) FILTER (WHERE district ~ ''[ก-๙]'') FROM public.%I', t) INTO n, th;
  RAISE NOTICE 'table % rows % thai_district_values %', t, n, th;
 END LOOP;
END $$;
ROLLBACK;

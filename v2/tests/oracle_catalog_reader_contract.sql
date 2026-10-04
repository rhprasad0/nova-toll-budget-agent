-- Disposable development migration 035 regression; never run on a deployed DB.
\set ON_ERROR_STOP on
DO $$
BEGIN
  IF current_database() <> 'nova_toll_development'
     OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.15.2' THEN
    RAISE EXCEPTION 'catalog grant regression requires the disposable canonical development DB';
  END IF;
END $$;
REVOKE USAGE ON SCHEMA oracle FROM pricing_reader_development;
REVOKE SELECT ON oracle.schema_version, oracle.toll_route_point,
  oracle.toll_connection, oracle.route_pricing_component FROM pricing_reader_development;
UPDATE oracle.schema_version SET version = '1.15.1' WHERE singleton;
\ir ../db/migrations/035_upgrade_oracle_1_15_1_to_1_15_2.sql
\ir ../db/migrations/035_upgrade_oracle_1_15_1_to_1_15_2.sql
SET ROLE pricing_reader_development;
SELECT version FROM oracle.schema_version WHERE singleton;
SELECT point_id, label FROM oracle.toll_route_point ORDER BY point_id LIMIT 1;
SELECT connection_id FROM oracle.toll_connection ORDER BY connection_id LIMIT 1;
SELECT connection_id FROM oracle.route_pricing_component ORDER BY connection_id LIMIT 1;
DO $$
BEGIN
  BEGIN
    UPDATE oracle.toll_route_point SET label = label WHERE false;
    RAISE EXCEPTION 'catalog reader unexpectedly has UPDATE';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    PERFORM oracle.get_toll_route_prompt_points();
    RAISE EXCEPTION 'catalog reader unexpectedly has EXECUTE';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END $$;
RESET ROLE;

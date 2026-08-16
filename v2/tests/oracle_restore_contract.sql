\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    postgis_namespace text;
BEGIN
    IF current_setting('server_version_num')::integer < 170000
       OR current_setting('server_version_num')::integer >= 180000 THEN
        RAISE EXCEPTION 'oracle contract requires PostgreSQL 17';
    END IF;
    SELECT namespace.nspname INTO postgis_namespace
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = extension.extnamespace
    WHERE extension.extname = 'postgis';
    IF postgis_namespace <> 'oracle' THEN
        RAISE EXCEPTION 'PostGIS was installed in %, not oracle', postgis_namespace;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_extension
        WHERE extname IN ('postgis_raster', 'postgis_topology', 'postgis_tiger_geocoder', 'pgrouting')
    ) THEN
        RAISE EXCEPTION 'an excluded spatial extension was installed';
    END IF;
END $$;

DO $$
DECLARE
    counts record;
BEGIN
    SELECT
        (SELECT count(*) FROM oracle.toll_route_point) AS points,
        (SELECT count(*) FROM oracle.toll_connection) AS connections,
        (SELECT count(*) FROM oracle.toll_route_point WHERE location IS NOT NULL)
            AS located,
        (SELECT count(*) FROM oracle.toll_connection
         WHERE connection_type = 'within_facility') AS within_facility,
        (SELECT count(*) FROM oracle.toll_connection
         WHERE connection_type = 'general_purpose_gap') AS gaps,
        (SELECT count(*) FROM oracle.toll_connection
         WHERE connection_type = 'toll_handoff') AS handoffs,
        (SELECT count(*) FROM oracle.toll_connection
         WHERE connection_type = 'airport_access') AS airports
    INTO counts;
    IF counts.points <> 220 OR counts.connections <> 989 OR counts.located <> 107
       OR counts.within_facility <> 670 OR counts.gaps <> 300
       OR counts.handoffs <> 12 OR counts.airports <> 7 THEN
        RAISE EXCEPTION 'unexpected oracle seed counts: %', row_to_json(counts);
    END IF;
END $$;

DO $$
BEGIN
    IF (SELECT count(*) FROM oracle.schema_version) <> 1
       OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.0.0' THEN
        RAISE EXCEPTION 'oracle schema version is invalid';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_connection
        WHERE connection_type = 'general_purpose_gap'
          AND source_metadata->'source_pair'->'ods' IS NOT NULL) <> 300 THEN
        RAISE EXCEPTION 'I-95/I-495 OD provenance was not retained';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_connection
        WHERE connection_type = 'general_purpose_gap'
          AND EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(source_metadata->'source_pair'->'ods') AS od(value)
              WHERE od.value::integer BETWEEN 1374 AND 1389
          )) <> 107 THEN
        RAISE EXCEPTION 'modeled-junction OD routes were not retained';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_route_point
        WHERE location IS NOT NULL
          AND source_metadata->>'coordinate_quality' <> 'provisional_generalized') <> 0
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE location IS NULL
             AND source_metadata->>'coordinate_quality' <> 'missing') <> 0 THEN
        RAISE EXCEPTION 'coordinate quality does not match nullable geometry';
    END IF;
END $$;

DO $$
BEGIN
    BEGIN
        INSERT INTO oracle.toll_route_point (
            point_id, network_id, source_node_id, point_type, direction,
            label, aliases, source_metadata
        ) VALUES (
            'invalid-airport', 'airport_iad', 'bad', 'airport', 'NB',
            'bad', ARRAY[]::text[], '{}'::jsonb
        );
        RAISE EXCEPTION 'invalid airport direction was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO oracle.toll_connection (
            connection_id, from_point_id, to_point_id,
            connection_type, source_metadata
        ) VALUES (
            'invalid-self', 'airport_iad', 'airport_iad',
            'airport_access', '{}'::jsonb
        );
        RAISE EXCEPTION 'self connection was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
    BEGIN
        INSERT INTO oracle.toll_connection (
            connection_id, from_point_id, to_point_id,
            connection_type, source_metadata
        ) VALUES (
            'invalid-missing', 'missing', 'airport_iad',
            'airport_access', '{}'::jsonb
        );
        RAISE EXCEPTION 'missing endpoint was accepted';
    EXCEPTION WHEN foreign_key_violation THEN NULL;
    END;
END $$;

ROLLBACK;

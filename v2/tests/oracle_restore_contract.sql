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
    IF counts.points <> 220 OR counts.connections <> 995 OR counts.located <> 220
       OR counts.within_facility <> 670 OR counts.gaps <> 300
       OR counts.handoffs <> 13 OR counts.airports <> 12 THEN
        RAISE EXCEPTION 'unexpected oracle seed counts: %', row_to_json(counts);
    END IF;
END $$;

DO $$
BEGIN
    IF (SELECT count(*) FROM oracle.schema_version) <> 1
       OR (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.0' THEN
        RAISE EXCEPTION 'oracle schema version is invalid';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_connection
        WHERE required_i95_direction IS NOT NULL) <> 311
       OR (SELECT count(*) FROM oracle.toll_connection
           WHERE connection_type = 'general_purpose_gap'
             AND required_i95_direction IS NOT NULL) <> 0
       OR (SELECT required_i95_direction FROM oracle.toll_connection
           WHERE connection_id = 'i95_north_to_dca') <> 'NB'
       OR (SELECT required_i95_direction FROM oracle.toll_connection
           WHERE connection_id = 'dca_to_i95_north') <> 'NB'
       OR (SELECT required_i95_direction FROM oracle.toll_connection
           WHERE connection_id = 'dca_to_i95_south') <> 'SB' THEN
        RAISE EXCEPTION 'connection-level I-95 requirements are invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM oracle.toll_connection
        WHERE connection_id = 'dulles_toll_road_westbound_to_i495_north'
          AND from_point_id = 'dtr:1819:exit:WB'
          AND to_point_id = 'i495:182NO'
    ) THEN
        RAISE EXCEPTION 'westbound DTR to northbound I-495 handoff is missing';
    END IF;
    IF (SELECT aliases[1] FROM oracle.toll_route_point
        WHERE point_id = 'i495:192NO') <> 'TP1NB'
       OR (SELECT aliases[1] FROM oracle.toll_route_point
           WHERE point_id = 'i495:192SD') <> 'TP1SB'
       OR (SELECT point_type FROM oracle.toll_route_point
           WHERE point_id = 'i95:234NO') <> 'entry'
       OR (SELECT point_type FROM oracle.toll_route_point
           WHERE point_id = 'i95:235SD') <> 'exit' THEN
        RAISE EXCEPTION 'TP1 or Route 17 boundary points are invalid';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_connection
        WHERE connection_type = 'general_purpose_gap'
          AND source_metadata->'source_pair'->'ods' IS NOT NULL) <> 300 THEN
        RAISE EXCEPTION 'I-95/I-495 OD provenance was not retained';
    END IF;
    IF (SELECT count(*) FROM oracle.toll_connection
        WHERE connection_type = 'general_purpose_gap'
          AND source_metadata->'general_purpose_fallback'->>'boundary_point_id'
              IN ('i495:192NO', 'i495:192SD')) <> 300 THEN
        RAISE EXCEPTION 'I-95/I-495 TP1 fallback provenance was not retained';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM oracle.toll_connection
        WHERE connection_id = 'source:i95_shared:Southbound:182SO:2239ND'
          AND source_metadata->'general_purpose_fallback'->>'i95_direction' = 'NB'
    ) OR NOT EXISTS (
        SELECT 1 FROM oracle.toll_connection
        WHERE connection_id = 'i95_north_to_dca_from_i495_south'
          AND from_point_id = 'i95:2239ND'
          AND to_point_id = 'airport_dca'
          AND required_i95_direction = 'NB'
    ) THEN
        RAISE EXCEPTION 'I-495 south/I-95 north DCA route is invalid';
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
        WHERE location IS NULL) <> 0
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE source_metadata->>'coordinate_quality' =
                 'provisional_generalized') <> 107
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE source_metadata->>'coordinate_quality' =
                 'approximate_interchange'
             AND source_metadata->'coordinate_source' IS NOT NULL) <> 111
       OR (SELECT count(*) FROM oracle.toll_route_point
           WHERE source_metadata->>'coordinate_quality' =
                 'official_reference_point'
             AND source_metadata->'coordinate_source' IS NOT NULL) <> 2 THEN
        RAISE EXCEPTION 'coordinate quality or provenance is invalid';
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

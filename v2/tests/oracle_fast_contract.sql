\set ON_ERROR_STOP on

-- Real functions and roles on a small graph. Graph and pricing replacement
-- roll back; the full contracts retain the independent canonical census.
BEGIN;
TRUNCATE oracle.toll_connection, oracle.toll_route_point;
TRUNCATE pricing.trip_pricing_i95;

INSERT INTO oracle.toll_route_point (
    point_id, network_id, source_node_id, point_type, direction, label,
    source_metadata, place_name, region, country_code
)
SELECT id, network, id, kind, direction, id, '{}', area, 'VA', 'US'
FROM (VALUES
    ('fast:a', 'i66', 'entry', 'EB', 'First origin'),
    ('fast:b', 'i66', 'entry', 'EB', 'Second origin'),
    ('fast:x', 'i66', 'exit', 'EB', 'First destination'),
    ('fast:y', 'i66', 'exit', 'EB', 'Second destination'),
    ('fast:z', 'i66', 'exit', 'EB', 'Two-leg destination'),
    ('fast:n', 'i95', 'entry', 'NB', 'North origin'),
    ('fast:s', 'i95', 'exit', 'NB', 'North destination'),
    ('fast:isolated', 'dtr', 'exit', 'EB', 'Unreachable'),
    ('airport_iad', 'airport_iad', 'airport', NULL, 'Airport')
) AS points(id, network, kind, direction, area);

-- Two origins share a normalized price signature. fast:a must win the tie,
-- even though the other connection is inserted first. Another key stays unique.
INSERT INTO oracle.toll_connection (
    connection_id, from_point_id, to_point_id, connection_type,
    required_i95_direction, source_route_key, source_metadata
) VALUES
    ('fast:bx', 'fast:b', 'fast:x', 'within_facility', NULL, 'b-x',
     '{"source_pair":{"start_zone":1,"end_zone":2}}'),
    ('fast:ax', 'fast:a', 'fast:x', 'within_facility', NULL, 'a-x',
     '{"source_pair":{"start_zone":1,"end_zone":2}}'),
    ('fast:ay', 'fast:a', 'fast:y', 'within_facility', NULL, 'a-y',
     '{"source_pair":{"start_zone":1,"end_zone":3}}'),
    ('fast:xz', 'fast:x', 'fast:z', 'within_facility', NULL, 'x-z',
     '{"source_pair":{"start_zone":2,"end_zone":4}}'),
    ('fast:ns', 'fast:n', 'fast:s', 'within_facility', 'NB', 'n-s',
     '{"source_pair":{"ods":[1132]}}'),
    ('fast:airport', 'fast:x', 'airport_iad', 'airport_access', NULL, NULL, '{}');

INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id, corridor_name,
    od_pair_id, od_pair_name, start_zone_id, start_zone_name, end_zone_id,
    end_zone_name, zone_toll_rate_usd, link_status, s3_key
)
SELECT statement_timestamp() - interval '1 minute',
       statement_timestamp() - interval '1 minute',
       statement_timestamp() - interval '1 minute',
       95, corridor, od, corridor, 1, 'A', 2, 'B', 1.25, state,
       'test/fast-contract.csv'
FROM (VALUES ('I-95-NB', 1132, 'NORTHBOUND_OPEN'),
             ('I-95-SB', 1151, 'CLOSED')) AS evidence(corridor, od, state);

-- Explicit expected records independent of production route enumeration.
CREATE TEMP TABLE fast_expected (
    facility text, origin_area text, destination_area text, direction text,
    pricing_legs jsonb, signature jsonb
);
INSERT INTO fast_expected VALUES
    ('i66', 'First origin', 'First destination', 'eastbound',
     '[{"route_step_id":"step-1","facility":"i66","pricing_key":{"source_route_key":"a-x","start_zone_id":1,"end_zone_id":2}}]',
     '[{"facility":"i66","direction":"eastbound","start_zone_id":1,"end_zone_id":2,"charge_index":null}]'),
    ('i66', 'First origin', 'Second destination', 'eastbound',
     '[{"route_step_id":"step-1","facility":"i66","pricing_key":{"source_route_key":"a-y","start_zone_id":1,"end_zone_id":3}}]',
     '[{"facility":"i66","direction":"eastbound","start_zone_id":1,"end_zone_id":3,"charge_index":null}]'),
    ('i66', 'First origin', 'Two-leg destination', 'eastbound',
     '[{"route_step_id":"step-1","facility":"i66","pricing_key":{"source_route_key":"a-x","start_zone_id":1,"end_zone_id":2}},{"route_step_id":"step-2","facility":"i66","pricing_key":{"source_route_key":"x-z","start_zone_id":2,"end_zone_id":4}}]',
     '[{"facility":"i66","direction":"eastbound","start_zone_id":1,"end_zone_id":2,"charge_index":null},{"facility":"i66","direction":"eastbound","start_zone_id":2,"end_zone_id":4,"charge_index":null}]'),
    ('i95_i495', 'North origin', 'North destination', 'northbound',
     '[{"route_step_id":"step-1","facility":"i95_i495","pricing_key":{"source_route_key":"n-s","od_pair_id":1132}}]',
     '[{"facility":"i95_i495","direction":"northbound","od_pair_id":1132,"charge_index":null}]');

SET ROLE report_publisher;
CREATE TEMP TABLE fast_report AS SELECT * FROM oracle.get_agent_report_routes();
CREATE TEMP TABLE fast_inputs AS SELECT * FROM oracle.get_i95_i495_report_inputs();
RESET ROLE;

DO $$
BEGIN
    IF EXISTS (
        (SELECT facility, origin_area, destination_area, direction, pricing_legs,
                facility || '-' || md5(signature::text) AS path_id,
                row_number() OVER (ORDER BY facility, signature)::integer AS path_order
         FROM fast_expected
         EXCEPT
         SELECT facility, origin_area, destination_area, direction, pricing_legs,
                path_id, path_order FROM fast_report)
        UNION ALL
        (SELECT facility, origin_area, destination_area, direction, pricing_legs,
                path_id, path_order FROM fast_report
         EXCEPT
         SELECT facility, origin_area, destination_area, direction, pricing_legs,
                facility || '-' || md5(signature::text),
                row_number() OVER (ORDER BY facility, signature)::integer
         FROM fast_expected)
    ) OR (SELECT count(*) FROM fast_report) <> 4 THEN
        RAISE EXCEPTION 'small report shape, pricing keys, ordering, or tie-break changed';
    END IF;
    IF (SELECT count(*) FROM fast_inputs WHERE comparison_kind = 'current') <> 1
       OR NOT EXISTS (
           SELECT 1 FROM fast_inputs
           WHERE comparison_kind = 'current' AND status = 'valid'
             AND origin->>'point_id' = 'fast:n'
             AND destination->>'point_id' = 'fast:s'
             -- Availability also depends on the real time-of-week schedule;
             -- schedule boundary cases remain in oracle_i95_pricing_contract.
             AND price_usd = 1.25 AND source_kind = 'observed'
             AND od_pair_id = 1132 AND route_step_id = 'step-1'
       ) THEN
        RAISE EXCEPTION 'small report lost the real current pricing result';
    END IF;
END $$;

-- Reverse physical input order, then create maliciously named temporary
-- relations. Both checks call the real SECURITY DEFINER as its runtime role.
CREATE TEMP TABLE fast_connections AS SELECT * FROM oracle.toll_connection;
DELETE FROM oracle.toll_connection;
INSERT INTO oracle.toll_connection SELECT * FROM fast_connections ORDER BY connection_id DESC;
SET ROLE report_publisher;
DO $$
BEGIN
    IF (SELECT jsonb_agg(to_jsonb(r) ORDER BY path_order)
        FROM oracle.get_agent_report_routes() AS r)
       IS DISTINCT FROM
       (SELECT jsonb_agg(to_jsonb(r) ORDER BY path_order) FROM fast_report AS r) THEN
        RAISE EXCEPTION 'small report depends on physical row order';
    END IF;
END $$;
CREATE TEMP TABLE toll_route_point AS SELECT NULL::text AS point_id;
CREATE TEMP TABLE route_pricing_component AS SELECT NULL::text AS facility;
DO $$
BEGIN
    IF (SELECT jsonb_agg(to_jsonb(r) ORDER BY path_order)
        FROM oracle.get_agent_report_routes() AS r)
       IS DISTINCT FROM
       (SELECT jsonb_agg(to_jsonb(r) ORDER BY path_order) FROM fast_report AS r) THEN
        RAISE EXCEPTION 'temporary shadow object changed small report';
    END IF;
    BEGIN
        PERFORM count(*) FROM oracle.toll_route_point;
        RAISE EXCEPTION 'publisher read underlying Oracle tables';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM count(*) FROM pricing.i95_i495_pricing_comparisons;
        RAISE EXCEPTION 'publisher read underlying pricing relations';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM * FROM oracle.validate_toll_route('fast:a', 'fast:x');
        RAISE EXCEPTION 'publisher executed unrelated function';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
RESET ROLE;

DO $$
BEGIN
    IF NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER')
       OR NOT (SELECT rolcanlogin FROM pg_catalog.pg_roles
               WHERE rolname = 'report_publisher')
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_class AS relation
           JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
           WHERE namespace.nspname IN ('oracle', 'pricing')
             AND has_table_privilege('report_publisher', relation.oid,
                                     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       ) OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_proc AS procedure
           JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
           WHERE namespace.nspname = 'oracle'
             AND procedure.oid NOT IN (
                 'oracle.get_agent_report_routes()'::regprocedure,
                 'oracle.get_i95_i495_report_inputs()'::regprocedure
             )
             AND has_function_privilege('report_publisher', procedure.oid, 'EXECUTE')
       ) THEN
        RAISE EXCEPTION 'publisher role exceeds its bounded report access';
    END IF;
END $$;
CREATE ROLE fast_contract_unrelated NOLOGIN;
GRANT USAGE ON SCHEMA oracle TO fast_contract_unrelated;
SET ROLE fast_contract_unrelated;
DO $$
BEGIN
    BEGIN
        PERFORM * FROM oracle.get_agent_report_routes();
        RAISE EXCEPTION 'unrelated role executed report routes';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
RESET ROLE;

-- Compare complete wrapper records, not only status. Canonical route contracts
-- still check handoffs, alternatives, gaps, cycles and traversal boundaries.
CREATE FUNCTION pg_temp.assert_fast_parity(origin_id text, destination_id text, expected_status text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE public_result jsonb; resolved_result jsonb;
BEGIN
    SELECT to_jsonb(r) INTO STRICT public_result
    FROM oracle.validate_toll_route(origin_id, destination_id) AS r;
    SELECT to_jsonb(r) INTO STRICT resolved_result
    FROM oracle.resolve_toll_route(origin_id, destination_id) AS r;
    IF public_result IS DISTINCT FROM resolved_result
       OR public_result->>'status' IS DISTINCT FROM expected_status THEN
        RAISE EXCEPTION 'wrapper parity failed for % -> %: % / %',
            origin_id, destination_id, public_result, resolved_result;
    END IF;
END $$;
SELECT pg_temp.assert_fast_parity(origin_id, destination_id, expected_status)
FROM (VALUES
    ('fast:a', 'fast:x', 'valid'),
    ('fast:a', 'airport_iad', 'valid'),
    ('fast:n', 'fast:s', 'valid'),
    (NULL, 'fast:x', 'invalid_origin'),
    ('missing', 'fast:x', 'invalid_origin'),
    ('fast:x', 'fast:y', 'invalid_origin'),
    ('fast:a', NULL, 'invalid_destination'),
    ('fast:a', 'missing', 'invalid_destination'),
    ('fast:a', 'fast:b', 'invalid_destination'),
    ('fast:a', 'fast:a', 'invalid_destination'),
    ('fast:a', 'fast:isolated', 'no_supported_route')
) AS cases(origin_id, destination_id, expected_status);
UPDATE pricing.trip_pricing_i95 SET link_status = 'CLOSED';
SELECT pg_temp.assert_fast_parity('fast:n', 'fast:s', 'currently_unavailable');
TRUNCATE pricing.trip_pricing_i95;
SELECT pg_temp.assert_fast_parity('fast:n', 'fast:s', 'unknown_availability');

-- A 13-edge path covers the last status without a canonical all-pairs sweep.
INSERT INTO oracle.toll_route_point (
    point_id, network_id, source_node_id, point_type, direction, label, source_metadata
)
SELECT 'fast:depth:' || n, 'dtr', 'depth:' || n,
       CASE WHEN n = 13 THEN 'exit' ELSE 'entry' END, 'EB', 'Depth fixture', '{}'
FROM generate_series(0, 13) AS n;
INSERT INTO oracle.toll_connection (
    connection_id, from_point_id, to_point_id, connection_type, source_metadata
)
SELECT 'fast:depth:' || n, 'fast:depth:' || n, 'fast:depth:' || (n + 1),
       'within_facility', '{}'
FROM generate_series(0, 12) AS n;
SELECT pg_temp.assert_fast_parity('fast:depth:0', 'fast:depth:13', 'traversal_limit_exceeded');
ROLLBACK;

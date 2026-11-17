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

\set ON_ERROR_STOP on

TRUNCATE pricing.trip_pricing_i95;
INSERT INTO pricing.trip_pricing_i95 (
    interval_end_at, current_at, calculated_at, corridor_id,
    corridor_name, od_pair_id, od_pair_name, start_zone_id,
    start_zone_name, end_zone_id, end_zone_name, zone_toll_rate_usd,
    link_status, s3_key
)
SELECT
    statement_timestamp() - interval '1 minute',
    statement_timestamp() - interval '1 minute',
    statement_timestamp() - interval '1 minute',
    95,
    fixture.corridor_name,
    fixture.od_pair_id,
    fixture.corridor_name || ' direction sentinel',
    fixture.od_pair_id,
    'start',
    fixture.od_pair_id + 1,
    'end',
    1.00,
    fixture.link_status,
    'test/report-contract.csv'
FROM (VALUES
    ('I-95-NB', 1132, 'NORTHBOUND_OPEN'),
    ('I-95-SB', 1151, 'CLOSED')
) AS fixture(corridor_name, od_pair_id, link_status);

SET ROLE report_publisher;
CREATE TEMP TABLE report_inputs AS
SELECT * FROM oracle.get_i95_i495_report_inputs();
RESET ROLE;

DO $$
DECLARE
    report record;
    distinct_routes integer;
    structural_components integer;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.13.1' THEN
        RAISE EXCEPTION 'Oracle report schema is not 1.13.1';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM oracle.toll_route_point
        WHERE network_id IN ('i95', 'i495')
          AND (
              place_name IS NULL OR btrim(place_name) = ''
              OR region IS NULL OR btrim(region) = ''
              OR country_code !~ '^[A-Z]{2}$'
          )
    ) THEN
        RAISE EXCEPTION 'I-95/I-495 report context is incomplete';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM oracle.toll_route_point
        WHERE num_nonnulls(place_name, region, country_code) NOT IN (0, 3)
    ) THEN
        RAISE EXCEPTION 'partial geographic context was accepted';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM oracle.toll_route_point,
             LATERAL unnest(aliases) AS alias(value)
        GROUP BY point_id, alias.value
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'duplicate route-point aliases are present';
    END IF;

    SELECT * INTO STRICT report
    FROM report_inputs
    WHERE origin->>'point_id' = 'i95:218NO'
      AND destination->>'point_id' = 'i495:185ND'
    LIMIT 1;
    IF report.origin->>'label' <> 'I-95 Near Dumfries Road/Route 234'
       OR report.origin->>'place_name' <> 'Dumfries'
       OR report.origin->>'region' <> 'Virginia'
       OR report.origin->>'country_code' <> 'US'
       OR NOT report.origin->'aliases' @> '["Dumfries Road", "Route 234"]'
       OR jsonb_typeof(report.origin->'nearby_landmarks') <> 'array'
       OR report.origin->>'direction' <> 'northbound'
       OR report.origin->>'role' <> 'entry'
       OR report.origin->'location'->>'type' <> 'Point'
       OR jsonb_array_length(report.origin->'location'->'coordinates') <> 2
       OR report.destination->>'label' <> 'Westpark Drive'
       OR report.destination->>'place_name' <> 'Tysons'
       OR report.destination->>'region' <> 'Virginia'
       OR report.destination->>'country_code' <> 'US'
       OR NOT report.destination->'aliases' @> '["Tysons Corner"]'
       OR report.destination->>'direction' <> 'northbound'
       OR report.destination->>'role' <> 'exit'
       OR report.destination->>'display_name'
          <> 'Tysons, Virginia — Westpark Drive (northbound exit)'
       OR report.status <> 'valid'
       OR report.route_step_id !~ '^step-[1-9][0-9]*$'
       OR report.comparison_kind <> 'current'
       OR report.comparison_offset <> 0
       OR report.available
       OR report.availability_reason <> 'missing_observation' THEN
        RAISE EXCEPTION 'Dumfries-to-Tysons report context is wrong: %',
            row_to_json(report);
    END IF;

    SELECT * INTO STRICT report
    FROM report_inputs
    WHERE origin->>'point_id' = 'i95:208SO'
    LIMIT 1;
    IF report.origin->>'place_name' <> 'Newington'
       OR NOT report.origin->'aliases' @> '["Fairfax County Parkway", "Route 286"]'
       OR report.origin->'nearby_landmarks' <> '["Fort Belvoir"]'::jsonb THEN
        RAISE EXCEPTION 'Newington report context is wrong: %',
            row_to_json(report);
    END IF;

    IF NOT (SELECT aliases @> ARRAY['DCA', 'Reagan Airport']
            FROM oracle.toll_route_point WHERE point_id = 'airport_dca')
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_route_point
           WHERE network_id IN ('i95', 'i495')
             AND 'Reagan Airport' = ANY(aliases)
       ) THEN
        RAISE EXCEPTION 'Reagan Airport aliases do not resolve uniquely';
    END IF;

    SELECT count(DISTINCT (origin->>'point_id', destination->>'point_id')),
           sum(jsonb_array_length(structural_facility_legs))
    INTO distinct_routes, structural_components
    FROM (
        SELECT DISTINCT ON (origin->>'point_id', destination->>'point_id')
            origin, destination, structural_facility_legs
        FROM report_inputs
        ORDER BY origin->>'point_id', destination->>'point_id'
    ) AS routes;
    IF distinct_routes <> 685 OR structural_components <> 980 THEN
        RAISE EXCEPTION 'report scope changed: % routes, % components',
            distinct_routes, structural_components;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM report_inputs
        WHERE origin->>'point_id' IS NULL
           OR destination->>'point_id' IS NULL
           OR origin->>'place_name' IS NULL
           OR destination->>'place_name' IS NULL
           OR origin->>'country_code' !~ '^[A-Z]{2}$'
           OR destination->>'country_code' !~ '^[A-Z]{2}$'
           OR jsonb_typeof(structural_facility_legs) <> 'array'
           OR jsonb_array_length(structural_facility_legs) = 0
           OR EXISTS (
               SELECT 1
               FROM jsonb_array_elements(structural_facility_legs) AS leg(value)
               WHERE leg.value->>'facility' <> 'i95_i495'
           )
           OR (status = 'valid' AND route_step_id IS NULL)
           OR (route_step_id IS NOT NULL AND comparison_kind IS NULL)
    ) THEN
        RAISE EXCEPTION 'bounded report operation returned malformed rows';
    END IF;

    IF (SELECT count(DISTINCT snapshot_evaluated_at)
        FROM report_inputs) <> 1 THEN
        RAISE EXCEPTION 'report rows do not share one evaluation timestamp';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regrole('report_publisher') IS NULL
       OR NOT (SELECT rolcanlogin FROM pg_catalog.pg_roles
               WHERE rolname = 'report_publisher')
       OR NOT pg_has_role('report_publisher', 'rds_iam', 'MEMBER')
       OR NOT has_schema_privilege('report_publisher', 'oracle', 'USAGE')
       OR NOT has_function_privilege(
           'report_publisher', 'oracle.get_i95_i495_report_inputs()', 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'report publisher role is not installed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname IN ('oracle', 'pricing')
          AND has_table_privilege(
              'report_publisher', relation.oid,
              'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'oracle'
          AND procedure.oid <> 'oracle.get_i95_i495_report_inputs()'::regprocedure
          AND has_function_privilege(
              'report_publisher', procedure.oid, 'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION 'report publisher has privileges beyond the bounded read';
    END IF;
END $$;

SET ROLE report_publisher;
DO $$
BEGIN
    BEGIN
        PERFORM count(*) FROM oracle.toll_route_point;
        RAISE EXCEPTION 'report publisher read Oracle tables directly';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    BEGIN
        PERFORM count(*) FROM pricing.i95_i495_pricing_comparisons;
        RAISE EXCEPTION 'report publisher read pricing tables directly';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
RESET ROLE;

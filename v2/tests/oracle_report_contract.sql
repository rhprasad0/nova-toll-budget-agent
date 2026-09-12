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
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.14.1' THEN
        RAISE EXCEPTION 'Oracle report schema is not 1.14.1';
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
    IF (SELECT count(*) FROM oracle.toll_route_point WHERE network_id = 'i66') <> 30
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_route_point AS point
           JOIN (VALUES
               ('1', 'Idylwood'), ('2', 'Idylwood'), ('3', 'Idylwood'),
               ('4', 'West Falls Church'), ('5', 'Idylwood'),
               ('6', 'West Falls Church'), ('7', 'Tysons'),
               ('8', 'East Falls Church'), ('9', 'Ballston'),
               ('10', 'East Falls Church'), ('11', 'East Falls Church'),
               ('12', 'East Falls Church'), ('13', 'North Arlington'),
               ('14', 'Rosslyn'), ('15', 'Pentagon area'),
               ('16', 'Washington, D.C.'), ('17', 'North Arlington')
           ) AS expected(source_node_id, place_name)
             ON expected.source_node_id = point.source_node_id
           WHERE point.network_id = 'i66'
             AND (
                 point.place_name IS DISTINCT FROM expected.place_name
                 OR point.region IS DISTINCT FROM CASE point.source_node_id
                     WHEN '16' THEN 'District of Columbia'
                     ELSE 'Virginia'
                 END
                 OR point.country_code IS DISTINCT FROM 'US'
             )
       ) THEN
        RAISE EXCEPTION 'I-66 broad-area metadata is wrong';
    END IF;
END $$;

SET ROLE report_publisher;
CREATE TEMP TABLE report_routes_run1 AS
SELECT * FROM oracle.get_agent_report_routes();
CREATE TEMP TABLE report_routes_run2 AS
SELECT * FROM oracle.get_agent_report_routes();
RESET ROLE;

CREATE TEMP TABLE raw_report_candidates AS
WITH report_points AS (
    SELECT
        logical.facility,
        point.point_id,
        point.point_type,
        point.direction,
        point.place_name
    FROM (VALUES
        ('i66'::text, ARRAY['i66']::text[]),
        ('i95_i495'::text, ARRAY['i95', 'i495']::text[])
    ) AS logical(facility, networks)
    JOIN oracle.toll_route_point AS point
      ON point.network_id = ANY(logical.networks)
)
SELECT
    origin.facility,
    origin.point_id AS origin_point_id,
    destination.point_id AS destination_point_id,
    origin.place_name AS origin_area,
    destination.place_name AS destination_area,
    CASE origin.direction
        WHEN 'NB' THEN 'northbound'
        WHEN 'SB' THEN 'southbound'
        WHEN 'EB' THEN 'eastbound'
        WHEN 'WB' THEN 'westbound'
    END AS direction,
    resolved.point_ids,
    resolved.connection_ids,
    oracle.route_pricing_legs(
        resolved.point_ids, resolved.connection_ids
    ) AS pricing_legs
FROM report_points AS origin
JOIN report_points AS destination
  ON destination.facility = origin.facility
 AND destination.point_type = 'exit'
CROSS JOIN LATERAL oracle.resolve_toll_route_internal(
    origin.point_id, destination.point_id, false
) AS resolved
WHERE origin.point_type = 'entry'
  AND resolved.status = 'valid'
  AND jsonb_array_length(oracle.route_pricing_legs(
      resolved.point_ids, resolved.connection_ids
  )) > 0
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements(oracle.route_pricing_legs(
          resolved.point_ids, resolved.connection_ids
      )) AS leg(value)
      WHERE leg.value->>'facility' <> origin.facility
  );

CREATE TEMP TABLE raw_report_signatures AS
SELECT candidate.*, normalized.signature
FROM raw_report_candidates AS candidate
CROSS JOIN LATERAL (
    SELECT jsonb_agg(
        CASE candidate.facility
            WHEN 'i66' THEN jsonb_build_object(
                'facility', candidate.facility,
                'direction', candidate.direction,
                'start_zone_id', leg.value->'pricing_key'->'start_zone_id',
                'end_zone_id', leg.value->'pricing_key'->'end_zone_id',
                'charge_index', leg.value->'pricing_key'->'charge_index'
            )
            WHEN 'i95_i495' THEN jsonb_build_object(
                'facility', candidate.facility,
                'direction', candidate.direction,
                'od_pair_id', leg.value->'pricing_key'->'od_pair_id',
                'charge_index', leg.value->'pricing_key'->'charge_index'
            )
        END ORDER BY leg.ord
    ) AS signature
    FROM jsonb_array_elements(candidate.pricing_legs)
         WITH ORDINALITY AS leg(value, ord)
) AS normalized;

CREATE TEMP TABLE returned_report_signatures AS
SELECT report.*, normalized.signature
FROM report_routes_run1 AS report
CROSS JOIN LATERAL (
    SELECT jsonb_agg(
        CASE report.facility
            WHEN 'i66' THEN jsonb_build_object(
                'facility', report.facility,
                'direction', report.direction,
                'start_zone_id', leg.value->'pricing_key'->'start_zone_id',
                'end_zone_id', leg.value->'pricing_key'->'end_zone_id',
                'charge_index', leg.value->'pricing_key'->'charge_index'
            )
            WHEN 'i95_i495' THEN jsonb_build_object(
                'facility', report.facility,
                'direction', report.direction,
                'od_pair_id', leg.value->'pricing_key'->'od_pair_id',
                'charge_index', leg.value->'pricing_key'->'charge_index'
            )
        END ORDER BY leg.ord
    ) AS signature
    FROM jsonb_array_elements(report.pricing_legs)
         WITH ORDINALITY AS leg(value, ord)
) AS normalized;

CREATE TEMP TABLE expected_report_routes AS
WITH ranked AS (
    SELECT
        raw.*,
        row_number() OVER (
            PARTITION BY raw.facility, raw.signature
            ORDER BY
                raw.origin_point_id,
                raw.destination_point_id,
                raw.point_ids::text,
                raw.connection_ids::text
        ) AS representative_order
    FROM raw_report_signatures AS raw
), representatives AS (
    SELECT * FROM ranked WHERE representative_order = 1
), stripped AS (
    SELECT
        representative.*,
        (SELECT jsonb_agg(jsonb_build_object(
            'route_step_id', leg.value->'route_step_id',
            'facility', leg.value->'facility',
            'pricing_key', leg.value->'pricing_key'
        ) ORDER BY leg.ord)
         FROM jsonb_array_elements(representative.pricing_legs)
              WITH ORDINALITY AS leg(value, ord)) AS public_pricing_legs
    FROM representatives AS representative
)
SELECT
    stripped.facility,
    stripped.facility || '-' || md5(stripped.signature::text) AS path_id,
    row_number() OVER (
        ORDER BY stripped.facility, stripped.signature
    )::integer AS path_order,
    stripped.public_pricing_legs AS pricing_legs,
    stripped.origin_area,
    stripped.destination_area,
    stripped.direction,
    stripped.signature,
    stripped.origin_point_id,
    stripped.destination_point_id
FROM stripped;

CREATE TEMP TABLE reversed_expected_report_routes AS
WITH reversed AS MATERIALIZED (
    SELECT *
    FROM raw_report_signatures
    ORDER BY origin_point_id DESC, destination_point_id DESC
), ranked AS (
    SELECT
        reversed.*,
        row_number() OVER (
            PARTITION BY reversed.facility, reversed.signature
            ORDER BY
                reversed.origin_point_id,
                reversed.destination_point_id,
                reversed.point_ids::text,
                reversed.connection_ids::text
        ) AS representative_order
    FROM reversed
), representatives AS (
    SELECT * FROM ranked WHERE representative_order = 1
), stripped AS (
    SELECT
        representative.*,
        (SELECT jsonb_agg(jsonb_build_object(
            'route_step_id', leg.value->'route_step_id',
            'facility', leg.value->'facility',
            'pricing_key', leg.value->'pricing_key'
        ) ORDER BY leg.ord)
         FROM jsonb_array_elements(representative.pricing_legs)
              WITH ORDINALITY AS leg(value, ord)) AS public_pricing_legs
    FROM representatives AS representative
)
SELECT
    stripped.facility,
    stripped.facility || '-' || md5(stripped.signature::text) AS path_id,
    row_number() OVER (
        ORDER BY stripped.facility, stripped.signature
    )::integer AS path_order,
    stripped.public_pricing_legs AS pricing_legs,
    stripped.origin_area,
    stripped.destination_area,
    stripped.direction,
    stripped.signature,
    stripped.origin_point_id,
    stripped.destination_point_id
FROM stripped;

WITH route_groups AS (
    SELECT
        facility,
        origin_area,
        destination_area,
        direction,
        count(*) AS paths
    FROM report_routes_run1
    GROUP BY 1, 2, 3, 4
), metrics AS (
    SELECT
        facility,
        count(*) AS broad_group_count,
        count(*) FILTER (WHERE paths > 1) AS multi_path_group_count,
        max(paths) AS max_paths_per_group,
        sum(paths) AS path_count
    FROM route_groups
    GROUP BY facility
), global_metrics AS (
    SELECT
        'all'::text AS facility,
        count(*) AS broad_group_count,
        count(*) FILTER (WHERE paths > 1) AS multi_path_group_count,
        max(paths) AS max_paths_per_group,
        sum(paths) AS path_count
    FROM route_groups
)
SELECT
    facility,
    path_count,
    broad_group_count,
    multi_path_group_count,
    max_paths_per_group
FROM (
    SELECT * FROM metrics
    UNION ALL
    SELECT * FROM global_metrics
) AS accepted_counts
ORDER BY CASE facility WHEN 'i66' THEN 1 WHEN 'i95_i495' THEN 2 ELSE 3 END;

DO $$
DECLARE
    i66_paths integer;
    i95_paths integer;
    i66_groups integer;
    i95_groups integer;
    i66_multi integer;
    i95_multi integer;
    i66_max integer;
    i95_max integer;
BEGIN
    SELECT
        count(*) FILTER (WHERE facility = 'i66'),
        count(*) FILTER (WHERE facility = 'i95_i495')
    INTO i66_paths, i95_paths
    FROM report_routes_run1;

    SELECT
        count(*) FILTER (WHERE facility = 'i66'),
        count(*) FILTER (WHERE facility = 'i95_i495'),
        count(*) FILTER (WHERE facility = 'i66' AND paths > 1),
        count(*) FILTER (WHERE facility = 'i95_i495' AND paths > 1),
        max(paths) FILTER (WHERE facility = 'i66'),
        max(paths) FILTER (WHERE facility = 'i95_i495')
    INTO i66_groups, i95_groups, i66_multi, i95_multi, i66_max, i95_max
    FROM (
        SELECT facility, origin_area, destination_area, direction, count(*) AS paths
        FROM report_routes_run1
        GROUP BY 1, 2, 3, 4
    ) AS groups;

    IF (i66_paths, i95_paths) <> (20, 562)
       OR (i66_groups, i95_groups) <> (16, 246)
       OR (i66_multi, i95_multi) <> (4, 142)
       OR (i66_max, i95_max) <> (2, 12)
       OR i66_paths + i95_paths <> 582
       OR i66_groups + i95_groups <> 262
       OR i66_multi + i95_multi <> 146
       OR greatest(i66_max, i95_max) <> 12 THEN
        RAISE EXCEPTION 'normalized report-route counts changed';
    END IF;

    IF EXISTS (
        (SELECT facility, signature FROM raw_report_signatures GROUP BY 1, 2
         EXCEPT
         SELECT facility, signature FROM returned_report_signatures)
        UNION ALL
        (SELECT facility, signature FROM returned_report_signatures
         EXCEPT
         SELECT facility, signature FROM raw_report_signatures GROUP BY 1, 2)
    ) OR EXISTS (
        SELECT 1
        FROM raw_report_signatures AS raw
        LEFT JOIN returned_report_signatures AS returned
          ON returned.facility = raw.facility
         AND returned.signature = raw.signature
        GROUP BY raw.facility, raw.origin_point_id, raw.destination_point_id
        HAVING count(returned.*) <> 1
    ) THEN
        RAISE EXCEPTION 'normalized signature coverage differs from raw candidates';
    END IF;

    IF EXISTS (
        (SELECT facility, path_id, path_order, pricing_legs,
                origin_area, destination_area, direction, signature
         FROM expected_report_routes
         EXCEPT
         SELECT facility, path_id, path_order, pricing_legs,
                origin_area, destination_area, direction, signature
         FROM returned_report_signatures)
        UNION ALL
        (SELECT facility, path_id, path_order, pricing_legs,
                origin_area, destination_area, direction, signature
         FROM returned_report_signatures
         EXCEPT
         SELECT facility, path_id, path_order, pricing_legs,
                origin_area, destination_area, direction, signature
         FROM expected_report_routes)
    ) OR EXISTS (
        (SELECT * FROM expected_report_routes
         EXCEPT SELECT * FROM reversed_expected_report_routes)
        UNION ALL
        (SELECT * FROM reversed_expected_report_routes
         EXCEPT SELECT * FROM expected_report_routes)
    ) THEN
        RAISE EXCEPTION 'representative selection or reversed ordering changed';
    END IF;

    IF (SELECT jsonb_agg(to_jsonb(run1) ORDER BY path_order)
        FROM report_routes_run1 AS run1)
       IS DISTINCT FROM
       (SELECT jsonb_agg(to_jsonb(run2) ORDER BY path_order)
        FROM report_routes_run2 AS run2)
       OR (SELECT count(*) FROM report_routes_run1)
          <> (SELECT count(DISTINCT path_id) FROM report_routes_run1)
       OR (SELECT array_agg(path_order ORDER BY path_order)
           FROM report_routes_run1)
          <> ARRAY(SELECT generate_series(1, 582)) THEN
        RAISE EXCEPTION 'report route identity or order is nondeterministic';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM report_routes_run1 AS report
        CROSS JOIN LATERAL jsonb_array_elements(report.pricing_legs)
             WITH ORDINALITY AS leg(value, ord)
        WHERE jsonb_typeof(report.pricing_legs) <> 'array'
           OR jsonb_array_length(report.pricing_legs) = 0
           OR leg.value->>'facility' <> report.facility
           OR leg.value->>'route_step_id' <> 'step-' || leg.ord
           OR jsonb_strip_nulls(leg.value->'pricing_key')
              <> leg.value->'pricing_key'
           OR (SELECT array_agg(key ORDER BY key)
               FROM jsonb_object_keys(leg.value) AS key)
              <> ARRAY['facility', 'pricing_key', 'route_step_id']::text[]
    ) THEN
        RAISE EXCEPTION 'report pricing leg shape is wrong';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM report_routes_run1 AS report
        WHERE report.facility NOT IN ('i66', 'i95_i495')
           OR btrim(report.path_id) = ''
           OR btrim(report.origin_area) = ''
           OR btrim(report.destination_area) = ''
           OR report.direction NOT IN (
               'eastbound', 'westbound', 'northbound', 'southbound'
           )
    ) OR EXISTS (
        SELECT 1
        FROM expected_report_routes AS report
        JOIN oracle.toll_route_point AS origin
          ON origin.point_id = report.origin_point_id
        JOIN oracle.toll_route_point AS destination
          ON destination.point_id = report.destination_point_id
        WHERE report.origin_area IS DISTINCT FROM origin.place_name
           OR report.destination_area IS DISTINCT FROM destination.place_name
           OR report.origin_area IN (origin.point_id, origin.label)
           OR report.destination_area IN (
               destination.point_id, destination.label
           )
    ) THEN
        RAISE EXCEPTION 'report public fields are unsafe';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM report_routes_run1
        WHERE facility = 'i66'
          AND 'Idylwood' IN (origin_area, destination_area)
    ) OR NOT EXISTS (
        SELECT 1 FROM report_routes_run1
        WHERE facility = 'i95_i495'
          AND 'Idylwood' IN (origin_area, destination_area)
    ) THEN
        RAISE EXCEPTION 'separate I-66/I-495 boundary paths are missing';
    END IF;
END $$;

CREATE TEMP TABLE raw_candidate_comparisons AS
SELECT
    raw.facility,
    raw.origin_point_id,
    raw.destination_point_id,
    raw.signature,
    comparisons.value AS comparison_semantics
FROM raw_report_signatures AS raw
CROSS JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'route_step', leg.ord,
        'result', CASE raw.facility
            WHEN 'i66' THEN (
                SELECT jsonb_agg(to_jsonb(comparison) - 'evaluated_at'
                                 ORDER BY comparison_kind, comparison_offset)
                FROM oracle.get_i66_pricing_comparisons(
                    (leg.value->'pricing_key'->>'start_zone_id')::integer,
                    (leg.value->'pricing_key'->>'end_zone_id')::integer,
                    CASE raw.direction WHEN 'eastbound' THEN 'EB' ELSE 'WB' END
                ) AS comparison
            )
            WHEN 'i95_i495' THEN (
                SELECT jsonb_agg(to_jsonb(comparison) - 'evaluated_at'
                                 ORDER BY comparison_kind, comparison_offset)
                FROM oracle.get_i95_i495_pricing_comparisons(
                    (leg.value->'pricing_key'->>'od_pair_id')::integer
                ) AS comparison
            )
        END
    ) ORDER BY leg.ord) AS value
    FROM jsonb_array_elements(raw.pricing_legs)
         WITH ORDINALITY AS leg(value, ord)
) AS comparisons;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM raw_candidate_comparisons
        GROUP BY facility, signature
        HAVING count(DISTINCT comparison_semantics) <> 1
    ) OR EXISTS (
        SELECT 1
        FROM raw_report_signatures AS raw
        CROSS JOIN LATERAL jsonb_array_elements(raw.pricing_legs) AS leg(value)
        LEFT JOIN pricing.i95_modeled_od_proxy AS proxy
          ON proxy.target_od_pair_id =
             (leg.value->'pricing_key'->>'od_pair_id')::integer
        WHERE raw.facility = 'i95_i495'
        GROUP BY
            raw.direction,
            leg.value->'pricing_key'->'od_pair_id',
            leg.value->'pricing_key'->'charge_index'
        HAVING count(DISTINCT jsonb_build_object(
            'effective_od_pair_id', coalesce(
                proxy.proxy_od_pair_id,
                (leg.value->'pricing_key'->>'od_pair_id')::integer
            ),
            'required_status', proxy.required_status
        )) <> 1
    ) THEN
        RAISE EXCEPTION 'normalized lookup semantics produced different results';
    END IF;
END $$;

DO $$
DECLARE
    normalized_count integer;
    source_key_count integer;
BEGIN
    SELECT count(DISTINCT signature), count(DISTINCT leg.value->'pricing_key'->>'source_route_key')
    INTO normalized_count, source_key_count
    FROM raw_report_signatures AS raw
    CROSS JOIN LATERAL jsonb_array_elements(raw.pricing_legs) AS leg(value)
    WHERE raw.facility = 'i66'
      AND raw.direction = 'eastbound'
      AND leg.value->'pricing_key'->>'start_zone_id' = '3100'
      AND leg.value->'pricing_key'->>'end_zone_id' = '3110';
    IF (normalized_count, source_key_count) <> (1, 6) THEN
        RAISE EXCEPTION 'I-66 3100-to-3110 normalization changed';
    END IF;

    SELECT count(DISTINCT signature), count(DISTINCT leg.value->'pricing_key'->>'source_route_key')
    INTO normalized_count, source_key_count
    FROM raw_report_signatures AS raw
    CROSS JOIN LATERAL jsonb_array_elements(raw.pricing_legs) AS leg(value)
    WHERE raw.facility = 'i66'
      AND raw.direction = 'eastbound'
      AND leg.value->'pricing_key'->>'start_zone_id' = '3100'
      AND leg.value->'pricing_key'->>'end_zone_id' = '3130';
    IF (normalized_count, source_key_count) <> (1, 12) THEN
        RAISE EXCEPTION 'I-66 3100-to-3130 normalization changed';
    END IF;

    SELECT count(DISTINCT signature), count(DISTINCT leg.value->'pricing_key'->>'source_route_key')
    INTO normalized_count, source_key_count
    FROM raw_report_signatures AS raw
    CROSS JOIN LATERAL jsonb_array_elements(raw.pricing_legs) AS leg(value)
    WHERE raw.facility = 'i66'
      AND raw.direction = 'eastbound'
      AND leg.value->'pricing_key'->>'start_zone_id' = '3110'
      AND leg.value->'pricing_key'->>'end_zone_id' = '3130';
    IF (normalized_count, source_key_count) <> (1, 16) THEN
        RAISE EXCEPTION 'I-66 3110-to-3130 normalization changed';
    END IF;

    IF jsonb_build_array(jsonb_build_object(
           'facility', 'i66', 'direction', 'eastbound',
           'start_zone_id', 3100, 'end_zone_id', 3110, 'charge_index', NULL
       )) = jsonb_build_array(jsonb_build_object(
           'facility', 'i66', 'direction', 'westbound',
           'start_zone_id', 3100, 'end_zone_id', 3110, 'charge_index', NULL
       ))
       OR jsonb_build_array(jsonb_build_object(
           'facility', 'i95_i495', 'direction', 'northbound',
           'od_pair_id', 1132, 'charge_index', NULL
       )) = jsonb_build_array(jsonb_build_object(
           'facility', 'i95_i495', 'direction', 'northbound',
           'od_pair_id', 1133, 'charge_index', NULL
       ))
       OR jsonb_build_array(jsonb_build_object(
           'facility', 'i95_i495', 'direction', 'northbound',
           'od_pair_id', 1132, 'charge_index', NULL
       )) = jsonb_build_array(jsonb_build_object(
           'facility', 'i95_i495', 'direction', 'northbound',
           'od_pair_id', 1132, 'charge_index', 1
       ))
       OR jsonb_build_array('{"facility":"i66","direction":"eastbound","start_zone_id":3100,"end_zone_id":3110,"charge_index":null}'::jsonb,
                            '{"facility":"i66","direction":"eastbound","start_zone_id":3110,"end_zone_id":3130,"charge_index":null}'::jsonb)
          = jsonb_build_array('{"facility":"i66","direction":"eastbound","start_zone_id":3110,"end_zone_id":3130,"charge_index":null}'::jsonb,
                              '{"facility":"i66","direction":"eastbound","start_zone_id":3100,"end_zone_id":3110,"charge_index":null}'::jsonb) THEN
        RAISE EXCEPTION 'normalized lookup inputs or leg order did not split';
    END IF;
END $$;

DO $$
BEGIN
    IF pg_get_function_result('oracle.get_agent_report_routes()'::regprocedure)
       <> 'TABLE(facility text, path_id text, path_order integer, pricing_legs jsonb, origin_area text, destination_area text, direction text)'
       OR (SELECT prosecdef FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure) IS NOT TRUE
       OR (SELECT provolatile FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure) <> 's'
       OR (SELECT proconfig FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure)
          IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR (SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc
           WHERE oid = 'oracle.get_agent_report_routes()'::regprocedure)
          <> 'oracle_owner'
       OR (SELECT count(*)
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure) <> 2
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure
             AND NOT (
                 privilege.grantor = 'oracle_owner'::regrole
                 AND privilege.privilege_type = 'EXECUTE'
                 AND NOT privilege.is_grantable
                 AND privilege.grantee IN (
                     'oracle_owner'::regrole,
                     'report_publisher'::regrole
                 )
             )
       )
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure
             AND privilege.grantor = 'oracle_owner'::regrole
             AND privilege.grantee = 'oracle_owner'::regrole
             AND privilege.privilege_type = 'EXECUTE'
             AND NOT privilege.is_grantable
       )
       OR NOT EXISTS (
           SELECT 1
           FROM pg_catalog.pg_proc AS procedure
           CROSS JOIN LATERAL aclexplode(procedure.proacl) AS privilege
           WHERE procedure.oid =
                 'oracle.get_agent_report_routes()'::regprocedure
             AND privilege.grantor = 'oracle_owner'::regrole
             AND privilege.grantee = 'report_publisher'::regrole
             AND privilege.privilege_type = 'EXECUTE'
             AND NOT privilege.is_grantable
       ) THEN
        RAISE EXCEPTION 'agent report function catalog contract is wrong';
    END IF;
END $$;

CREATE TEMP TABLE toll_route_point AS SELECT NULL::text AS point_id;
CREATE TEMP TABLE route_pricing_component AS SELECT NULL::text AS facility;
DO $$
BEGIN
    IF (SELECT jsonb_agg(to_jsonb(report) ORDER BY path_order)
        FROM oracle.get_agent_report_routes() AS report)
       IS DISTINCT FROM
       (SELECT jsonb_agg(to_jsonb(report) ORDER BY path_order)
        FROM report_routes_run1 AS report) THEN
        RAISE EXCEPTION 'temporary shadow object changed report routes';
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
       ) OR NOT has_function_privilege(
           'report_publisher', 'oracle.get_agent_report_routes()', 'EXECUTE'
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
          AND procedure.oid NOT IN (
              'oracle.get_i95_i495_report_inputs()'::regprocedure,
              'oracle.get_agent_report_routes()'::regprocedure
          )
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
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'EXPECTED_FAILURE stage=publisher_relation sqlstate=% message=permission denied', SQLSTATE;
    END;
    BEGIN
        PERFORM * FROM oracle.validate_toll_route('x', 'y');
        RAISE EXCEPTION 'report publisher executed an unrelated function';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'EXPECTED_FAILURE stage=publisher_function sqlstate=% message=permission denied', SQLSTATE;
    END;
END $$;
RESET ROLE;

DO $$
BEGIN
    CREATE ROLE report_contract_unrelated NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
GRANT USAGE ON SCHEMA oracle TO report_contract_unrelated;
SET ROLE report_contract_unrelated;
DO $$
BEGIN
    BEGIN
        PERFORM * FROM oracle.get_agent_report_routes();
        RAISE EXCEPTION 'unrelated role executed agent report routes';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'EXPECTED_FAILURE stage=public_execute sqlstate=% message=permission denied', SQLSTATE;
    END;
END $$;
RESET ROLE;
REVOKE USAGE ON SCHEMA oracle FROM report_contract_unrelated;
DROP ROLE report_contract_unrelated;

-- Guarded, rerunnable coordinate upgrade for the oracle 1.0.1 release.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    changed_rows integer;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.0.0', '1.0.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.0.0 or 1.0.1, got %',
            current_version;
    END IF;

    IF to_regclass('oracle.toll_route_point') IS NULL THEN
        RAISE EXCEPTION 'oracle schema prerequisites are not ready';
    END IF;

    IF current_version = '1.0.0' THEN
        WITH coordinate_sources(
            source_key, coordinate_quality, coordinate_source
        ) AS (
            VALUES
                (
                    'faa_dca', 'official_reference_point',
                    '{"method":"faa_airport_reference_point","provider":"Federal Aviation Administration","retrieved_at":"2026-08-17","source_id":"DCA","source_url":"https://nfdc.faa.gov/nfdcApps/services/ajv5/airportDisplay.jsp?airportId=DCA"}'::jsonb
                ),
                (
                    'faa_iad', 'official_reference_point',
                    '{"method":"faa_airport_reference_point","provider":"Federal Aviation Administration","retrieved_at":"2026-08-17","source_id":"IAD","source_url":"https://nfdc.faa.gov/nfdcApps/services/ajv5/airportDisplay.jsp?airportId=IAD"}'::jsonb
                ),
                (
                    'vdot_i66', 'approximate_interchange',
                    '{"evidence_url":"https://vdot.virginia.gov/projects/major-projects/66expresslanes/about/","method":"reviewed_interchange_projected_to_route_centerline","provider":"Virginia Department of Transportation","retrieved_at":"2026-08-17","source_feature_id":97140,"source_feature_name":"R-VA   IS00066EB","source_url":"https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/LRS_Route_Master/FeatureServer/0"}'::jsonb
                ),
                (
                    'vdot_sr267_dtr', 'approximate_interchange',
                    '{"evidence_url":"https://www.dullestollroad.com/maps-interchanges","method":"reviewed_interchange_projected_to_route_centerline","provider":"Virginia Department of Transportation","retrieved_at":"2026-08-17","source_feature_id":5707,"source_feature_name":"R-VA   SR00267EB","source_url":"https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/LRS_Route_Master/FeatureServer/0"}'::jsonb
                ),
                (
                    'vdot_sr267_greenway', 'approximate_interchange',
                    '{"evidence_url":"https://www.dullesgreenway.com/toll-calculator/","method":"reviewed_interchange_projected_to_route_centerline","provider":"Virginia Department of Transportation","retrieved_at":"2026-08-17","source_feature_id":5707,"source_feature_name":"R-VA   SR00267EB","source_url":"https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/LRS_Route_Master/FeatureServer/0"}'::jsonb
                ),
                (
                    'vdot_sr267_i66', 'approximate_interchange',
                    '{"evidence_url":"https://vdot.virginia.gov/projects/major-projects/66expresslanes/about/","method":"reviewed_interchange_projected_to_route_centerline","provider":"Virginia Department of Transportation","retrieved_at":"2026-08-17","source_feature_id":5707,"source_feature_name":"R-VA   SR00267EB","source_url":"https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/LRS_Route_Master/FeatureServer/0"}'::jsonb
                )
        ),
        locations(
            network_id, source_node_id, longitude, latitude, source_key
        ) AS (
            VALUES
                ('airport_dca', 'DCA', -77.0377214, 38.8514403, 'faa_dca'),
                ('airport_iad', 'IAD', -77.4599286, 38.9474564, 'faa_iad'),
                ('dtr', '10', -77.3983638, 38.9545776, 'vdot_sr267_dtr'),
                ('dtr', '11', -77.3739791, 38.9528520, 'vdot_sr267_dtr'),
                ('dtr', '12', -77.3564815, 38.9519397, 'vdot_sr267_dtr'),
                ('dtr', '13', -77.3379578, 38.9467082, 'vdot_sr267_dtr'),
                ('dtr', '14', -77.3117472, 38.9475129, 'vdot_sr267_dtr'),
                ('dtr', '15', -77.2679980, 38.9364969, 'vdot_sr267_dtr'),
                ('dtr', '16', -77.2468048, 38.9338704, 'vdot_sr267_dtr'),
                ('dtr', '17', -77.2332489, 38.9335214, 'vdot_sr267_dtr'),
                ('dtr', '1819', -77.2126604, 38.9318591, 'vdot_sr267_dtr'),
                ('dtr', '28', -77.4278587, 38.9646107, 'vdot_sr267_dtr'),
                ('dtr', '66', -77.1849815, 38.8999364, 'vdot_sr267_dtr'),
                ('greenway', '1', -77.5652813, 39.1000972, 'vdot_sr267_greenway'),
                ('greenway', '2A', -77.5663725, 39.0867135, 'vdot_sr267_greenway'),
                ('greenway', '2B', -77.5653713, 39.0734586, 'vdot_sr267_greenway'),
                ('greenway', '3', -77.5623098, 39.0604467, 'vdot_sr267_greenway'),
                ('greenway', '4', -77.5228923, 39.0368575, 'vdot_sr267_greenway'),
                ('greenway', '5', -77.5083964, 39.0302984, 'vdot_sr267_greenway'),
                ('greenway', '6', -77.4966979, 39.0107879, 'vdot_sr267_greenway'),
                ('greenway', '7', -77.4784892, 38.9975485, 'vdot_sr267_greenway'),
                ('greenway', '8', -77.4589620, 38.9906018, 'vdot_sr267_greenway'),
                ('greenway', '28', -77.4278587, 38.9646107, 'vdot_sr267_greenway'),
                ('i66', '1', -77.2189905, 38.8862187, 'vdot_i66'),
                ('i66', '10', -77.1663129, 38.8914007, 'vdot_i66'),
                ('i66', '11', -77.1603661, 38.8870753, 'vdot_i66'),
                ('i66', '12', -77.1645989, 38.8899871, 'vdot_i66'),
                ('i66', '13', -77.0942755, 38.8976751, 'vdot_i66'),
                ('i66', '14', -77.0682271, 38.8967771, 'vdot_i66'),
                ('i66', '15', -77.0679009, 38.8946960, 'vdot_i66'),
                ('i66', '16', -77.0639945, 38.8916467, 'vdot_i66'),
                ('i66', '17', -77.0804369, 38.8970859, 'vdot_i66'),
                ('i66', '2', -77.2189905, 38.8862187, 'vdot_i66'),
                ('i66', '3', -77.2189905, 38.8862187, 'vdot_i66'),
                ('i66', '4', -77.1967508, 38.8987045, 'vdot_i66'),
                ('i66', '5', -77.2189905, 38.8862187, 'vdot_i66'),
                ('i66', '6', -77.1850131, 38.9001038, 'vdot_i66'),
                ('i66', '7', -77.2035113, 38.9285321, 'vdot_sr267_i66'),
                ('i66', '8', -77.1563453, 38.8856285, 'vdot_i66'),
                ('i66', '9', -77.1176218, 38.8865049, 'vdot_i66')
        )
        UPDATE oracle.toll_route_point AS route_point
        SET
            location = oracle.ST_SetSRID(
                oracle.ST_MakePoint(locations.longitude, locations.latitude),
                4326
            )::oracle.geography,
            source_metadata =
                (route_point.source_metadata - 'coordinate_quality')
                || jsonb_build_object(
                    'coordinate_quality', coordinate_sources.coordinate_quality,
                    'coordinate_source', coordinate_sources.coordinate_source
                )
        FROM locations
        JOIN coordinate_sources USING (source_key)
        WHERE route_point.network_id = locations.network_id
          AND route_point.source_node_id = locations.source_node_id
          AND route_point.location IS NULL;

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 113 THEN
            RAISE EXCEPTION 'expected 113 oracle coordinate updates, got %',
                changed_rows;
        END IF;

        UPDATE oracle.schema_version
        SET version = '1.0.1', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.0.0';

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 1 THEN
            RAISE EXCEPTION 'expected one oracle schema version update, got %',
                changed_rows;
        END IF;
    END IF;

    IF (SELECT count(*) FROM oracle.toll_route_point WHERE location IS NOT NULL) <> 220
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
        RAISE EXCEPTION 'oracle 1.0.1 coordinate contract is not satisfied';
    END IF;
END
$migration$;

CREATE OR REPLACE FUNCTION oracle.ramp_alternatives(
    submitted_point_id text,
    unchanged_point_id text,
    replace_origin boolean
) RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $function$
WITH RECURSIVE
submitted AS (
    SELECT route_point.*
    FROM oracle.toll_route_point AS route_point
    WHERE route_point.point_id = submitted_point_id
),
candidate_points AS (
    SELECT candidate.*
    FROM oracle.toll_route_point AS candidate
    CROSS JOIN submitted
    WHERE candidate.network_id = submitted.network_id
      AND candidate.point_type = CASE
          WHEN replace_origin THEN 'entry'
          ELSE 'exit'
      END
),
seeds AS (
    SELECT
        candidate.point_id AS alternative_point_id,
        candidate.point_id AS current_point_id,
        ARRAY[candidate.point_id]::text[] AS walked_point_ids,
        0 AS depth
    FROM candidate_points AS candidate
    WHERE replace_origin

    UNION ALL

    SELECT
        NULL::text,
        unchanged.point_id,
        ARRAY[unchanged.point_id]::text[],
        0
    FROM oracle.toll_route_point AS unchanged
    WHERE NOT replace_origin
      AND unchanged.point_id = unchanged_point_id
),
walk AS (
    SELECT
        seeds.alternative_point_id,
        seeds.current_point_id,
        seeds.walked_point_ids,
        seeds.depth
    FROM seeds

    UNION ALL

    SELECT
        walk.alternative_point_id,
        next_point.point_id,
        walk.walked_point_ids || next_point.point_id,
        walk.depth + 1
    FROM walk
    JOIN oracle.toll_route_point AS current_point
      ON current_point.point_id = walk.current_point_id
    JOIN oracle.toll_connection AS connection
      ON connection.from_point_id = walk.current_point_id
    JOIN oracle.toll_route_point AS next_point
      ON next_point.point_id = connection.to_point_id
    WHERE walk.depth < 12
      AND (NOT replace_origin OR walk.current_point_id <> unchanged_point_id)
      AND NOT next_point.point_id = ANY(walk.walked_point_ids)
      AND (
          current_point.point_type <> 'airport'
          OR (NOT replace_origin AND current_point.point_id = unchanged_point_id)
      )
      AND (
          next_point.point_type <> 'airport'
          OR (replace_origin AND next_point.point_id = unchanged_point_id)
      )
),
reachable AS (
    SELECT DISTINCT
        CASE
            WHEN replace_origin THEN walk.alternative_point_id
            ELSE walk.current_point_id
        END AS point_id
    FROM walk
    WHERE walk.depth > 0
      AND (
          (replace_origin AND walk.current_point_id = unchanged_point_id)
          OR (
              NOT replace_origin
              AND EXISTS (
                  SELECT 1
                  FROM candidate_points AS candidate
                  WHERE candidate.point_id = walk.current_point_id
              )
          )
      )
),
ranked AS (
    SELECT
        candidate.*,
        coalesce(preference.rank, 2147483647) AS preference_rank,
        CASE
            WHEN candidate.source_node_id = submitted.source_node_id THEN 0
            WHEN candidate.source_metadata
                     -> 'alternative_ranking' ->> 'corridor_position' IS NOT NULL
              AND submitted.source_metadata
                     -> 'alternative_ranking' ->> 'corridor_position' IS NOT NULL THEN
                abs(
                    (candidate.source_metadata
                        -> 'alternative_ranking' ->> 'corridor_position')::double precision
                    - (submitted.source_metadata
                        -> 'alternative_ranking' ->> 'corridor_position')::double precision
                )
            WHEN candidate.network_id IN ('i95', 'i495')
              AND candidate.location IS NOT NULL
              AND submitted.location IS NOT NULL THEN
                oracle.ST_Distance(candidate.location, submitted.location)
            ELSE 'Infinity'::double precision
        END AS distance
    FROM reachable
    JOIN candidate_points AS candidate USING (point_id)
    CROSS JOIN submitted
    LEFT JOIN LATERAL (
        SELECT preferred.ordinality::integer AS rank
        FROM jsonb_array_elements_text(
            coalesce(
                submitted.source_metadata
                    -> 'alternative_ranking' -> 'preferred_point_ids',
                '[]'::jsonb
            )
        ) WITH ORDINALITY AS preferred(point_id, ordinality)
        WHERE preferred.point_id = candidate.point_id
    ) AS preference ON true
    ORDER BY
        coalesce(preference.rank, 2147483647),
        distance,
        candidate.point_id
    LIMIT 2
)
SELECT coalesce(
    jsonb_agg(
        jsonb_build_object(
            'point_id', ranked.point_id,
            'network_id', ranked.network_id,
            'source_node_id', ranked.source_node_id,
            'point_type', ranked.point_type,
            'direction', ranked.direction,
            'label', ranked.label,
            'aliases', to_jsonb(ranked.aliases),
            'location', CASE
                WHEN ranked.location IS NULL THEN NULL
                ELSE oracle.ST_AsGeoJSON(ranked.location)::jsonb
            END
        )
        ORDER BY ranked.preference_rank, ranked.distance, ranked.point_id
    ),
    '[]'::jsonb
)
FROM ranked
$function$;

COMMIT;

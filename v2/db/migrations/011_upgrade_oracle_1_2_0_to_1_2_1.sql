-- Correct the DTR mainline boundary and Exit 16 ramp direction.

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

    IF current_version NOT IN ('1.2.0', '1.2.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.2.0 or 1.2.1, got %',
            current_version;
    END IF;

    IF current_version = '1.2.0' THEN
        WITH dtr_connections AS (
            SELECT
                connection.connection_id,
                connection.source_metadata,
                array_position(
                    ARRAY[
                        '28', '10', '11', '12', '13', '14',
                        '15', '16', '17', '1819', '66'
                    ]::text[],
                    split_part(connection.source_route_key, ':', 2)
                ) AS entry_position,
                array_position(
                    ARRAY[
                        '28', '10', '11', '12', '13', '14',
                        '15', '16', '17', '1819', '66'
                    ]::text[],
                    split_part(connection.source_route_key, ':', 3)
                ) AS exit_position
            FROM oracle.toll_connection AS connection
            JOIN oracle.toll_route_point AS origin
              ON origin.point_id = connection.from_point_id
            WHERE connection.connection_type = 'within_facility'
              AND origin.network_id = 'dtr'
        ), ramp_charges AS (
            SELECT
                dtr.connection_id,
                charge.value AS charge,
                CASE
                    WHEN charge.value->>'label' LIKE 'Entrance ramp%'
                    THEN 1
                    ELSE 3
                END AS component_order,
                charge.ordinality
            FROM dtr_connections AS dtr
            CROSS JOIN LATERAL jsonb_array_elements(
                dtr.source_metadata #> '{source_pair,charges}'
            ) WITH ORDINALITY AS charge(value, ordinality)
            WHERE charge.value->>'label' <> 'Mainline plaza'
              AND charge.value->>'label'
                  <> 'Entrance ramp at Exit 16 - SR 7 (Leesburg Pike)'
        ), desired_components AS (
            SELECT
                ramp.connection_id,
                ramp.charge,
                ramp.component_order,
                ramp.ordinality
            FROM ramp_charges AS ramp

            UNION ALL

            SELECT
                dtr.connection_id,
                jsonb_build_object(
                    'label', 'Mainline plaza',
                    'price_off_peak_usd', '4.00',
                    'price_peak_usd', '4.00'
                ),
                2,
                0
            FROM dtr_connections AS dtr
            WHERE least(dtr.entry_position, dtr.exit_position) <= 8
              AND 8 < greatest(dtr.entry_position, dtr.exit_position)
        ), desired_charges AS (
            SELECT
                dtr.connection_id,
                coalesce((
                    SELECT jsonb_agg(
                        component.charge
                        ORDER BY component.component_order, component.ordinality
                    )
                    FROM desired_components AS component
                    WHERE component.connection_id = dtr.connection_id
                ), '[]'::jsonb) AS charges
            FROM dtr_connections AS dtr
        )
        UPDATE oracle.toll_connection AS connection
        SET source_metadata = jsonb_set(
            connection.source_metadata,
            '{source_pair,charges}',
            desired.charges
        )
        FROM desired_charges AS desired
        WHERE connection.connection_id = desired.connection_id
          AND connection.source_metadata #> '{source_pair,charges}'
              IS DISTINCT FROM desired.charges;

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 20 THEN
            RAISE EXCEPTION 'expected 20 corrected DTR pairs, got %', changed_rows;
        END IF;

        UPDATE oracle.schema_version
        SET version = '1.2.1', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.2.0';
    END IF;
END
$migration$;

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.2.1'
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_connection AS connection
           JOIN oracle.toll_route_point AS origin
             ON origin.point_id = connection.from_point_id
           LEFT JOIN LATERAL jsonb_array_elements(
               connection.source_metadata #> '{source_pair,charges}'
           ) AS charge(value) ON true
           WHERE origin.network_id = 'dtr'
             AND connection.connection_type = 'within_facility'
           GROUP BY connection.connection_id, connection.source_route_key
           HAVING count(*) FILTER (
               WHERE charge.value->>'label'
                   = 'Entrance ramp at Exit 16 - SR 7 (Leesburg Pike)'
           ) <> 0
              OR count(*) FILTER (
                  WHERE charge.value->>'label' = 'Mainline plaza'
              ) <> CASE
                  WHEN least(
                      array_position(
                          ARRAY[
                              '28', '10', '11', '12', '13', '14',
                              '15', '16', '17', '1819', '66'
                          ]::text[],
                          split_part(connection.source_route_key, ':', 2)
                      ),
                      array_position(
                          ARRAY[
                              '28', '10', '11', '12', '13', '14',
                              '15', '16', '17', '1819', '66'
                          ]::text[],
                          split_part(connection.source_route_key, ':', 3)
                      )
                  ) <= 8
                   AND 8 < greatest(
                      array_position(
                          ARRAY[
                              '28', '10', '11', '12', '13', '14',
                              '15', '16', '17', '1819', '66'
                          ]::text[],
                          split_part(connection.source_route_key, ':', 2)
                      ),
                      array_position(
                          ARRAY[
                              '28', '10', '11', '12', '13', '14',
                              '15', '16', '17', '1819', '66'
                          ]::text[],
                          split_part(connection.source_route_key, ':', 3)
                      )
                  ) THEN 1
                  ELSE 0
              END
       ) THEN
        RAISE EXCEPTION 'oracle 1.2.1 DTR correction is not installed';
    END IF;
END
$migration$;

COMMIT;

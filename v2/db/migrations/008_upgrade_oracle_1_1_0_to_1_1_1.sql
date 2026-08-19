-- Bundle the published surcharge into the Greenway mainline charge.

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

    IF current_version NOT IN ('1.1.0', '1.1.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.1.0 or 1.1.1, got %',
            current_version;
    END IF;

    IF current_version = '1.1.0' THEN
        IF (
            SELECT count(*)
            FROM oracle.toll_connection AS connection
            JOIN oracle.toll_route_point AS origin
              ON origin.point_id = connection.from_point_id
            CROSS JOIN LATERAL jsonb_array_elements(
                connection.source_metadata #> '{source_pair,charges}'
            ) AS charge(value)
            WHERE origin.network_id = 'greenway'
              AND charge.value->>'facility' = 'dulles_toll_road'
        ) <> 17 OR EXISTS (
            SELECT 1
            FROM oracle.toll_connection AS connection
            JOIN oracle.toll_route_point AS origin
              ON origin.point_id = connection.from_point_id
            WHERE origin.network_id = 'greenway'
              AND jsonb_path_exists(
                  connection.source_metadata,
                  '$.source_pair.charges[*] ? (@.facility == "dulles_toll_road")'
              )
              AND (
                  jsonb_array_length(
                      connection.source_metadata #> '{source_pair,charges}'
                  ) <> 2
                  OR (
                      SELECT count(*)
                      FROM jsonb_array_elements(
                          connection.source_metadata #> '{source_pair,charges}'
                      ) AS charge(value)
                      WHERE charge.value = jsonb_build_object(
                          'label', 'Mainline plaza',
                          'price_off_peak_usd', '5.25',
                          'price_peak_usd', '5.80'
                      )
                  ) <> 1
                  OR (
                      SELECT count(*)
                      FROM jsonb_array_elements(
                          connection.source_metadata #> '{source_pair,charges}'
                      ) AS charge(value)
                      WHERE charge.value = jsonb_build_object(
                          'facility', 'dulles_toll_road',
                          'label', 'Mainline plaza',
                          'price_off_peak_usd', '2.00',
                          'price_peak_usd', '2.00'
                      )
                  ) <> 1
              )
        ) THEN
            RAISE EXCEPTION 'Greenway surcharge source pairs are not canonical';
        END IF;

        WITH affected AS (
            SELECT connection.connection_id
            FROM oracle.toll_connection AS connection
            JOIN oracle.toll_route_point AS origin
              ON origin.point_id = connection.from_point_id
            WHERE origin.network_id = 'greenway'
              AND jsonb_path_exists(
                  connection.source_metadata,
                  '$.source_pair.charges[*] ? (@.facility == "dulles_toll_road")'
              )
        ), normalized AS (
            SELECT
                affected.connection_id,
                jsonb_build_array(jsonb_build_object(
                    'label', 'Mainline plaza',
                    'price_off_peak_usd', '7.25',
                    'price_peak_usd', '7.80'
                )) AS charges
            FROM affected
        )
        UPDATE oracle.toll_connection AS connection
        SET source_metadata = jsonb_set(
            connection.source_metadata,
            '{source_pair,charges}',
            normalized.charges
        )
        FROM normalized
        WHERE connection.connection_id = normalized.connection_id;

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 17 THEN
            RAISE EXCEPTION 'expected 17 Greenway surcharge updates, got %',
                changed_rows;
        END IF;

        CREATE OR REPLACE VIEW oracle.route_pricing_component AS
        SELECT
            connection.connection_id,
            component.ordinality::integer AS component_order,
            connection.from_point_id,
            connection.to_point_id,
            connection.source_metadata
                #>> '{general_purpose_fallback,boundary_point_id}'
                AS boundary_point_id,
            jsonb_array_length(connection.source_metadata #> '{source_pair,ods}')
                AS component_count,
            'i95_i495'::text AS facility,
            connection.source_route_key,
            component.value::integer AS od_pair_id,
            NULL::integer AS start_zone_id,
            NULL::integer AS end_zone_id,
            NULL::jsonb AS charge
        FROM oracle.toll_connection AS connection
        CROSS JOIN LATERAL jsonb_array_elements_text(
            connection.source_metadata #> '{source_pair,ods}'
        ) WITH ORDINALITY AS component(value, ordinality)
        WHERE connection.connection_type IN (
            'within_facility', 'general_purpose_gap'
        )

        UNION ALL

        SELECT
            connection.connection_id,
            1,
            connection.from_point_id,
            connection.to_point_id,
            NULL,
            1,
            'i66',
            connection.source_route_key,
            NULL,
            (connection.source_metadata #>> '{source_pair,start_zone}')::integer,
            (connection.source_metadata #>> '{source_pair,end_zone}')::integer,
            NULL
        FROM oracle.toll_connection AS connection
        JOIN oracle.toll_route_point AS origin
          ON origin.point_id = connection.from_point_id
        WHERE connection.connection_type = 'within_facility'
          AND origin.network_id = 'i66'

        UNION ALL

        SELECT
            connection.connection_id,
            component.ordinality::integer,
            connection.from_point_id,
            connection.to_point_id,
            NULL,
            jsonb_array_length(
                connection.source_metadata #> '{source_pair,charges}'
            ),
            origin.network_id,
            connection.source_route_key,
            NULL,
            NULL,
            NULL,
            component.value
        FROM oracle.toll_connection AS connection
        JOIN oracle.toll_route_point AS origin
          ON origin.point_id = connection.from_point_id
        CROSS JOIN LATERAL jsonb_array_elements(
            connection.source_metadata #> '{source_pair,charges}'
        ) WITH ORDINALITY AS component(value, ordinality)
        WHERE connection.connection_type = 'within_facility'
          AND origin.network_id IN ('dtr', 'greenway')
          AND (
              (component.value->>'price_peak_usd')::numeric > 0
              OR (component.value->>'price_off_peak_usd')::numeric > 0
          );

        ALTER VIEW oracle.route_pricing_component OWNER TO oracle_owner;

        UPDATE oracle.schema_version
        SET version = '1.1.1', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.1.0';
    END IF;
END
$migration$;

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.1'
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_connection AS connection
           JOIN oracle.toll_route_point AS origin
             ON origin.point_id = connection.from_point_id
           CROSS JOIN LATERAL jsonb_array_elements(
               connection.source_metadata #> '{source_pair,charges}'
           ) AS charge(value)
           WHERE origin.network_id = 'greenway'
             AND charge.value ? 'facility'
       )
       OR (
           SELECT count(*)
           FROM oracle.toll_connection AS connection
           JOIN oracle.toll_route_point AS origin
             ON origin.point_id = connection.from_point_id
           WHERE origin.network_id = 'greenway'
             AND connection.source_metadata #> '{source_pair,charges}'
                 = jsonb_build_array(jsonb_build_object(
                     'label', 'Mainline plaza',
                     'price_off_peak_usd', '7.25',
                     'price_peak_usd', '7.80'
                 ))
       ) <> 17
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_connection
           WHERE connection_id IN ('greenway_to_dtr', 'dtr_to_greenway')
             AND (
                 source_route_key IS NOT NULL
                 OR source_metadata ? 'pricing_facility'
                 OR source_metadata ? 'source_pair'
             )
       )
       OR EXISTS (
           SELECT 1
           FROM oracle.route_pricing_component AS component
           JOIN oracle.toll_connection AS connection USING (connection_id)
           WHERE connection.connection_type IN ('toll_handoff', 'airport_access')
       )
       OR EXISTS (
           SELECT 1
           FROM oracle.route_pricing_component
           GROUP BY connection_id
           HAVING count(DISTINCT facility) <> 1
       )
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.validate_pricing_route(text[],text[])',
           'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'oracle 1.1.1 pricing-route contract is not satisfied';
    END IF;
END
$migration$;

COMMIT;

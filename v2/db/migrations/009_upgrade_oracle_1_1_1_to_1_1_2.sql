-- Price the Dulles Toll Road connection only on Greenway/DTR handoffs.

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
    old_note text :=
        'Every mainline crossing also incurs a separate $2.00 Dulles Toll Road charge.';
    new_note text :=
        'Only trips that continue through the Route 28 handoff onto the Dulles Toll Road incur its separate $2.00 connection charge; direct Route 28/Dulles Airport trips do not.';
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.1.1', '1.1.2') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.1.1 or 1.1.2, got %',
            current_version;
    END IF;

    IF current_version = '1.1.1' THEN
        IF (
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
        ) <> 17 OR EXISTS (
            SELECT 1
            FROM oracle.toll_connection
            WHERE connection_id IN ('greenway_to_dtr', 'dtr_to_greenway')
              AND (
                  source_route_key IS NOT NULL
                  OR source_metadata ? 'pricing_facility'
                  OR source_metadata ? 'pricing_charge'
              )
        ) THEN
            RAISE EXCEPTION 'oracle 1.1.1 Greenway pricing is not canonical';
        END IF;

        UPDATE oracle.toll_connection AS connection
        SET source_metadata = jsonb_set(
            connection.source_metadata,
            '{source_pair,charges}',
            jsonb_build_array(jsonb_build_object(
                'label', 'Mainline plaza',
                'price_off_peak_usd', '5.25',
                'price_peak_usd', '5.80'
            ))
        )
        FROM oracle.toll_route_point AS origin
        WHERE origin.point_id = connection.from_point_id
          AND origin.network_id = 'greenway'
          AND connection.source_metadata #> '{source_pair,charges}'
              = jsonb_build_array(jsonb_build_object(
                  'label', 'Mainline plaza',
                  'price_off_peak_usd', '7.25',
                  'price_peak_usd', '7.80'
              ));

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 17 THEN
            RAISE EXCEPTION 'expected 17 Greenway mainline updates, got %',
                changed_rows;
        END IF;

        UPDATE oracle.toll_connection
        SET source_route_key = connection_id,
            source_metadata = source_metadata || jsonb_build_object(
                'pricing_facility', 'dtr',
                'pricing_charge', jsonb_build_object(
                    'label', 'Dulles Toll Road connection',
                    'price_off_peak_usd', '2.00',
                    'price_peak_usd', '2.00'
                )
            )
        WHERE connection_id IN ('greenway_to_dtr', 'dtr_to_greenway');

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        IF changed_rows <> 2 THEN
            RAISE EXCEPTION 'expected 2 priced Greenway/DTR handoffs, got %',
                changed_rows;
        END IF;

        UPDATE oracle.toll_route_point
        SET source_metadata = jsonb_set(
            source_metadata,
            '{source_context,notes}',
            to_jsonb(replace(
                source_metadata #>> '{source_context,notes}', old_note, new_note
            ))
        )
        WHERE network_id = 'greenway'
          AND source_metadata #>> '{source_context,notes}' LIKE '%' || old_note || '%';

        UPDATE oracle.toll_connection AS connection
        SET source_metadata = jsonb_set(
            connection.source_metadata,
            '{source_context,notes}',
            to_jsonb(replace(
                connection.source_metadata #>> '{source_context,notes}',
                old_note,
                new_note
            ))
        )
        FROM oracle.toll_route_point AS origin
        WHERE origin.point_id = connection.from_point_id
          AND origin.network_id = 'greenway'
          AND connection.source_metadata #>> '{source_context,notes}'
              LIKE '%' || old_note || '%';

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
          )

        UNION ALL

        SELECT
            connection.connection_id,
            1,
            connection.from_point_id,
            connection.to_point_id,
            NULL,
            1,
            connection.source_metadata->>'pricing_facility',
            connection.source_route_key,
            NULL,
            NULL,
            NULL,
            connection.source_metadata->'pricing_charge'
        FROM oracle.toll_connection AS connection
        WHERE connection.connection_type = 'toll_handoff'
          AND connection.source_metadata ? 'pricing_facility'
          AND connection.source_metadata ? 'pricing_charge';

        ALTER VIEW oracle.route_pricing_component OWNER TO oracle_owner;

        UPDATE oracle.schema_version
        SET version = '1.1.2', installed_at = clock_timestamp()
        WHERE singleton AND version = '1.1.1';
    END IF;
END
$migration$;

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.1.2'
       OR (
           SELECT count(*)
           FROM oracle.toll_connection AS connection
           JOIN oracle.toll_route_point AS origin
             ON origin.point_id = connection.from_point_id
           WHERE origin.network_id = 'greenway'
             AND connection.source_metadata #> '{source_pair,charges}'
                 = jsonb_build_array(jsonb_build_object(
                     'label', 'Mainline plaza',
                     'price_off_peak_usd', '5.25',
                     'price_peak_usd', '5.80'
                 ))
       ) <> 17
       OR (
           SELECT count(*)
           FROM oracle.route_pricing_component
           WHERE connection_id IN ('greenway_to_dtr', 'dtr_to_greenway')
             AND facility = 'dtr'
             AND source_route_key = connection_id
             AND charge = jsonb_build_object(
                 'label', 'Dulles Toll Road connection',
                 'price_off_peak_usd', '2.00',
                 'price_peak_usd', '2.00'
             )
       ) <> 2
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_connection
           WHERE connection_id NOT IN ('greenway_to_dtr', 'dtr_to_greenway')
             AND connection_type = 'toll_handoff'
             AND (
                 source_route_key IS NOT NULL
                 OR source_metadata ? 'pricing_facility'
                 OR source_metadata ? 'pricing_charge'
             )
       )
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_route_point
           WHERE network_id = 'greenway'
             AND source_metadata #>> '{source_context,notes}' LIKE
                 '%Every mainline crossing also incurs a separate $2.00%'
       )
       OR EXISTS (
           SELECT 1
           FROM oracle.toll_connection AS connection
           JOIN oracle.toll_route_point AS origin
             ON origin.point_id = connection.from_point_id
           WHERE origin.network_id = 'greenway'
             AND connection.source_metadata #>> '{source_context,notes}' LIKE
                 '%Every mainline crossing also incurs a separate $2.00%'
       ) THEN
        RAISE EXCEPTION 'oracle 1.1.2 conditional DTR pricing is not satisfied';
    END IF;
END
$migration$;

COMMIT;

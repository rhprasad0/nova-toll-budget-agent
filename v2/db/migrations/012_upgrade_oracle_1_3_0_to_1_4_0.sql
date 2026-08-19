-- Add least-privilege I-66 current pricing comparisons.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.3.0', '1.4.0') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.3.0 or 1.4.0, got %',
            current_version;
    END IF;
    IF to_regclass('pricing.i66_pricing_comparisons') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.4.0 requires I-66 pricing comparisons';
    END IF;
END
$migration$;

SELECT version = '1.3.0' AS oracle_upgrade_needed
FROM oracle.schema_version
WHERE singleton
\gset

\if :oracle_upgrade_needed

GRANT SELECT ON pricing.i66_pricing_comparisons TO oracle_owner;

CREATE FUNCTION oracle.get_i66_pricing_comparisons(
    requested_start_zone_id integer,
    requested_end_zone_id integer
) RETURNS TABLE (
    evaluated_at timestamptz,
    comparison_kind text,
    comparison_offset integer,
    bin_start_at timestamptz,
    bin_end_at timestamptz,
    interval_end_at timestamptz,
    observed_at timestamptz,
    price_usd numeric,
    available boolean,
    availability_reason text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
WITH selected AS MATERIALIZED (
    SELECT
        comparison.evaluated_at,
        comparison.comparison_kind,
        comparison.comparison_offset,
        comparison.bin_start_at,
        comparison.bin_end_at,
        comparison.interval_end_at,
        comparison.observed_at,
        comparison.price_usd,
        comparison.available,
        comparison.availability_reason
    FROM pricing.i66_pricing_comparisons AS comparison
    WHERE comparison.start_zone_id = requested_start_zone_id
      AND comparison.end_zone_id = requested_end_zone_id
), diagnostic AS (
    SELECT
        statement_timestamp() AS evaluated_at,
        'current'::text AS comparison_kind,
        0 AS comparison_offset,
        NULL::timestamptz AS bin_start_at,
        NULL::timestamptz AS bin_end_at,
        NULL::timestamptz AS interval_end_at,
        NULL::timestamptz AS observed_at,
        NULL::numeric AS price_usd,
        false AS available,
        'missing_observation'::text AS availability_reason
    WHERE NOT EXISTS (
        SELECT 1 FROM selected WHERE selected.comparison_kind = 'current'
    )
), combined AS (
    SELECT * FROM selected
    UNION ALL
    SELECT * FROM diagnostic
)
SELECT * FROM combined
ORDER BY
    CASE comparison_kind
        WHEN 'current' THEN 0
        WHEN 'prior_cycle' THEN 1
        ELSE 2
    END,
    comparison_offset
$function$;

REVOKE ALL ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
TO tollchat_agent;
ALTER FUNCTION oracle.get_i66_pricing_comparisons(integer, integer)
OWNER TO oracle_owner;

UPDATE oracle.schema_version
SET version = '1.4.0', installed_at = clock_timestamp()
WHERE singleton AND version = '1.3.0';

\endif

DO $migration$
DECLARE
    pricing_function record;
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.4.0' THEN
        RAISE EXCEPTION 'oracle 1.4.0 is not installed';
    END IF;

    SELECT
        procedure.provolatile,
        procedure.prosecdef,
        procedure.proconfig,
        pg_get_userbyid(procedure.proowner) AS owner_name
    INTO STRICT pricing_function
    FROM pg_proc AS procedure
    WHERE procedure.oid =
        'oracle.get_i66_pricing_comparisons(integer,integer)'::regprocedure;

    IF pricing_function.provolatile <> 's'
       OR NOT pricing_function.prosecdef
       OR pricing_function.proconfig IS DISTINCT FROM
          ARRAY['search_path=pg_catalog, pg_temp']::text[]
       OR pricing_function.owner_name <> 'oracle_owner'
       OR NOT has_function_privilege(
           'tollchat_agent',
           'oracle.get_i66_pricing_comparisons(integer,integer)',
           'EXECUTE'
       )
       OR has_table_privilege(
           'tollchat_agent', 'pricing.i66_pricing_comparisons', 'SELECT'
       ) THEN
        RAISE EXCEPTION 'I-66 pricing security contract is not installed';
    END IF;
END
$migration$;

COMMIT;

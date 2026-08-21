-- Qualify Washington prompt labels by their usable toll approach.

\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    matching_rows integer;
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.9.0', '1.9.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.9.0 or 1.9.1, got %',
            current_version;
    END IF;
    IF to_regprocedure('oracle.get_toll_route_prompt_points()') IS NULL THEN
        RAISE EXCEPTION 'oracle 1.9.1 requires the oracle 1.9.0 contract';
    END IF;

    SELECT count(*) INTO matching_rows
    FROM oracle.toll_route_point AS point
    JOIN (
        VALUES
            ('i66:16:entry:WB', 'Washington'),
            ('i66:16:exit:EB', 'Washington'),
            ('i95:2232SO', 'Washington D.C.'),
            ('i95:224ND', 'Washington D.C.'),
            ('i95:2249ND', 'Washington D.C.')
    ) AS expected(point_id, label)
      ON expected.point_id = point.point_id
     AND expected.label = point.label
    WHERE point.aliases = ARRAY[]::text[];

    IF current_version = '1.9.0' AND matching_rows <> 5 THEN
        RAISE EXCEPTION 'oracle 1.9.0 Washington labels are not canonical';
    END IF;
END
$migration$;

UPDATE oracle.toll_route_point AS point
SET label = replacement.label,
    aliases = replacement.aliases
FROM (
    VALUES
        ('i66:16:entry:WB', 'Washington D.C. I-66', ARRAY['Washington']::text[]),
        ('i66:16:exit:EB', 'Washington D.C. I-66', ARRAY['Washington']::text[]),
        ('i95:2232SO', 'Washington D.C. I-395 Southbound', ARRAY['Washington D.C.']::text[]),
        ('i95:224ND', 'Washington D.C. I-95/I-395 Northbound', ARRAY['Washington D.C.']::text[]),
        ('i95:2249ND', 'Washington D.C. from I-495 Southbound via I-395', ARRAY['Washington D.C.']::text[])
) AS replacement(point_id, label, aliases)
WHERE point.point_id = replacement.point_id
  AND (SELECT version FROM oracle.schema_version WHERE singleton) = '1.9.0';

UPDATE oracle.schema_version
SET version = '1.9.1', installed_at = clock_timestamp()
WHERE singleton AND version = '1.9.0';

DO $migration$
DECLARE
    matching_rows integer;
BEGIN
    SELECT count(*) INTO matching_rows
    FROM oracle.toll_route_point AS point
    JOIN (
        VALUES
            ('i66:16:entry:WB', 'Washington D.C. I-66', ARRAY['Washington']::text[]),
            ('i66:16:exit:EB', 'Washington D.C. I-66', ARRAY['Washington']::text[]),
            ('i95:2232SO', 'Washington D.C. I-395 Southbound', ARRAY['Washington D.C.']::text[]),
            ('i95:224ND', 'Washington D.C. I-95/I-395 Northbound', ARRAY['Washington D.C.']::text[]),
            ('i95:2249ND', 'Washington D.C. from I-495 Southbound via I-395', ARRAY['Washington D.C.']::text[])
    ) AS expected(point_id, label, aliases)
      ON expected.point_id = point.point_id
     AND expected.label = point.label
     AND expected.aliases = point.aliases;

    IF (SELECT version FROM oracle.schema_version WHERE singleton) <> '1.9.1'
       OR matching_rows <> 5 THEN
        RAISE EXCEPTION 'oracle 1.9.1 Washington labels are not installed';
    END IF;
END
$migration$;

COMMIT;

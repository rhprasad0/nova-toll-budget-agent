-- Qualify distinct same-place exits by their committed route-graph approaches.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));
SET LOCAL ROLE oracle_owner;

CREATE TEMP TABLE approach_labels (
    point_id text PRIMARY KEY, old_label text, old_aliases jsonb,
    new_label text, new_aliases jsonb
) ON COMMIT DROP;
INSERT INTO approach_labels VALUES
    ('i495:1819ND', '495 Express Lanes End/George Wash. Mem. Pkwy.', '["George Washington Memorial Parkway", "GW Parkway", "McLean"]'::jsonb, '495 Express Lanes End/George Wash. Mem. Pkwy. (from I-95/I-395 southbound)', '["495 Express Lanes End/George Wash. Mem. Pkwy.", "George Washington Memorial Parkway", "GW Parkway", "McLean"]'::jsonb),
    ('i495:181ND', '495 Express Lanes End/George Wash. Mem. Pkwy.', '["George Washington Memorial Parkway", "GW Parkway", "McLean"]'::jsonb, '495 Express Lanes End/George Wash. Mem. Pkwy. (from I-495 northbound or I-95/I-395 northbound)', '["495 Express Lanes End/George Wash. Mem. Pkwy.", "George Washington Memorial Parkway", "GW Parkway", "McLean"]'::jsonb),
    ('i495:1829ND', 'Route 267', '["Dulles Toll Road", "Dulles Access Road", "Tysons Corner"]'::jsonb, 'Route 267 (from I-95/I-395 southbound)', '["Route 267", "Dulles Toll Road", "Dulles Access Road", "Tysons Corner"]'::jsonb),
    ('i495:182ND', 'Route 267', '["Dulles Toll Road", "Dulles Access Road", "Tysons Corner"]'::jsonb, 'Route 267 (from I-495 northbound or I-95/I-395 northbound)', '["Route 267", "Dulles Toll Road", "Dulles Access Road", "Tysons Corner"]'::jsonb),
    ('i495:1839ND', 'Jones Branch Drive/Route 123', '["Jones Branch Drive", "Route 123", "Tysons Corner"]'::jsonb, 'Jones Branch Drive/Route 123 (from I-95/I-395 southbound)', '["Jones Branch Drive/Route 123", "Jones Branch Drive", "Route 123", "Tysons Corner"]'::jsonb),
    ('i495:183ND', 'Jones Branch Drive/Route 123', '["Jones Branch Drive", "Route 123", "Tysons Corner"]'::jsonb, 'Jones Branch Drive/Route 123 (from I-495 northbound or I-95/I-395 northbound)', '["Jones Branch Drive/Route 123", "Jones Branch Drive", "Route 123", "Tysons Corner"]'::jsonb),
    ('i495:1859ND', 'Westpark Drive', '["Westpark Drive", "Tysons Corner"]'::jsonb, 'Westpark Drive (from I-95/I-395 southbound)', '["Westpark Drive", "Tysons Corner"]'::jsonb),
    ('i495:185ND', 'Westpark Drive', '["Westpark Drive", "Tysons Corner"]'::jsonb, 'Westpark Drive (from I-495 northbound or I-95/I-395 northbound)', '["Westpark Drive", "Tysons Corner"]'::jsonb),
    ('i495:1869ND', 'Route 7 (Leesburg Pike)', '["Route 7", "Leesburg Pike", "Tysons Corner"]'::jsonb, 'Route 7 (Leesburg Pike) (from I-95/I-395 southbound)', '["Route 7 (Leesburg Pike)", "Route 7", "Leesburg Pike", "Tysons Corner"]'::jsonb),
    ('i495:186ND', 'Route 7 (Leesburg Pike)', '["Route 7", "Leesburg Pike", "Tysons Corner"]'::jsonb, 'Route 7 (Leesburg Pike) (from I-495 northbound or I-95/I-395 northbound)', '["Route 7 (Leesburg Pike)", "Route 7", "Leesburg Pike", "Tysons Corner"]'::jsonb),
    ('i495:1879ND', 'Interstate 66', '["I-66", "Idylwood", "Dunn Loring"]'::jsonb, 'Interstate 66 (from I-95/I-395 southbound)', '["Interstate 66", "I-66", "Idylwood", "Dunn Loring"]'::jsonb),
    ('i495:187ND', 'Interstate 66', '["I-66", "Idylwood", "Dunn Loring"]'::jsonb, 'Interstate 66 (from I-495 northbound or I-95/I-395 northbound)', '["Interstate 66", "I-66", "Idylwood", "Dunn Loring"]'::jsonb),
    ('i495:1889ND', 'Lee Highway (Route 29)', '["Lee Highway", "Route 29", "Idylwood", "Merrifield"]'::jsonb, 'Lee Highway (Route 29) (from I-95/I-395 southbound)', '["Lee Highway (Route 29)", "Lee Highway", "Route 29", "Idylwood", "Merrifield"]'::jsonb),
    ('i495:188ND', 'Lee Highway (Route 29)', '["Lee Highway", "Route 29", "Idylwood", "Merrifield"]'::jsonb, 'Lee Highway (Route 29) (from I-495 northbound or I-95/I-395 northbound)', '["Lee Highway (Route 29)", "Lee Highway", "Route 29", "Idylwood", "Merrifield"]'::jsonb),
    ('i495:1919ND', 'I-495 Near Braddock Road', '["Braddock Road", "North Springfield", "Annandale"]'::jsonb, 'I-495 Near Braddock Road (from I-95/I-395 southbound)', '["I-495 Near Braddock Road", "Braddock Road", "North Springfield", "Annandale"]'::jsonb),
    ('i495:191ND', 'I-495 Near Braddock Road', '["Braddock Road", "North Springfield", "Annandale"]'::jsonb, 'I-495 Near Braddock Road (from I-495 northbound or I-95/I-395 northbound)', '["I-495 Near Braddock Road", "Braddock Road", "North Springfield", "Annandale"]'::jsonb),
    ('i95:201SD', 'I-395 Near Edsall Road', '["Edsall Road", "Lincolnia", "Alexandria"]'::jsonb, 'I-395 Near Edsall Road (from I-495 southbound)', '["I-395 Near Edsall Road", "Edsall Road", "Lincolnia", "Alexandria"]'::jsonb),
    ('i95:2229ND', 'Seminary Road', '["Seminary Road", "Alexandria"]'::jsonb, 'Seminary Road (from I-495 southbound)', '["Seminary Road", "Alexandria"]'::jsonb),
    ('i95:222ND', 'Seminary Road', '["Seminary Road", "Alexandria"]'::jsonb, 'Seminary Road (from I-95/I-395 northbound or I-495 northbound)', '["Seminary Road", "Alexandria"]'::jsonb),
    ('i95:22329ND', 'Washington Boulevard/Route 27', '["Washington Boulevard", "Route 27", "Pentagon"]'::jsonb, 'Washington Boulevard/Route 27 (from I-495 southbound)', '["Washington Boulevard/Route 27", "Washington Boulevard", "Route 27", "Pentagon"]'::jsonb),
    ('i95:2232ND', 'Washington Boulevard/Route 27', '["Washington Boulevard", "Route 27", "Pentagon"]'::jsonb, 'Washington Boulevard/Route 27 (from I-95/I-395 northbound or I-495 northbound)', '["Washington Boulevard/Route 27", "Washington Boulevard", "Route 27", "Pentagon"]'::jsonb),
    ('i95:2239ND', 'Pentagon/Eads Street', '["Pentagon", "Pentagon City", "Crystal City", "National Landing"]'::jsonb, 'Pentagon/Eads Street (from I-495 southbound)', '["Pentagon/Eads Street", "Pentagon", "Pentagon City", "Crystal City", "National Landing"]'::jsonb),
    ('i95:223ND', 'Pentagon/Eads Street', '["Pentagon", "Pentagon City", "Crystal City", "National Landing"]'::jsonb, 'Pentagon/Eads Street (from I-95/I-395 northbound or I-495 northbound)', '["Pentagon/Eads Street", "Pentagon", "Pentagon City", "Crystal City", "National Landing"]'::jsonb),
    ('i95:227SD', 'I-395 Near Edsall Road', '["Edsall Road", "Lincolnia", "Alexandria"]'::jsonb, 'I-395 Near Edsall Road (from I-95/I-395 southbound)', '["I-395 Near Edsall Road", "Edsall Road", "Lincolnia", "Alexandria"]'::jsonb);

DO $migration$
DECLARE current_version text;
BEGIN
    SELECT version INTO STRICT current_version FROM oracle.schema_version WHERE singleton;
    IF current_version NOT IN ('1.15.0', '1.15.1') THEN
        RAISE EXCEPTION 'expected oracle 1.15.0 or 1.15.1, got %', current_version;
    END IF;
    IF (SELECT count(*) FROM oracle.toll_route_point) <> 220
       OR (SELECT count(*) FROM oracle.toll_connection) <> 996
       OR (SELECT count(*) FROM oracle.toll_route_point p JOIN approach_labels a USING (point_id)) <> 24
       OR EXISTS (
           SELECT 1 FROM oracle.toll_route_point p JOIN approach_labels a USING (point_id)
           WHERE p.label IS DISTINCT FROM CASE WHEN current_version = '1.15.0' THEN a.old_label ELSE a.new_label END
              OR to_jsonb(p.aliases) IS DISTINCT FROM CASE WHEN current_version = '1.15.0' THEN a.old_aliases ELSE a.new_aliases END
       ) THEN
        RAISE EXCEPTION 'incompatible approach-label predecessor';
    END IF;
END
$migration$;

CREATE TEMP TABLE points_before ON COMMIT DROP AS
SELECT point_id, to_jsonb(p) - 'label' - 'aliases' AS unchanged,
       label, aliases FROM oracle.toll_route_point p;
CREATE TEMP TABLE connections_before ON COMMIT DROP AS
SELECT * FROM oracle.toll_connection;

UPDATE oracle.toll_route_point p
SET label = a.new_label,
    aliases = ARRAY(SELECT jsonb_array_elements_text(a.new_aliases))
FROM approach_labels a
WHERE p.point_id = a.point_id
  AND (SELECT version FROM oracle.schema_version WHERE singleton) = '1.15.0';
UPDATE oracle.schema_version SET version = '1.15.1' WHERE singleton AND version = '1.15.0';

DO $migration$
BEGIN
    IF (SELECT version FROM oracle.schema_version WHERE singleton) IS DISTINCT FROM '1.15.1'
       OR (SELECT count(*) FROM oracle.toll_route_point) <> 220
       OR EXISTS (
           SELECT 1 FROM oracle.toll_route_point p FULL JOIN points_before b USING (point_id)
           LEFT JOIN approach_labels a USING (point_id)
           WHERE to_jsonb(p) - 'label' - 'aliases' IS DISTINCT FROM b.unchanged
              OR p.label IS DISTINCT FROM coalesce(a.new_label, b.label)
              OR to_jsonb(p.aliases) IS DISTINCT FROM coalesce(a.new_aliases, to_jsonb(b.aliases))
       )
       OR EXISTS ((SELECT * FROM oracle.toll_connection EXCEPT SELECT * FROM connections_before)
                  UNION ALL (SELECT * FROM connections_before EXCEPT SELECT * FROM oracle.toll_connection)) THEN
        RAISE EXCEPTION 'approach-label postconditions failed';
    END IF;
END
$migration$;
COMMIT;

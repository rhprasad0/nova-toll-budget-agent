-- loader_writer: RDS IAM auth only (GRANT rds_iam), no password ever set.
-- Run after schema.sql has created the tables and current-price views.

CREATE ROLE loader_writer WITH LOGIN;
GRANT rds_iam TO loader_writer;
GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95, trip_pricing_i66 TO loader_writer;

-- pricing_reader: RDS IAM auth only, SELECT-only. Least-privilege credential
-- for agent_tools/i66_route.py and i95_route.py, which now query RDS for
-- pricing (docs/oracle-tools-spec.md) -- distinct from loader_writer, which
-- also holds INSERT/UPDATE it has no reason to carry into an agent process.
CREATE ROLE pricing_reader WITH LOGIN;
GRANT rds_iam TO pricing_reader;
GRANT SELECT ON trip_pricing_i95, trip_pricing_i66 TO pricing_reader;
GRANT SELECT ON current_trip_pricing_i95, current_trip_pricing_i66 TO pricing_reader;
-- Keep instants UTC-backed in Postgres, but make every agent-facing timestamp
-- use Northern Virginia's DST-aware local time (EST in winter, EDT in summer).
ALTER ROLE pricing_reader SET TimeZone TO 'America/New_York';

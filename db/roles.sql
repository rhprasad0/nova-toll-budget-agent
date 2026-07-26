-- loader_writer: RDS IAM auth only (GRANT rds_iam), no password ever set.
-- Run after schema.sql has created trip_pricing_i95 and trip_pricing_i66.

CREATE ROLE loader_writer WITH LOGIN;
GRANT rds_iam TO loader_writer;
GRANT SELECT, INSERT, UPDATE ON trip_pricing_i95, trip_pricing_i66, trip_pricing_i95_live TO loader_writer;

-- pricing_reader: RDS IAM auth only, SELECT-only. Least-privilege credential
-- for agent_tools/i66_route.py and i95_route.py, which now query RDS for
-- pricing (docs/oracle-tools-spec.md) -- distinct from loader_writer, which
-- also holds INSERT/UPDATE it has no reason to carry into an agent process.
CREATE ROLE pricing_reader WITH LOGIN;
GRANT rds_iam TO pricing_reader;
GRANT SELECT ON trip_pricing_i95, trip_pricing_i66, trip_pricing_i95_live TO pricing_reader;

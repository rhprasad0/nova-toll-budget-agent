-- loader_writer: RDS IAM auth only (GRANT rds_iam), no password ever set.
-- Run after schema.sql has created trip_pricing.

CREATE ROLE loader_writer WITH LOGIN;
GRANT rds_iam TO loader_writer;
GRANT SELECT, INSERT, UPDATE ON trip_pricing TO loader_writer;

-- agent_readonly: the beta agent's execute_sql/route tools. RDS IAM auth
-- only, SELECT only, read-only + 5s timeout enforced at the role level.
CREATE ROLE agent_readonly WITH LOGIN;
GRANT rds_iam TO agent_readonly;
GRANT SELECT ON trip_pricing, graph_node, graph_edge TO agent_readonly;
ALTER ROLE agent_readonly SET default_transaction_read_only = on;
ALTER ROLE agent_readonly SET statement_timeout = '5s';

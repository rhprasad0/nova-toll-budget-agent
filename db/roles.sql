-- loader_writer: RDS IAM auth only (GRANT rds_iam), no password ever set.
-- Run after schema.sql has created trip_pricing.

CREATE ROLE loader_writer WITH LOGIN;
GRANT rds_iam TO loader_writer;
GRANT SELECT, INSERT, UPDATE ON trip_pricing TO loader_writer;

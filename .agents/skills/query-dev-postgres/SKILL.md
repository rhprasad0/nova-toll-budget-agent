---
name: query-dev-postgres
description: Query TollChat's deployed development PostgreSQL database for bounded, read-only diagnostics through the existing local Tailscale and AWS IAM path. Use for questions that require current development data; do not use for production, writes, migrations, or disposable database tests.
---

# Query development PostgreSQL

Turn the user's question into one small SQL query, run it against the fixed
development database, and summarize the result. A request to use this skill
authorizes the read-only query needed to answer it, not any database or
infrastructure mutation.

## Fixed boundary

- AWS account: `903859731897`
- Region: `us-east-1`
- AWS CLI profile: `nova-toll-dev`
- RDS instance: `nova-toll-db`
- Database: `nova_toll_development`
- Database role: `pricing_reader_development`
- Transport: the owner's existing local Tailscale site-1 route

Never substitute production, an administrator or migration role, a password
from Secrets Manager or SSM, another database, or another account. Stop if the
local AWS identity lacks `rds:DescribeDBInstances` or `rds-db:connect` for the
fixed reader role; changing IAM is outside this skill.

## Build the query

Inspect the checked-in schema, migrations, and callers needed to confirm names
and semantics before querying. Treat the database as verification of current
data, not as a substitute for understanding the repository contract.

Use only one diagnostic `SELECT`, read-only `WITH`, or non-executing `EXPLAIN`
of a `SELECT`. Do not use:

- DML, DDL, `COPY`, `CALL`, `DO`, transaction control, session-level `SET`, or
  `EXPLAIN ANALYZE`;
- data-modifying CTEs;
- user-defined functions unless the checked-in definition proves them
  `STABLE` or `IMMUTABLE` and appropriate for the question.

Name columns instead of using `SELECT *`. Add `LIMIT 100` to row-returning
diagnostics unless the query already returns one aggregate row. Add a stable
`ORDER BY` when row order affects the answer. Do not fetch unrelated columns or
rows.

## Connect

Before every query, read the `Verify development route, identity, and
production denial` step in
`.github/workflows/v2-development-connectivity-verification.yml`. Reuse its
current commands for all of the following rather than copying connection logic
into this skill:

1. Require `aws`, `psql`, `tailscale`, `jq`, `curl`, `sha256sum`, `timeout`, and
   Python. Confirm Tailscale is connected.
2. Set `AWS_PROFILE=nova-toll-dev` for every AWS CLI command. Run
   `aws sts get-caller-identity` and require account `903859731897`.
3. Describe only `nova-toll-db`; require one available, private PostgreSQL
   instance and the workflow's development endpoint pattern.
4. Resolve exactly one private IPv4 address and derive its site-1 4via6 address
   with `tailscale debug via 1` and the workflow's `ipaddress` validation. Keep
   the RDS DNS name in `PGHOST` and put only the derived address in
   `PGHOSTADDR`.
5. Use the workflow's pinned RDS CA URL and SHA-256 validation in a temporary
   directory. Set `PGSSLMODE=verify-full`, `PGPORT=5432`,
   `PGDATABASE=nova_toll_development`, and `PGUSER=pricing_reader_development`.
6. Generate a short-lived IAM token with `aws rds generate-db-auth-token` for
   that exact host and user.

Keep shell tracing disabled. Do not print the token, endpoint metadata, route
diagnostics, or environment. Put the token only in `PGPASSWORD` for the single
`psql` process, unset token variables on success or failure, and remove the
temporary CA directory with a trap.

## Execute once

Run `psql` with `-X`, `ON_ERROR_STOP=1`, and an outer `timeout` of 25 seconds.
Wrap the approved query in this transaction; replace only the comment:

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
SET LOCAL idle_in_transaction_session_timeout = '20s';
-- one approved query
ROLLBACK;
```

Capture only the bounded query result needed for the answer. Do not retry a
failed statement automatically. On any identity, target, route, TLS,
authorization, timeout, or SQL error, stop and report the failed boundary
without exposing command output that may contain connection details.

## Report

State the SQL that ran, summarize the result, and distinguish observed rows
from interpretation. Mention the UTC retrieval time and any limiting filter or
row cap. Do not save query text, results, credentials, or connection metadata
to repository files.

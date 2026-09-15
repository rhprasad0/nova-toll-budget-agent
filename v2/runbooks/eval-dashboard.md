# Scheduled evaluation dashboard

The public route is `/eval-dashboard` in both environments. Development publishes
first; production activation and release remain separate work.

The timed-check Lambda records each scheduled occurrence in
`pricing.evaluation_runs`, then publishes `evals.json` to the existing site bucket
at start and completion. The browser reads that snapshot every minute while
visible. It never connects to Postgres or invokes an agent.

The snapshot contains seven days of runs, the latest result for each of the six
scenarios, and scheduled occurrences calculated in America/New_York. Failed
grades, execution errors, late arrivals, and missing completions are distinct.
A result is overdue after the existing ten-minute delivery allowance plus the
fifteen-minute Lambda timeout. Only completed graded runs enter the pass rate.
Duplicate deliveries do not invoke models again. A refresh failure retains the
last received snapshot with a warning; an absent or wrong-environment snapshot
shows no scores. There is no sample fallback or historical backfill.

Evidence includes the actual simulated user/assistant turns, allowlisted pricing
arguments/results, and each judge's explanation. Storage keys and internal error
diagnostics are omitted; common credential and infrastructure identifiers are
redacted from text. The source is this controlled synthetic suite, never real
user chat sessions. Postgres retains history; the public window is seven days.

## Development delivery order

1. Land the fixed dashboard site/release inventory prerequisite (#519).
2. Provision the `eval_writer_development` IAM database login with the fixed SQL
   below, using the existing development administrator connection. Do not run
   migration 033 as administrator. The protected schema migrator cannot create
   roles and must retain that restriction.
3. Save and inspect a private development Terraform plan targeting only
   `aws_iam_role_policy.timed_checks_lambda` and
   `aws_lambda_function.timed_checks`, using the **currently deployed packages**.
   Only the three dashboard IAM statements and two additional environment
   variables may change. Reject package changes, dependency-expanded mutations,
   deletes, replacements, production resources, or removed environment values.
   Apply that exact reviewed plan. The old handler ignores these new variables.
4. Merge the application PR after CI and human review. The protected development
   delivery sequence validates its saved plan, applies registered migration 033
   under the fixed migrator identity, re-assumes delivery, and applies that plan.
   Ordinary delivery permissions and finite plan guards are unchanged.
5. Verify pricing schema 1.4.0, the writer's table-only permissions, and
   `/eval-dashboard`. The first real scheduled invocation creates `evals.json`;
   until then the page correctly shows no results. Inspect its environment,
   occurrence timestamp, three verdicts, conversation, and tool evidence.

Production remains capped at migration 032. A future reviewed production release
must explicitly authorize migration 033 and provision its own writer and snapshot
publication permissions before activation. Development data is never copied there.

### Fixed development role prerequisite

Run only against `nova_toll_development` in development account `903859731897`,
after verifying the existing administrator connection and TLS target.

```sql
BEGIN;
DO $$ BEGIN
  IF current_database() <> 'nova_toll_development'
     OR shobj_description((SELECT oid FROM pg_database
                          WHERE datname = current_database()), 'pg_database')
        IS DISTINCT FROM 'environment=development' THEN
    RAISE EXCEPTION 'wrong evaluation writer bootstrap target';
  END IF;
END $$;
CREATE ROLE eval_writer_development LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;
COMMENT ON ROLE eval_writer_development IS 'environment=development';
GRANT rds_iam TO eval_writer_development;
GRANT CONNECT ON DATABASE nova_toll_development TO eval_writer_development;
COMMIT;
```

Migration 033 grants schema usage and SELECT/INSERT/UPDATE on the single new
table. The writer cannot delete history or read/write pricing tables. No role
creation or arbitrary SQL is added to the protected delivery workflow.

## Local checks

Run the focused Python eval/handler tests and the disposable database suite.
With Playwright available, run `node v2/tests/eval_dashboard_browser.cjs` for
snapshot rendering, refresh failure, environment isolation, safe text, keyboard
disclosures, missing runs, empty state, and mobile layout. The browser test's
synthetic inputs are test-only and are never part of the published site.

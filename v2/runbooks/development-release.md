### Development application release and database validation (#331)

This is the only operative #331 release procedure. It uses only the development
account and the two development state backends. The typed, non-secret foundation
output is consumed ephemerally from the #330 development foundation state. The
manual bootstrap/import creates or inventories the CloudFront distribution with
no aliases and the CloudFront default certificate. Recurring plans consume that
existing distribution and its d*.cloudfront.net hostname; they never create or
delete the distribution. Slice 3 custom-domain staging is an administrator-owned
development apply plus the separately trusted production-foundation DNS gate
below; recurring delivery remains explicitly disabled for that input.

When direct workstation access to the private RDS endpoint is unavailable, an
already-authorized development private path may forward the endpoint to a local
port. Set `NOVA_TOLL_RDS_LOCAL_PORT` to that port before this procedure; the
procedure keeps `PGHOST` set to the RDS endpoint so TLS hostname verification
still applies and uses only `127.0.0.1` as the transport address. Local
forwarding requires `NOVA_TOLL_EXPECTED_RDS_ENDPOINT` to match the real RDS
hostname and `NOVA_TOLL_ADMIN_URL` to carry explicit nonempty
`sslmode=verify-full` and `sslrootcert` settings. Ambient `PG*` values never
rescue a missing, mismatched, or downgraded URL setting; any such input stops
before `psql`.

The authorized replacement may initialize only the Terraform-created
`nova_toll_development` database after the protected route and saved-plan steps
complete. If that exact database is absent, non-empty, ambiguous, or already
bootstrapped, stop; do not run the fresh mode and do not use a versioned
migration. The bounded procedure is documented in the development foundation
replacement handoff below.

Keep the terminal non-traced. The development RDS-managed Secrets Manager JSON and
its extracted username/password exist only in process memory and are never
printed, placed in an argument, written to a file, put in Terraform input/state/
plan, or recorded in evidence.

#### Slice 2A development 4via6 policy handoff and allocation gate

The overlapping development VPC input is `172.31.0.0/16`. Tailscale site ID `1`
derives the stable development route
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112`. The current development RDS endpoint
`nova-toll-db.cc3usg2wmx63.us-east-1.rds.amazonaws.com` resolved to
`172.31.4.167`, whose site-1 transport host is
`fd7a:115c:a1e0:b1a:0:1:ac1f:4a7/128`. Re-resolve the endpoint and regenerate
that host immediately before Slice 2B activation; this address is a current
policy-test fixture, not a permanent DNS record. The later TLS connection keeps
the RDS DNS name in `PGHOST` for hostname verification and uses the 4via6 host
only as `PGHOSTADDR`. Confirm both derivations with
`tailscale debug via 1 172.31.0.0/16` and
`tailscale debug via 1 172.31.4.167/32` before handoff.

Before any protected connectivity verification, create a separate protected
route-control OAuth client with only the documented device-inventory read scope
`devices:core:read`, route-read scope `devices:routes:read`, and route-management
scope `devices:routes`. The existing
`TS_DEVELOPMENT_OAUTH_CLIENT_ID` and `TS_DEVELOPMENT_OAUTH_SECRET` client remains
`auth_keys`-only for the third-party `tailscale/github-action`; its values stay
opaque to operators, logs, arguments, artifacts, and summaries. The route
helper uses only `TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID` and
`TS_DEVELOPMENT_ROUTE_OAUTH_SECRET`. Do not use a personal API token, an ACL
OAuth client, or a legacy device identifier.
The helper requests exactly the space-delimited scope string
`devices:core:read devices:routes:read devices:routes` and rejects a token
response with missing, duplicated, insufficient, or additional scope tokens.

The protected `workflow_dispatch` run is the sole route-control boundary. It
must run from `refs/heads/main` and keep `DEVELOPMENT_DELIVERY_ENABLED` absent
or false. The reviewer-free `development` environment does not authorize this
operation; its safety comes from the explicit dispatch, main-ref, and owner-ID
checks. The foundation
Terraform root creates and maintains the separate
`nova-toll-v2-route-control-dev` role; the workflow assumes that
administrator-controlled role first. It sends exactly one fixed, no-parameter
custom SSM document named
`nova-toll-v2-route-control-status-dev` to instance `i-0d33b9a9c15db93fc` in
`us-east-1`. The document contains only `set -eu` and `tailscale status --json`,
then the helper reads only that command's status and output. The command
document is not `AWS-RunShellScript`, and callers cannot provide commands.
The command must be successful, have response code `0`, empty stderr, and one
JSON document with a nonempty `Self.ID`. The helper
`v2/scripts/approve_development_tailscale_route.py` never prints that private
output or the OAuth bearer.

The helper exchanges the route-control secrets in memory, requests the canonical
`GET /api/v2/tailnet/rhprasad0.github/devices` device list, and rejects any
pagination/continuation marker, malformed field, or duplicate `nodeId`. For
every listed device, it then requests exactly one
`GET /api/v2/device/<nodeId>/routes` using that device's preferred, quoted
`nodeId`. It merges only the list-owned identity, tags, and
`connectedToControl` fields with the two route arrays returned by that matching
route read; list-supplied route fields are not trusted. Only after every device
has been enriched does it reject duplicate route, noncanonical route, IPv4 on
the bound device, foreign or ambiguous site-1 4via6 route, collision, or tag
ambiguity. It selects exactly the API `nodeId` equal to SSM `Self.ID`; that
device must have exactly `tag:nova-toll-development-router`, and the exact
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112` must already be advertised there. If the
route is not yet advertised, stop and use the reviewed exact-instance SSM
advertisement procedure below.

Immediately before a write, the helper re-fetches the canonical list and every
device's route response, then revalidates the complete enriched inventory. If
the exact route is already enabled, it succeeds without a POST. Otherwise it
sends exactly one
`POST /api/v2/device/<nodeId>/routes` containing the complete current
`enabledRoutes` list plus the exact route, preserving every unrelated entry.
The API scope must include `devices:routes:read` for route GETs and
`devices:routes` for the replacement POST; a 401/403, timeout, invalid
response, or uncertain write is a hard failure and is never retried. A
successful write is followed by a complete enriched inventory read proving the same
SSM/API node binding, sole tag ownership, no intended-device IPv4, and both
advertised/enabled exact-route state. The API has no conditional version, so the
list-plus-per-device route reads are not an atomic snapshot and retain an
irreducible multi-GET sub-request TOCTOU window; drift is rejected before POST
and the exact post-write readback is mandatory. Only the sanitized
identity/route booleans are recorded as evidence.

Any SSM, OAuth, inventory, identity, ownership, route, POST, or post-read
failure stops before the DB role is assumed. Do not guess a device, accept a
partial list, use an alternate credential, or continue to TLS/SQL checks.

After the diagnostic source change is merged, inspect the unknown route state
with the protected workflow's manual `route-diagnostic` phase before any
approval attempt:

```sh
gh workflow run v2-development-connectivity-verification.yml \
  --ref main --field phase=route-diagnostic
```

Run this `development`-environment phase only through the protected workflow
dispatch. This phase skips the Tailscale auth-key action, timed-checks role,
route approval, transport, and SQL steps; it assumes only the fixed
route-control role and records only the sanitized JSON summary. Keep the
delivery gate unchanged. A
non-success stage, missing/foreign route state, or any indication that the
earlier run reached a POST remains a hard stop for human review.

#### Slice 2B development router and protected connectivity handoff

This section is a post-merge operator procedure. The builder and deterministic
tests do not create credentials, enroll the existing instance, advertise a
route, apply the policy, change GitHub settings, or connect to PostgreSQL.
The only live router target is development account `903859731897`, instance
`i-0d33b9a9c15db93fc`, in `us-east-1`; never substitute a name, public address,
or a production instance. The development route is exactly
`fd7a:115c:a1e0:b1a:0:1:ac1f:0/112`. No VPC route, IPv4 route, exit node, SG,
peering, public RDS setting, or production route is part of this handoff.

##### Policy and one-off router key

1. In **Tailscale Admin Console → Access controls → Policy file**, confirm the
   merged protected-main GitOps policy is applied. Do not edit the policy in
   the console after that confirmation.
2. In **Keys → Generate auth key**, create one key with a description such as
   `nova-toll development router`, **one-off**, **non-ephemeral**,
   **pre-approved** when device approval is enabled, a short expiry of at most
   90 days, and **only** the tag
   `tag:nova-toll-development-router`. Generate it and copy it once into a
   secure prompt. Do not create a reusable key, add a second tag, or retain the
   plaintext.
3. In the development AWS account, keep the terminal non-traced (`set +x`),
   set `AWS_REGION=us-east-1` and `AWS_DEFAULT_REGION=us-east-1`, and verify
   `aws sts get-caller-identity` reports `903859731897`. Read the copied key
   only into process memory and pipe the request body to AWS CLI stdin; the key
   is never a command argument, output, file, Terraform input/state, GitHub
   secret, log, or evidence field:

   ```sh
   set +x
   umask 077
   export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
   test "$(aws sts get-caller-identity --query Account --output text)" = "903859731897"
   read -r -s ROUTER_KEY
   printf '{"Name":"/nova-toll/tailscale-authkey","Type":"SecureString","Value":"%s","Overwrite":true}\n' "$ROUTER_KEY" |
     aws --region us-east-1 ssm put-parameter --cli-input-json file:///dev/stdin >/dev/null
   unset ROUTER_KEY
   aws --region us-east-1 ssm describe-parameters \
     --parameter-filters 'Key=Name,Option=Equals,Values=/nova-toll/tailscale-authkey' \
     --query 'Parameters[0].{Name:Name,Type:Type,Version:Version}' --output json
   ```

   The metadata check must show only the expected name, `SecureString`, and a
   version. Never use `get-parameter --with-decryption` on the operator host.

##### Existing-instance enrollment and route allocation

Use only SSM Run Command against `i-0d33b9a9c15db93fc`; do not open SSH or
enroll a replacement. This command decrypts the temporary key in the remote
process, disables tracing before the key is read, joins with Tailscale SSH, and
advertises no route:

```sh
set +x
INSTANCE_ID=i-0d33b9a9c15db93fc
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
test "$(aws sts get-caller-identity --query Account --output text)" = 903859731897
COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","KEY=$(aws --region us-east-1 ssm get-parameter --name /nova-toll/tailscale-authkey --with-decryption --query Parameter.Value --output text)","tailscale up --authkey=\"$KEY\" --ssh","unset KEY"]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query Status --output text)" = Success
```

After enrollment, do not select the device by hostname, address, or the
legacy device identifier. The protected workflow obtains the local
Tailscale node ID from the exact instance's SSM `Self.ID` and binds that
value to exactly one API `nodeId` with exactly the router tag.

In the existing development account, advertise the route only through the
reviewed exact-instance SSM command below. This changes advertisement only;
it does not approve an enabled route:

```sh
set +x
INSTANCE_ID=i-0d33b9a9c15db93fc
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids i-0d33b9a9c15db93fc \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","tailscale set --advertise-routes=fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$COMMAND_ID" --instance-id i-0d33b9a9c15db93fc
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id i-0d33b9a9c15db93fc --query Status --output text)" = Success
```

Immediately dispatch the protected connectivity workflow from the reviewed
`main` SHA with `phase=pre-bootstrap`. Its route-control step passes only when
the complete canonical list plus every per-device route read has the exact route in both
`advertisedRoutes` and `enabledRoutes`; canonical unrelated-device `::/0` is
the sole broad-route exception, while the exact site-1 route remains owned only
by the exact SSM/API-bound device. Its pre-bootstrap phase then proves that the
derived site-1 host uses
`tailscale0` and accepts a bounded TCP/5432 connection, without assuming the
database role that fresh bootstrap has not created yet. It rejects partial or
marked inventories, duplicate or malformed data, IPv4 on the bound device,
foreign or ambiguous site-1 routes, collisions, tag drift, scope failure, and
any uncertain API result before the transport check. The workflow records only
its sanitized route/transport summary; this phase is not the full SQL proof.

Dispatch it only from protected `main`, and keep
`DEVELOPMENT_DELIVERY_ENABLED` absent or false:

```sh
gh workflow run v2-development-connectivity-verification.yml \
  --repo rhprasad0/nova-toll-budget-agent --ref main -f phase=pre-bootstrap
```

If route approval or post-write proof fails, stop before TLS or SQL. Never
retry an uncertain POST. With the still-proven exact node binding, restore
the complete pre-write `enabledRoutes` list in one bounded replacement POST,
preserving every unrelated entry; never replace it with a guessed single
route. Then remove only the development advertisement through the exact
instance SSM command below and prove that no site-1 route remains before any
retry. If identity, command status, route state, or the pre-write list is
uncertain, stop for human review and do not guess a rollback target.

The remote rollback command is exactly `tailscale set --advertise-routes=""`:

```sh
set +x
test "$INSTANCE_ID" = i-0d33b9a9c15db93fc
DISABLE_COMMAND_ID="$(aws --region us-east-1 ssm send-command \
  --instance-ids i-0d33b9a9c15db93fc \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["set +x","set -eu","tailscale set --advertise-routes=\"\""]' \
  --query Command.CommandId --output text)"
aws --region us-east-1 ssm wait command_executed --command-id "$DISABLE_COMMAND_ID" --instance-id i-0d33b9a9c15db93fc
test "$(aws --region us-east-1 ssm get-command-invocation --command-id "$DISABLE_COMMAND_ID" --instance-id i-0d33b9a9c15db93fc --query Status --output text)" = Success
```

The final enriched inventory proof must complete all list and per-device route
reads and show no site-1 route in `advertisedRoutes`; an uncertain SSM/API
response remains a hard stop. No failure or rollback path changes production.
##### Manual development TLS/query verification

The separate
`.github/workflows/v2-development-connectivity-verification.yml` is the sole
pre-enable CI proof. It is `workflow_dispatch` only, must be dispatched from
`refs/heads/main` while `DEVELOPMENT_DELIVERY_ENABLED` is absent or `false`,
and accepts `phase=pre-bootstrap` for the route/transport proof above or
`phase=full` for the post-bootstrap SQL and production-denial proof. The
workflow uses the protected `development` environment and has only
`contents: read`/`id-token: write`. Its Tailscale OAuth client has only the
`auth_keys` scope and only `tag:ci-development`; its only AWS role is
`arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-dev`. It has no
delivery, Terraform, apply, package, write-capable AWS, production secret,
production route, or production SQL path.

Before dispatch, an AWS development-account administrator must confirm that
the timed-check role trust retains audience `sts.amazonaws.com` and, for the
development deployment, includes exactly the development environment subject
`repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development`.
The `development` branch of the IaC condition must not admit the
protected-main branch subject; the secret-bearing connectivity role is usable
only by the protected `development` environment. The production foundation
variant retains only the protected-main branch subject.
The IaC trust in `v2/infra/main.tf` is the source of truth. The role policy is
limited to development `rds:DescribeDBInstances`, development
`rds-db:connect` as `pricing_caller_development`, and its pre-existing
OpenAI-parameter read; it has no deployment, Terraform, SSM write, Secrets
Manager, or production resource permission.

The verifier resolves the development RDS endpoint with
`aws rds describe-db-instances` and native `getent ahostsv4`, immediately
derives the site-1 `/128` with `tailscale debug via 1 <ipv4>/32` and Python's
standard-library `ipaddress`, and rejects a stale or non-site-1 result. The
`pre-bootstrap` phase stops after validating the `tailscale0` route and a
bounded TCP/5432 connection to the derived host, so it does not require
`pricing_caller_development`. Run the `full` phase only after fresh bootstrap;
it keeps the refreshed RDS DNS name in `PGHOST` and for IAM-token generation,
puts only the derived IPv6 address in `PGHOSTADDR`, uses the pinned RDS CA with
`PGSSLMODE=verify-full`, and runs one bounded query only:
`SELECT current_database(), current_user`. The expected result is exactly
`nova_toll_development` and `pricing_caller_development`; no query rows,
password, IAM token, OAuth value, or raw command output is evidence.

For the production boundary, the verifier proves the caller is account
`903859731897` and role `nova-toll-v2-timed-checks-dev`, resolves only the
documented production endpoint as needed for a route check, and uses the Linux
JSON route decision to assert that the production address is not selected
through `tailscale0`. (`tailscale debug via` only derives 4via6 addresses; it is
not a route probe.) It then makes one short TCP/5432 socket attempt with no
production credentials and no SQL. A successful connection or unexpected local
error fails the run; bounded refusal, timeout, host/network-unreachable, or
permission-denied results prove socket denial. It never calls a production RDS
API. The existing development database contract remains the source for both
development-to-production and production-to-development cross-database denial;
no deployed schema or role change is allowed.

The verifier writes one sanitized commit/run-bound summary containing only
`commit_sha`, `run_id`, `run_attempt`, `ref`, development account/role,
expected route, transport-validation boolean, query identity/database, and
explicit production-route/socket denial booleans. Record that summary with the
policy success, exact route ownership and enablement, development TLS/query,
both production-boundary denials, and the delivery-role bootstrap/simulated
GitHub-main OIDC proof before enabling delivery.

##### Protected activation and rollback

In **GitHub repository Settings → Environments → development**, retain its
`main` branch policy and keep the environment reviewer-free before adding any
environment secret. In **Tailscale Admin Console → Settings → OAuth
clients → Generate OAuth client**, retain the existing client described as
`nova-toll development CI` with scope `auth_keys` only and tag only
`tag:ci-development`. Copy it once into the protected environment as exactly
`TS_DEVELOPMENT_OAUTH_CLIENT_ID` and `TS_DEVELOPMENT_OAUTH_SECRET`; these names
remain exclusively for the third-party action. Create a second client for the
route helper with only `devices:core:read`, `devices:routes:read`, and
`devices:routes` (no `all`, ACL, or other scopes), and copy it as exactly
`TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID` and
`TS_DEVELOPMENT_ROUTE_OAUTH_SECRET`. Keep both values opaque. Do not replace
repository production `TS_OAUTH_*` or policy `TS_ACL_OAUTH_*` secrets.

The delivery workflow's build job remains harmless without AWS OIDC. Its
development deploy job has the job-level false-closed condition
`vars.DEVELOPMENT_DELIVERY_ENABLED == 'true'`, evaluated before the job declares
its protected environment or requests OIDC. GitHub environment variables are
not available at that point, so this must be a **repository variable**. Keep it
absent (or literal `false`) through policy, key, router, route, role, OAuth, and
manual-verification setup. After every evidence item passes and the manual
workflow succeeds on `main`, an authorized operator may set it in **Settings →
Secrets and variables → Actions → Variables → New repository variable** with
name `DEVELOPMENT_DELIVERY_ENABLED` and value `true`, then save it. This
variable only enables the existing post-merge application delivery job; it does
not bypass the explicit `workflow_dispatch`/`refs/heads/main` boundaries for
route control, connectivity verification, or migrations.
The equivalent operator-only CLI activation is:

```sh
gh variable set DEVELOPMENT_DELIVERY_ENABLED --body true \
  --repo rhprasad0/nova-toll-budget-agent
```

Rollback is ordered and false-first: delete that exact repository variable or
set it to literal `false`, confirm a later delivery run is skipped without an
OIDC request, then disable and recheck the development route. Only after that
may the operator revoke the development CI OAuth client if needed and close the
router-key lifecycle. The equivalent rollback CLI call is
`gh variable delete DEVELOPMENT_DELIVERY_ENABLED --repo rhprasad0/nova-toll-budget-agent`.
No rollback action mutates production.

#### Slice 3 development custom-domain and DNS handoff

This is a bounded, post-merge operator procedure. The application state remains
in development account `903859731897`, region `us-east-1`, backend
`v2/infra/backend.development.hcl`, and distribution `E33DVF3KT7BTAC` with
hostname `d1wqry4fbd92w5.cloudfront.net` (all are re-read and checked immediately
before use). The foundation DNS workflow runs in production account
`920534282028` only to read the exact SSM parameter
`arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-development-dns-api-token`.
It has no application, state, CloudFront, ACM, or cross-account AWS access.
The token is read into the workflow process only, never printed, passed to
development, put in Terraform input/state, or retained in an artifact.

The Terraform switch `enable_development_custom_domain` defaults to `false`.
After certificate staging, recurring `development.tfvars` records `true` and
the development delivery workflow preserves that setting. With it false, the development distribution has no aliases,
uses the CloudFront default certificate and `TLSv1`, and has no development ACM
resource. Production keeps its existing certificate, aliases, validation records,
resource addresses, and Cloudflare provider path. Certificate creation and
CloudFront alias/certificate changes remain administrator-owned. The recurring
role can only describe and read tags of the exact staged development
certificate; its scoped development IAM policy does not permit certificate
creation, updates, deletion, or CloudFront alias/certificate changes. It
cannot request ACM certificates or update CloudFront aliases/certificates.

##### Protected environment and preflight

1. Start from a clean, protected `origin/main` checkout. Retain the successful
   automatic delivery, development health/connectivity, and Slice 2 route/TLS/query
   evidence. Set `DEVELOPMENT_DELIVERY_ENABLED=false` during administrator staging
   and cutover. Restore it only after the issued certificate, alias, DNS and health
   checks pass and an ordinary recurring plan contains no administrator-owned
   changes. Keep the development environment's secrets and main-only branch
   restriction unchanged. The DNS workflow must be dispatched
   only from `refs/heads/main` with the protected GitHub environment named exactly
   `production-foundation-dns`; its required reviewer must approve the run.
2. In the production foundation state, apply the reviewed role only after the
   plan shows `nova-toll-production-foundation-dns` and exactly one policy action:
   `ssm:GetParameter` on the exact parameter ARN above. Confirm its trust uses
   only the GitHub OIDC provider, `aud=sts.amazonaws.com`, and the immutable
   subject
   `repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production-foundation-dns`.
   There is no branch wildcard, pull-request subject, development role, state
   bucket, KMS, Secrets Manager, or application permission.
3. In **Settings → Environments**, create the protected environment
   `production-foundation-dns` with a required owner/admin reviewer and a `main`
   branch policy. Do not add a Cloudflare secret to GitHub. The workflow obtains
   the token only through the production role's SSM read. Check the action SHAs
   and the exact `role-to-assume` before dispatch.
4. Read current state without mutating it. Record sanitized evidence for the
   `dev.tollchat.ai`, apex `tollchat.ai`, and `www.tollchat.ai` records, including
   IDs, names, types, values, TTLs, and proxy flags. Record production CloudFront
   and ACM health as read-only evidence. The known rollback baseline is exactly
   one unproxied CNAME `dev.tollchat.ai` →
   `dmsiz11apblcv.cloudfront.net`; treat that value as a checked live input, not
   permission to touch any other record. Apex and `www` IDs/content are immutable
   checksums for the remainder of the handoff.

##### Certificate staging in the development account

1. From the development account, first confirm the caller is
   `903859731897`, the backend is `v2/infra/backend.development.hcl`, and the
   distribution is the exact `E33DVF3KT7BTAC`. Resolve the foundation output
   ephemerally as the existing delivery workflow does; never read production
   state. Keep the terminal non-traced (`set +x`) and use a private temporary
   directory for plans.
2. Save and review a targeted administrator plan with
   `enable_development_custom_domain=true` to request only the ACM certificate
   first. The certificate must be exactly `dev.tollchat.ai`, DNS validated, and
   in `us-east-1`; do not attach an alias before validation. A representative
   command is:

   ```sh
   set -euo pipefail
   set +x
   terraform -chdir=v2/infra init -input=false -backend-config=backend.development.hcl
   terraform -chdir=v2/infra plan -input=false \
     -out=/private/reviewed/development-certificate.tfplan \
     -var-file=development.tfvars \
     -var enable_development_custom_domain=true \
     -target=aws_acm_certificate.site[0] \
     -var-file=/private/reviewed/development-foundation.tfvars.json
   ```

   Require exactly one create, `aws_acm_certificate.site[0]`, for `dev.tollchat.ai`
   in development `us-east-1`, DNS validation, and the existing project,
   environment=development and version=v2 tags. Apply only that reviewed saved
   plan. The target is a staging convenience only; review the complete follow-up
   plan. Do not apply if it proposes a production backend/account, Cloudflare
   data/resource, Route 53 object, or any production address. Capture only the
   non-secret outputs:

   ```sh
   set +x
   terraform -chdir=v2/infra output -json development_acm_certificate_arn
   terraform -chdir=v2/infra output -json development_acm_validation_records
   ```

   The output must contain exactly one certificate ARN for account
   `903859731897` in `us-east-1`, and exactly the current ACM DVO name/value for
   `dev.tollchat.ai`. Pass those records to the protected DNS workflow as JSON;
   do not copy a token or a plan/state object across accounts.
3. The certificate output is not an issuance proof. In the development account,
   poll the certificate with a bounded 10-minute wait (for example, 30 checks
   at 20-second intervals) and stop on any status other than `ISSUED`. The DNS
   workflow must first create/verify only the exact unproxied CNAME DVO records
   with type `CNAME` and TTL `60`. It resolves exactly one active `tollchat.ai`
   zone through the authenticated API, derives its account and zone IDs in
   memory, calls `GET /accounts/{derived_account_id}/tokens/verify`, and
   requires a successful active account-owned token. Zero, multiple, paginated,
   inactive, wrong-account, malformed, or API-error results stop before a write.

##### Exact DNS workflow operations and ordering

Dispatch `.github/workflows/v2-production-foundation-dns.yml` from protected
`main` with `operation=stage-validation`, the non-secret certificate ARN, the
   JSON `development_acm_validation_records` value, distribution ID
`E33DVF3KT7BTAC`, deployed hostname `d1wqry4fbd92w5.cloudfront.net`, and the
captured old target/snapshot. The workflow rejects any record except exactly
one ACM-looking `_...dev.tollchat.ai` CNAME with the expected ACM
`_...acm-validations.aws` value, TTL `60`, and `proxied=false`. It refuses
duplicates, wrong type/content/TTL/proxy, arbitrary underscore names, wildcard,
apex, `www`, production names, and any broad reconciliation. Existing matching
records are left unchanged; a missing record is the only validation create.
All inputs and all current records are checked before the first write, and each
write re-verifies the token. The workflow uses only GET/POST/PUT; it has no
record deletion or proxy-mode path, and all API failures are sanitized.

After validation records are verified, wait for ACM `ISSUED` in the development
account. Prepare and review the administrator's enabled development application
plan before moving traffic, but do not attach the new alias yet. CloudFront
checks the existing DNS target and can reject attachment with
`CNAMEAlreadyExists` while DNS still points to the old distribution, even after
its alias was removed. This handoff therefore uses **DNS before alias
attachment**, accepting temporary downtime; see the AWS
[incorrectly configured DNS record guidance](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/troubleshooting-distributions.html#troubleshooting-distributions-dns-errors).

First release only `dev.tollchat.ai` from legacy distribution `E1JXKQYNAN39E4`.
In account `920534282028`, require its expected hostname, `Deployed` status, and
sole alias; capture the complete `GetDistributionConfig` response and ETag.
Change only `Aliases` to `{"Quantity":0}`, prove every other field is identical,
then use `UpdateDistribution` with that complete payload and fresh `IfMatch`.
Wait for `Deployed` and verify zero aliases and unchanged non-alias configuration.
Keep the old certificate, origins, distribution, and captured configuration.
Do not apply the production Terraform root or delete any legacy resource.

Before `operation=cutover`, immediately re-read the dev record and compare it
to the supplied snapshot: one record ID, exact name/type, old content
`dmsiz11apblcv.cloudfront.net`, TTL `1`, and `proxied=false`. The workflow also
rechecks every validation record and requires operator evidence
`certificate_status=ISSUED`, `cloudfront_status=Deployed`, and
`legacy_alias_released=true`. The development distribution must be the exact
staged target; its new alias need not be attached yet. Never supply guessed or
stale evidence or bypass the protected environment reviewer. The workflow
updates only the captured dev record ID to the
validated development hostname and verifies the same ID/content after the
write. It never touches apex, `www`, production CloudFront/ACM, the old
distribution `E1JXKQYNAN39E4`, or validation records. Verify DNS resolves to
`d1wqry4fbd92w5.cloudfront.net` before applying the reviewed development alias
plan. The new alias must be exactly `dev.tollchat.ai`, with the issued
certificate, `sni-only`, and `TLSv1.2_2021`; `local.public_site_url`,
`PUBLIC_ORIGINS`, and `PUBLIC_BASE_URL` must become exactly
`https://dev.tollchat.ai`. `public_preview_hostname` cannot override this URL.
If a bounded native CloudFront-target stage is needed to resolve downstream
policy-document values, review every included dependency update and apply
only the saved plan, then review and apply the full application follow-up.
Never apply unknown IAM/KMS policy values or reuse a partially applied plan.
Wait for the exact new distribution to report `Deployed` with a bounded
30-minute wait (30 checks at 60 seconds), and independently verify its alias
and certificate. Allow up to 15 minutes for DNS propagation; a successful DNS
workflow alone is not proof of a healthy cutover.

Run read-only smoke checks after propagation: HTTPS must present a certificate
for `dev.tollchat.ai`, the page and `/api/config` must return successfully, the
`X-Robots-Tag: noindex` header must remain, and the response/API identity must
be the development account/origin. Re-read apex and `www` and assert their
record IDs/content are byte-for-byte unchanged. Recheck production CloudFront
and ACM health and retain the sanitized before/after evidence with the commit,
workflow run, and operator identities.

##### Failed-cutover recovery and cleanup gate

Keep the old distribution, old certificate, and validation records throughout
the rollback window; #333 cleanup is not authorized by this procedure. If any
post-cutover smoke, certificate, deployment, or DNS check fails, first release
the new development alias, if attached, using an exact reviewed administrator
plan or full-config/ETag alias-only update, and wait for `Deployed`. Then dispatch
the same workflow with `operation=rollback` and the exact captured snapshot. It
must fail closed unless the current dev record still has the captured ID and
currently points to the staged development hostname. It then PUTs only that ID
back to the captured old content and checks the legacy CloudFront hostname.
After DNS resolves to the old target, restore only the old alias with the
captured configuration and a freshly fetched ETag; assert all non-alias fields
are unchanged, wait for `Deployed`, and verify `https://dev.tollchat.ai` itself.
If DNS never changed, skip the DNS rollback and restore the old alias directly.
As in the forward move, DNS must point to the destination before restoring its
alias. The workflow's legacy-host probe alone is not custom-host health proof.
Do not remove a validation record, alter apex/`www`, or use a generic record
delete. Keep recurring delivery disabled until the chosen endpoint and the
full application plan are healthy and contain no administrator-owned changes.

Before authorizing #333 cleanup, prove a successful rollback against the
captured record in a disposable/reviewed gate, retain production no-change
evidence, and confirm that no workflow output, summary, artifact, cache, plan,
state, or log contains the Cloudflare token or Authorization header. A stale,
missing, ambiguous, or concurrently changed snapshot is a hard stop requiring
fresh read-only evidence; never guess at a replacement record.

~~~sh
(
set -euo pipefail
set +x
umask 077
ROOT="$(git rev-parse --show-toplevel)"
EXPECTED_ACCOUNT=903859731897
REGION=us-east-1
AWS_PROFILE=nova-toll-dev
: "$RELEASE_EVIDENCE"
case "$RELEASE_EVIDENCE" in /*) ;; *) exit 1 ;; esac
RELEASE_EVIDENCE="$(readlink -m -- "$RELEASE_EVIDENCE")"
case "$RELEASE_EVIDENCE" in "$ROOT"|"$ROOT"/*) exit 1 ;; esac
test ! -e "$RELEASE_EVIDENCE"
test "$(git -C "$ROOT" rev-parse --show-toplevel)" = "$ROOT"
git -C "$ROOT" diff --check
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)"
for command_name in aws curl dig find git jq psql python3 rg sha256sum terraform unzip uv; do command -v "$command_name" >/dev/null; done
RELEASE_DIR="$(mktemp -d -t nova-toll-331-XXXXXX)"
FOUNDATION_TF_DATA_DIR="$RELEASE_DIR/foundation-tfdata"
APP_TF_DATA_DIR="$RELEASE_DIR/application-tfdata"
FOUNDATION_JSON="$RELEASE_DIR/foundation.json"
DEV_FOUNDATION_VARS="$RELEASE_DIR/foundation.tfvars.json"
PHASE_ONE_PLAN="$RELEASE_DIR/development-phase-one.tfplan"
PHASE_TWO_PLAN="$RELEASE_DIR/development-phase-two.tfplan"
PHASE_ONE_PLAN_JSON="$RELEASE_DIR/development-phase-one.tfplan.json"
PHASE_TWO_PLAN_JSON="$RELEASE_DIR/development-phase-two.tfplan.json"
PLAN_JSON=
CA_FILE="$RELEASE_DIR/global-bundle.pem"
IDENTITY_JSON="$RELEASE_DIR/identity.json"
RESET_BODY="$RELEASE_DIR/reset.json"
RESET_REQUEST="$RELEASE_DIR/reset-request.json"
LAMBDA_ACCOUNT_SETTINGS="$RELEASE_DIR/lambda-account-settings.json"
SECRET_ARN=
SECRET_JSON=
PGUSER=
PGPASSWORD=
cleanup() {
  unset PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE PGSSLMODE PGSSLROOTCERT
  unset SECRET_JSON SECRET_ARN RDS_METADATA DB_USER DB_PASSWORD DB_HOST DB_PORT
  rm -f -- "$FOUNDATION_JSON" "$DEV_FOUNDATION_VARS" "$PHASE_ONE_PLAN_JSON" "$PHASE_TWO_PLAN_JSON" "$CA_FILE" "$IDENTITY_JSON" "$RESET_BODY" "$RESET_REQUEST" "$LAMBDA_ACCOUNT_SETTINGS" "$PHASE_ONE_PLAN" "$PHASE_TWO_PLAN"
  rm -rf -- "$ROOT/v2/infra/build"
  rm -rf -- "$RELEASE_DIR"
}
trap cleanup EXIT
account() {
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json >"$IDENTITY_JSON"
  jq -e --arg account "$EXPECTED_ACCOUNT" 'select(.Account == $account)' "$IDENTITY_JSON" >/dev/null
}
aws_dev() {
  account
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" aws --region "$REGION" "$@"
}
tf_dev() {
  account
  AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" TF_DATA_DIR="$TF_DATA_DIR" terraform "$@"
}

export TF_DATA_DIR="$FOUNDATION_TF_DATA_DIR"
grep -F 'bucket       = "nova-toll-tfstate-903859731897"' "$ROOT/infra/backend.development.hcl" >/dev/null
grep -F 'key          = "nova-toll/development/terraform.tfstate"' "$ROOT/infra/backend.development.hcl" >/dev/null
grep -F 'kms_key_id   = "alias/nova-toll-tfstate"' "$ROOT/infra/backend.development.hcl" >/dev/null
tf_dev -chdir="$ROOT/infra" init -reconfigure -input=false -backend-config="$ROOT/infra/backend.development.hcl" >/dev/null
tf_dev -chdir="$ROOT/infra" output -json foundation >"$FOUNDATION_JSON"
jq -e 'def exact_keys($keys): type == "object" and ((keys_unsorted | sort) == ($keys | sort)); . as $foundation | exact_keys(["vpc_id", "vpc_cidr_block", "private_subnet_ids", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "db_instance", "alerts_topic_arn"]) and all(["vpc_id", "vpc_cidr_block", "rds_security_group_id", "agentcore_endpoint_security_group_id", "eventbridge_endpoint_security_group_id", "agentcore_vpc_endpoint_id", "agentcore_vpc_endpoint_dns_name", "tollchat_api_vpc_endpoint_id", "raw_bucket_name", "raw_kms_key_arn", "agentcore_artifacts_bucket_name", "alerts_topic_arn"][]; $foundation[.] | type == "string" and length > 0) and ($foundation.private_subnet_ids | exact_keys(["a", "c"]) and all(.[]; type == "string" and length > 0)) and ($foundation.db_instance | exact_keys(["identifier", "resource_id", "address", "port"]) and all(["identifier", "resource_id", "address"][]; $foundation.db_instance[.] | type == "string" and length > 0) and (.port | type == "number"))' "$FOUNDATION_JSON" >/dev/null
if rg --fixed-strings --quiet '920534282028' "$FOUNDATION_JSON" || rg --ignore-case --quiet 'password|secret|ssm|terraform_remote_state' "$FOUNDATION_JSON"; then exit 1; fi
jq -n --argjson foundation "$(<"$FOUNDATION_JSON")" '{foundation: $foundation}' >"$DEV_FOUNDATION_VARS"
chmod 600 -- "$FOUNDATION_JSON" "$DEV_FOUNDATION_VARS"
DNS_BEFORE="$(dig +short dev.tollchat.ai CNAME | tr -d '\r')"
test "$DNS_BEFORE" = "dmsiz11apblcv.cloudfront.net."
cd "$ROOT/v2"
./scripts/build_loader_zip.sh >/dev/null
./scripts/build_publisher_zip.sh >/dev/null
./scripts/build_agentcore_zips.sh >/dev/null
for package in infra/build/loader.zip infra/build/publisher.zip infra/build/agentcore.zip infra/build/chat-proxy.zip; do test -s "$package"; ! unzip -Z1 "$package" | rg --line-regexp '(^|/)\.env$'; done
LOADER_SHA256="$(sha256sum infra/build/loader.zip | cut -d' ' -f1)"
PUBLISHER_SHA256="$(sha256sum infra/build/publisher.zip | cut -d' ' -f1)"
AGENTCORE_SHA256="$(sha256sum infra/build/agentcore.zip | cut -d' ' -f1)"
PROXY_SHA256="$(sha256sum infra/build/chat-proxy.zip | cut -d' ' -f1)"
ARTIFACT_SCAN_PATTERN='920534282028|nova-toll-prod|backend\.production\.hcl|terraform_remote_state|arn:aws:secretsmanager:|AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)[[:space:]]*[:=][[:space:]]*[^[:space:]}\"]{8,}|PGPASSWORD=|NOVA_TOLL_ADMIN_URL=|SECRET_(ARN|STRING)[[:space:]]*[:=][[:space:]]*[^[:space:]}\"]{8,}|\"(secret(_arn|string)?|password)\"[[:space:]]*[:=][[:space:]]*\"?[[:alnum:]/+=_-]{8,}'
PACKAGE_SCAN_PATTERN='920534282028|nova-toll-prod|backend\.production\.hcl|terraform_remote_state|PGPASSWORD=|NOVA_TOLL_ADMIN_URL=|SECRET_(ARN|STRING)[[:space:]]*[:=][[:space:]}\"]{8,}'
SSM_ARN_PATTERN='arn:aws:ssm:[[:alnum:]-]+:[0-9]{12}:parameter/[[:alnum:]_.:/=+-]+'
ALLOWED_SSM_REFERENCE='arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key'
scan_ssm_references() {
  local reference
  while IFS= read -r reference; do
    test "$reference" = "$ALLOWED_SSM_REFERENCE"
  done
}
scan_release_file() {
  local file="$1" references
  if rg --text --ignore-case --quiet -- "$ARTIFACT_SCAN_PATTERN" "$file"; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if references="$(rg --text --only-matching -- "$SSM_ARN_PATTERN" "$file")"; then
    scan_ssm_references <<<"$references"
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_package() {
  local package="$1" references
  unzip -t "$package" >/dev/null
  if unzip -Z1 "$package" | rg --ignore-case --quiet '(^|/)\.env$'; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if unzip -p "$package" | rg --text --ignore-case --quiet -- "$PACKAGE_SCAN_PATTERN"; then
    exit 1
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
  if references="$(unzip -p "$package" | rg --text --only-matching -- "$SSM_ARN_PATTERN")"; then
    scan_ssm_references <<<"$references"
  elif [ "$?" -ne 1 ]; then
    exit 1
  fi
}
scan_release_directory() {
  while IFS= read -r -d '' file; do
    scan_release_file "$file"
  done < <(find "$RELEASE_DIR" -type f -print0)
}
for package in infra/build/loader.zip infra/build/publisher.zip infra/build/agentcore.zip infra/build/chat-proxy.zip; do
  scan_package "$package"
done

export TF_DATA_DIR="$APP_TF_DATA_DIR"
grep -F 'bucket       = "nova-toll-tfstate-903859731897"' infra/backend.development.hcl >/dev/null
grep -F 'key          = "nova-toll/v2/development/terraform.tfstate"' infra/backend.development.hcl >/dev/null
grep -F 'kms_key_id   = "alias/nova-toll-tfstate"' infra/backend.development.hcl >/dev/null
tf_dev -chdir="$ROOT/v2/infra" init -reconfigure -input=false -backend-config="$ROOT/v2/infra/backend.development.hcl" >/dev/null
plan_policy() {
  local plan="$1"
  local phase="${2:-}"
  if [ "$phase" = phase-two ]; then
    PLAN_JSON="$PHASE_TWO_PLAN_JSON"
  else
    PLAN_JSON="$PHASE_ONE_PLAN_JSON"
  fi
  tf_dev -chdir="$ROOT/v2/infra" show -json "$plan" >"$PLAN_JSON"
  if ! jq -e --arg allowlist "$DEVELOPMENT_RESOURCE_ALLOWLIST" --arg data_allowlist "$DEVELOPMENT_DATA_ALLOWLIST" --arg readonly "$DEVELOPMENT_READ_ONLY_ALLOWLIST" --arg retired "$DEVELOPMENT_RETIRED_USAGE_ALLOWLIST" '
    def base: .address | split("[")[0];
    def listed($items): .address as $address | any(($items | split("\n") | map(select(length > 0)))[]; . as $item | $address == $item or ($address | startswith($item + "[")));
    def retired_exact($items): .address as $address | any(($items | split("\n") | map(select(length > 0)))[]; $address == .);
    def immutable: ((base == "aws_api_gateway_deployment.tollchat" and (.change.actions == ["create"] or .change.actions == ["delete"] or .change.actions == ["create", "delete"] or .change.actions == ["delete", "create"])) or (base == "aws_bedrock_guardrail_version.tollchat" and .change.actions == ["create"]));
    (.resource_changes | type == "array") and all(.resource_changes[];
      (.address | type == "string") and (.change.actions | type == "array" and length > 0) and (.deposed? == null) and (.previous_address? == null) and
      (.mode == "data" and listed($data_allowlist) and (.change.actions == ["read"] or .change.actions == ["no-op"]) or
       .mode == "managed" and
       ((.change.actions == ["delete"] and retired_exact($retired)) or
        (listed($allowlist) and
         ((.change.actions == ["no-op"]) or
          (.change.actions == ["update"] and (listed($readonly) | not)) or immutable))))
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if jq -r '.resource_changes[]? | [.address, (.change.after // {} | tostring)] | @json' "$PLAN_JSON" | rg --quiet '920534282028|dev.tollchat.ai' || jq -r '.resource_changes[]?.address' "$PLAN_JSON" | rg --ignore-case --quiet 'cloudflare|route53|terraform_remote_state'; then exit 1; fi
  if ! jq -e '
    def account_ok($value):
      (((($value | test("^arn:aws:[^:]*:[^:]*:[0-9]{12}:")) | not)
       or ($value | test("^arn:aws:[^:]*:[^:]*:903859731897:"))));
    def no_known_value($value):
      (["toll-v2-pricing-loader", "toll-v2-report-publisher", "tollchat-v2-chat-proxy", "tollchat-v2-agent-usage-rollup", "nova-toll-v2-chat-proxy", "nova-toll-v2-preview", "tollchat-v2-anonymous-sessions", "tollchat-v2-agentcore-runtime"] | any(.[]; . == $value) | not);
    def identifier_ok($value):
      (($value | test("(^|[/:\"])(nova_toll|pricing_loader_writer|pricing_reader|oracle_owner|tollchat_agent|pricing_caller|report_publisher)([/:\"]|$)"; "i")) | not);
    def app_name_ok($value):
      (($value | test("(^|[/:\"])(toll-v2-pricing-loader|toll-v2-report-publisher|tollchat-v2-chat-proxy|tollchat-v2-agent-usage-rollup|nova-toll-v2-chat-proxy|nova-toll-v2-preview|tollchat-v2-anonymous-sessions|nova-toll-v2-agentcore-runtime)([/:\"]|$)"; "i")) | not);
    def suffix_ok($after):
      all(["function_name", "role", "role_arn", "table_name", "queue_name", "log_group_name", "alarm_name", "database_name", "workgroup_name"][];
        . as $key |
        ($after[$key] == null
          or ($after[$key] | type != "string")
          or (($after[$key] | test("(^|[/:-])(toll-v2|tollchat-v2|nova-toll-v2)"; "i")) | not)
          or ($after[$key] | test("-dev([/:]|$)|-development([/:]|$)|_development([/:]|$)"))
        )
      );
    def plan_strings($after):
      [$after | .. | strings] + [$after | .. | strings | try fromjson catch empty | .. | strings] | .[];
    def environment_ok($after):
      ([
        (($after.environment[]?.variables? // {}) | to_entries[]?),
        (($after.environment_variables // {}) | to_entries[]?)
      ] | all(.[]?;
        (.key as $key | .value as $value |
          (($key | test("^(DB_NAME|DB_USER|DB_READER_USER|PRICING_DB_USER|ATHENA_DATABASE|SESSION_TABLE_NAME|SITE_BUCKET_NAME|AGENT_MEASUREMENT_BUCKET)$")) | not)
          or ($value | type != "string")
          or ($value | test("-dev([/:]|$)|-development([/:]|$)|_development([/:]|$)"))
        )
      ));
    all(.resource_changes[] | select(.mode == "managed" and .change.after != null);
      .change.after as $after |
      (all(plan_strings($after); . as $value | account_ok($value) and no_known_value($value) and identifier_ok($value) and app_name_ok($value))
        and suffix_ok($after)
        and environment_ok($after))
    )
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if ! jq -e '
    def managed_changes($address):
      [.resource_changes[]? | select(.mode == "managed" and .address == $address)] as $changes |
      if ($changes | length) == 1 then $changes[0] else false end;
    def reserved($address; $expected):
      managed_changes($address) as $resource |
      if ($resource | type) != "object" then false
      elif (($resource.change.after_unknown? // {}) | (.reserved_concurrent_executions? // false)) then false
      else ($resource.change.after | type == "object" and .reserved_concurrent_executions == $expected)
      end;
    def default_edge:
      managed_changes("aws_cloudfront_distribution.site") as $resource |
      if ($resource | type) != "object" then false
      else $resource.change.after as $after |
        if ($after | type) != "object" then false
        elif (($after.aliases | type) != "array" or ($after.aliases | length) != 0) then false
        elif (($after.viewer_certificate | type) != "array" or ($after.viewer_certificate | length) != 1) then false
        elif (($after.viewer_certificate[0] | type) != "object") then false
        else $after.viewer_certificate[0] as $certificate |
          ($certificate | has("acm_certificate_arn") and (.acm_certificate_arn == null or .acm_certificate_arn == "")
            and has("cloudfront_default_certificate") and .cloudfront_default_certificate == true
            and has("minimum_protocol_version") and .minimum_protocol_version == "TLSv1"
            and has("ssl_support_method") and (.ssl_support_method == null or .ssl_support_method == ""))
        end
      end;
    all(.resource_changes[]; (.change.actions | type == "array" and length > 0))
      and reserved("aws_lambda_function.loader"; 5)
      and reserved("aws_lambda_function.publisher"; 1)
      and reserved("aws_lambda_function.tollchat_proxy"; 5)
      and default_edge
  ' "$PLAN_JSON" >/dev/null; then exit 1; fi
  if [ "$phase" = phase-two ]; then
    if ! jq -e 'all(.resource_changes[]; (.change.actions | type == "array" and length > 0) and (.mode == "data" or .change.actions == ["update"] or .change.actions == ["no-op"]))' "$PLAN_JSON" >/dev/null; then exit 1; fi
  fi
  sha256sum "$plan" | cut -d' ' -f1
}
PLAN_ARGS="-var-file=$ROOT/v2/infra/development.tfvars -var-file=$DEV_FOUNDATION_VARS -var loader_package_path=$ROOT/v2/infra/build/loader.zip -var publisher_package_path=$ROOT/v2/infra/build/publisher.zip -var agentcore_package_path=$ROOT/v2/infra/build/agentcore.zip -var chat_proxy_package_path=$ROOT/v2/infra/build/chat-proxy.zip"
read -r -d '' DEVELOPMENT_RESOURCE_ALLOWLIST <<'EOF' || true
aws_api_gateway_deployment.tollchat
aws_api_gateway_integration.tollchat_proxy
aws_api_gateway_integration.tollchat_root
aws_api_gateway_method.tollchat_proxy
aws_api_gateway_method.tollchat_root
aws_api_gateway_method_settings.tollchat
aws_api_gateway_resource.tollchat_proxy
aws_api_gateway_rest_api.tollchat
aws_api_gateway_rest_api_policy.tollchat
aws_api_gateway_stage.tollchat
aws_athena_named_query.recent_routes
aws_athena_named_query.top_routes
aws_athena_workgroup.agent_reports
aws_bedrock_guardrail.tollchat
aws_bedrock_guardrail_version.tollchat
aws_bedrockagentcore_agent_runtime.tollchat
aws_bedrockagentcore_agent_runtime_endpoint.tollchat
aws_bedrockagentcore_resource_policy.tollchat
aws_cloudfront_distribution.site
aws_cloudfront_function.public_chat_routes
aws_cloudfront_function.public_report_routes
aws_cloudfront_origin_access_control.public_chat
aws_cloudfront_origin_access_control.site
aws_cloudfront_response_headers_policy.development_noindex
aws_cloudwatch_event_rule.agent_usage_rollup
aws_cloudwatch_event_rule.raw_objects
aws_cloudwatch_event_target.agent_usage_rollup
aws_cloudwatch_event_target.loader
aws_cloudwatch_log_group.agent_usage_rollup
aws_cloudwatch_log_group.agentcore_runtime
aws_cloudwatch_log_group.loader
aws_cloudwatch_log_group.publisher
aws_cloudwatch_log_group.tollchat_proxy
aws_cloudwatch_log_group.usage_publisher
aws_cloudwatch_log_metric_filter.load_success
aws_cloudwatch_log_metric_filter.proxy_failure
aws_cloudwatch_metric_alarm.agent_usage_log_coverage
aws_cloudwatch_metric_alarm.agent_usage_rollup_errors
aws_cloudwatch_metric_alarm.agent_usage_rollup_missing
aws_cloudwatch_metric_alarm.failure_queues
aws_cloudwatch_metric_alarm.freshness
aws_cloudwatch_metric_alarm.loader_errors
aws_cloudwatch_metric_alarm.publisher_errors
aws_cloudwatch_metric_alarm.publisher_failure_queues
aws_cloudwatch_metric_alarm.report_generation_freshness
aws_cloudwatch_metric_alarm.tollchat_proxy_errors
aws_cloudwatch_metric_alarm.tollchat_proxy_failures
aws_cloudwatch_metric_alarm.tollchat_proxy_latency
aws_cloudwatch_metric_alarm.tollchat_sessions
aws_dynamodb_table.tollchat_sessions
aws_glue_catalog_database.agent_reports
aws_glue_catalog_table.agent_registry
aws_glue_catalog_table.agent_report_generations
aws_glue_catalog_table.agent_report_rollup_completions
aws_glue_catalog_table.agent_report_rollups
aws_glue_catalog_table.waf_logs
aws_iam_role.agent_usage_rollup
aws_iam_role.loader
aws_iam_role.publisher
aws_iam_role.publisher_scheduler
aws_iam_role.timed_checks
aws_iam_role.tollchat_proxy
aws_iam_role.tollchat_runtime
aws_iam_role_policy.agent_usage_rollup
aws_iam_role_policy.loader
aws_iam_role_policy.publisher
aws_iam_role_policy.publisher_scheduler
aws_iam_role_policy.timed_checks
aws_iam_role_policy.tollchat_proxy
aws_iam_role_policy.tollchat_runtime
aws_iam_role_policy_attachment.loader_vpc
aws_iam_role_policy_attachment.publisher_vpc
aws_iam_role_policy_attachment.tollchat_proxy_vpc
aws_kms_alias.agent_measurement
aws_kms_alias.site
aws_kms_key.agent_measurement
aws_kms_key.site
aws_lambda_alias.tollchat_live
aws_lambda_function.agent_usage_rollup
aws_lambda_function.loader
aws_lambda_function.publisher
aws_lambda_function.tollchat_proxy
aws_lambda_function_event_invoke_config.loader
aws_lambda_function_event_invoke_config.publisher
aws_lambda_function_url.public_chat
aws_lambda_permission.agent_usage_rollup
aws_lambda_permission.eventbridge_invoke
aws_lambda_permission.public_chat_invoke
aws_lambda_permission.public_chat_url
aws_lambda_permission.tollchat_api
aws_lambda_provisioned_concurrency_config.tollchat
aws_s3_bucket.agent_measurement
aws_s3_bucket.site
aws_s3_bucket_lifecycle_configuration.agent_measurement
aws_s3_bucket_policy.agent_measurement
aws_s3_bucket_policy.site
aws_s3_bucket_public_access_block.agent_measurement
aws_s3_bucket_public_access_block.site
aws_s3_bucket_server_side_encryption_configuration.agent_measurement
aws_s3_bucket_server_side_encryption_configuration.site
aws_s3_object.agent_registry
aws_s3_object.agentcore
aws_s3_object.chat
aws_s3_object.faq
aws_s3_object.index
aws_s3_object.privacy
aws_s3_object.robots
aws_s3_object.site_assets
aws_s3_object.terms
aws_s3_object.tollchat_proxy
aws_s3_object.usage
aws_scheduler_schedule.publisher
aws_security_group.loader
aws_security_group.publisher
aws_security_group.tollchat_proxy
aws_security_group.tollchat_runtime
aws_sqs_queue.delivery_failure
aws_sqs_queue.invoke_failure
aws_sqs_queue.publisher_delivery_failure
aws_sqs_queue.publisher_invoke_failure
aws_sqs_queue_policy.delivery_failure
aws_vpc_security_group_egress_rule.loader_to_eventbridge
aws_vpc_security_group_egress_rule.loader_to_rds
aws_vpc_security_group_egress_rule.loader_to_s3
aws_vpc_security_group_egress_rule.proxy_https
aws_vpc_security_group_egress_rule.proxy_to_dynamodb
aws_vpc_security_group_egress_rule.publisher_to_rds
aws_vpc_security_group_egress_rule.publisher_to_s3
aws_vpc_security_group_egress_rule.runtime_https
aws_vpc_security_group_egress_rule.runtime_to_rds
aws_vpc_security_group_ingress_rule.agentcore_from_proxy
aws_vpc_security_group_ingress_rule.rds_from_loader
aws_vpc_security_group_ingress_rule.rds_from_publisher
aws_vpc_security_group_ingress_rule.rds_from_runtime
aws_wafv2_web_acl.public_chat
aws_wafv2_web_acl_logging_configuration.agent_reports
EOF
read -r -d '' DEVELOPMENT_DATA_ALLOWLIST <<'EOF' || true
data.archive_file.agent_usage_rollup
data.archive_file.placeholder
data.aws_caller_identity.current
data.aws_cloudfront_cache_policy.caching_disabled
data.aws_cloudfront_origin_request_policy.all_except_host
data.aws_iam_policy_document.agent_measurement_bucket
data.aws_iam_policy_document.agent_measurement_kms
data.aws_iam_policy_document.agent_usage_rollup
data.aws_iam_policy_document.agentcore_assume
data.aws_iam_policy_document.delivery_failure
data.aws_iam_policy_document.lambda_assume
data.aws_iam_policy_document.loader
data.aws_iam_policy_document.publisher
data.aws_iam_policy_document.publisher_scheduler
data.aws_iam_policy_document.publisher_scheduler_assume
data.aws_iam_policy_document.site_kms
data.aws_iam_policy_document.timed_checks
data.aws_iam_policy_document.timed_checks_assume
data.aws_iam_policy_document.tollchat_proxy
data.aws_iam_policy_document.tollchat_runtime
data.aws_prefix_list.dynamodb
data.aws_prefix_list.s3
data.aws_region.current
EOF
read -r -d '' DEVELOPMENT_READ_ONLY_ALLOWLIST <<'EOF' || true
aws_api_gateway_deployment.tollchat
aws_bedrock_guardrail_version.tollchat
aws_bedrock_guardrail.tollchat
aws_bedrockagentcore_resource_policy.tollchat
aws_cloudfront_distribution.site
aws_cloudfront_origin_access_control.public_chat
aws_cloudfront_origin_access_control.site
aws_cloudfront_response_headers_policy.development_noindex
aws_iam_role.agent_usage_rollup
aws_iam_role.loader
aws_iam_role.publisher
aws_iam_role.publisher_scheduler
aws_iam_role.timed_checks
aws_iam_role.tollchat_proxy
aws_iam_role.tollchat_runtime
aws_iam_role_policy.agent_usage_rollup
aws_iam_role_policy.loader
aws_iam_role_policy.publisher
aws_iam_role_policy.publisher_scheduler
aws_iam_role_policy.timed_checks
aws_iam_role_policy.tollchat_proxy
aws_iam_role_policy.tollchat_runtime
aws_iam_role_policy_attachment.loader_vpc
aws_iam_role_policy_attachment.publisher_vpc
aws_iam_role_policy_attachment.tollchat_proxy_vpc
aws_kms_alias.agent_measurement
aws_kms_alias.site
aws_kms_key.agent_measurement
aws_kms_key.site
aws_lambda_function_url.public_chat
aws_lambda_permission.agent_usage_rollup
aws_lambda_permission.eventbridge_invoke
aws_lambda_permission.public_chat_invoke
aws_lambda_permission.public_chat_url
aws_lambda_permission.tollchat_api
aws_s3_bucket.agent_measurement
aws_s3_bucket_lifecycle_configuration.agent_measurement
aws_s3_bucket_policy.agent_measurement
aws_s3_bucket_policy.site
aws_s3_bucket_public_access_block.agent_measurement
aws_s3_bucket_server_side_encryption_configuration.agent_measurement
EOF
read -r -d '' DEVELOPMENT_RETIRED_USAGE_ALLOWLIST <<'EOF' || true
aws_iam_role.usage_publisher
aws_iam_role_policy.usage_publisher
aws_lambda_function.usage_publisher
aws_cloudwatch_event_rule.usage_publisher
aws_cloudwatch_event_target.usage_publisher
aws_lambda_permission.usage_publisher
aws_cloudwatch_metric_alarm.usage_publisher_errors
aws_cloudwatch_metric_alarm.usage_publisher_failed_invocations
EOF
source_tree_digest() {
  git -C "$ROOT" ls-files -z | while IFS= read -r -d '' path; do
    sha256sum "$ROOT/$path"
  done | sha256sum | cut -d' ' -f1
}
SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_TREE_SHA256="$(source_tree_digest)"
SOURCE_DIFF_SHA256="$(git -C "$ROOT" diff HEAD --no-ext-diff --binary -- . ':(exclude).graph' | sha256sum | cut -d' ' -f1)"
tf_dev -chdir="$ROOT/v2/infra" plan -input=false $PLAN_ARGS -var public_preview_hostname= -out="$PHASE_ONE_PLAN" >/dev/null
PHASE_ONE_PLAN_SHA256="$(plan_policy "$PHASE_ONE_PLAN")"
scan_release_file "$PHASE_ONE_PLAN"
scan_release_file "$PHASE_ONE_PLAN_JSON"
scan_release_directory
aws_dev lambda get-account-settings >"$LAMBDA_ACCOUNT_SETTINGS"
LAMBDA_QUOTA="$(aws_dev service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text)"
uv run --project "$ROOT/v2" python "$ROOT/v2/scripts/check_lambda_quota_gate.py" --account-settings "$LAMBDA_ACCOUNT_SETTINGS" --plan "$PHASE_ONE_PLAN_JSON" --quota "$LAMBDA_QUOTA" >/dev/null
tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_ONE_PLAN" >/dev/null
PUBLIC_SITE_JSON="$(tf_dev -chdir="$ROOT/v2/infra" output -json public_site)"
PREVIEW_HOST="$(jq -er '.hostname | select(test("^d[A-Za-z0-9]+[.]cloudfront[.]net$"))' <<<"$PUBLIC_SITE_JSON")"
PREVIEW_URL="https://$PREVIEW_HOST"
test "$(jq -r '.url' <<<"$PUBLIC_SITE_JSON")" = ""
tf_dev -chdir="$ROOT/v2/infra" plan -input=false $PLAN_ARGS -var "public_preview_hostname=$PREVIEW_HOST" -out="$PHASE_TWO_PLAN" >/dev/null
PHASE_TWO_PLAN_SHA256="$(plan_policy "$PHASE_TWO_PLAN" phase-two)"
scan_release_file "$PHASE_TWO_PLAN"
scan_release_file "$PHASE_TWO_PLAN_JSON"
scan_release_directory
aws_dev lambda get-account-settings >"$LAMBDA_ACCOUNT_SETTINGS"
LAMBDA_QUOTA="$(aws_dev service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --query 'Quota.Value' --output text)"
uv run --project "$ROOT/v2" python "$ROOT/v2/scripts/check_lambda_quota_gate.py" --account-settings "$LAMBDA_ACCOUNT_SETTINGS" --plan "$PHASE_TWO_PLAN_JSON" --quota "$LAMBDA_QUOTA" >/dev/null
tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_TWO_PLAN" >/dev/null
PUBLIC_SITE_JSON="$(tf_dev -chdir="$ROOT/v2/infra" output -json public_site)"
test "$(jq -r '.url' <<<"$PUBLIC_SITE_JSON")" = "$PREVIEW_URL"
DIST_ID="$(jq -er '.distribution_id' <<<"$PUBLIC_SITE_JSON")"
aws_dev cloudfront wait distribution-deployed --id "$DIST_ID"
DIST_INFO="$(aws_dev cloudfront get-distribution --id "$DIST_ID" --query 'Distribution.{domain:DomainName,status:Status,aliases:DistributionConfig.Aliases.Items,default_certificate:DistributionConfig.ViewerCertificate.CloudFrontDefaultCertificate,minimum_protocol_version:DistributionConfig.ViewerCertificate.MinimumProtocolVersion}' --output json)"
jq -e --arg host "$PREVIEW_HOST" '(.domain == $host) and (.status == "Deployed") and ((.aliases // []) | length == 0) and (.default_certificate == true) and (.minimum_protocol_version == "TLSv1")' <<<"$DIST_INFO" >/dev/null
PUBLIC_ORIGINS="$(aws_dev lambda get-function-configuration --function-name tollchat-v2-chat-proxy-dev --query 'Environment.Variables.PUBLIC_ORIGINS' --output text)"
test "$PUBLIC_ORIGINS" = "$PREVIEW_URL"
PUBLIC_BASE_URL="$(aws_dev lambda get-function-configuration --function-name toll-v2-report-publisher-dev --query 'Environment.Variables.PUBLIC_BASE_URL' --output text)"
test "$PUBLIC_BASE_URL" = "$PREVIEW_URL"
assert_reserved_concurrency() {
  local function_name="$1" expected="$2"
  test "$(aws_dev lambda get-function-concurrency --function-name "$function_name" --query ReservedConcurrentExecutions --output text)" = "$expected"
}
assert_reserved_concurrency toll-v2-pricing-loader-dev 5
assert_reserved_concurrency toll-v2-report-publisher-dev 1
assert_reserved_concurrency tollchat-v2-chat-proxy-dev 5
FOUNDATION_DIGEST="$(sha256sum "$FOUNDATION_JSON" | cut -d' ' -f1)"
RDS_METADATA="$(aws_dev rds describe-db-instances --db-instance-identifier "$(jq -er '.db_instance.identifier' "$FOUNDATION_JSON")" --query 'DBInstances[0].{status:DBInstanceStatus,address:Endpoint.Address,port:Endpoint.Port,private:PubliclyAccessible,secret:MasterUserSecret.SecretArn}' --output json)"
DB_HOST="$(jq -er '.address' <<<"$RDS_METADATA")"
DB_PORT="$(jq -er '.port | tostring' <<<"$RDS_METADATA")"
jq -e --arg address "$(jq -er '.db_instance.address' "$FOUNDATION_JSON")" --argjson port "$(jq -er '.db_instance.port' "$FOUNDATION_JSON")" '(.status == "available") and (.private == false) and (.address == $address) and (.port == $port) and (.secret | type == "string" and length > 0)' <<<"$RDS_METADATA" >/dev/null
SECRET_ARN="$(jq -er '.secret' <<<"$RDS_METADATA")"
secret_json() {
  account
  SECRET_ARN="$SECRET_ARN" AWS_PROFILE="$AWS_PROFILE" AWS_DEFAULT_REGION="$REGION" \
    uv run --project "$ROOT/v2" python - <<'PY'
import boto3
import os

client = boto3.client("secretsmanager", region_name=os.environ["AWS_DEFAULT_REGION"])
print(client.get_secret_value(SecretId=os.environ["SECRET_ARN"])["SecretString"])
PY
}
SECRET_JSON="$(secret_json)"
jq -e 'type == "object" and (.username | type == "string" and length > 0) and (.password | type == "string" and length > 0)' <<<"$SECRET_JSON" >/dev/null
DB_USER="$(jq -er '.username' <<<"$SECRET_JSON")"
DB_PASSWORD="$(jq -er '.password' <<<"$SECRET_JSON")"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$CA_FILE"
echo 'e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3  '"$CA_FILE" | sha256sum --check --status
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" PGSSLMODE=verify-full PGSSLROOTCERT="$CA_FILE"
if [ -n "${NOVA_TOLL_RDS_LOCAL_PORT:-}" ]; then
  case "$NOVA_TOLL_RDS_LOCAL_PORT" in (*[!0-9]*|'') exit 1 ;; esac
  export PGHOSTADDR=127.0.0.1 PGPORT="$NOVA_TOLL_RDS_LOCAL_PORT"
fi
psql --dbname nova_toll_development --file "$ROOT/v2/tests/development_bootstrap_contract.sql" >/dev/null
for role in pricing_loader_writer pricing_reader tollchat_agent pricing_caller report_publisher; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT has_database_privilege('$role', 'nova_toll', 'CONNECT') AND NOT has_database_privilege('$role', 'nova_toll_development', 'CONNECT');" | grep -qx t
done
for role in pricing_loader_writer_development pricing_reader_development tollchat_agent_development pricing_caller_development report_publisher_development; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT has_database_privilege('$role', 'nova_toll_development', 'CONNECT') AND NOT has_database_privilege('$role', 'nova_toll', 'CONNECT');" | grep -qx t
done
for role in oracle_owner oracle_owner_development; do
  psql --dbname postgres --tuples-only --no-align --command "SELECT NOT rolcanlogin FROM pg_roles WHERE rolname = '$role';" | grep -qx t
done
DB_CONTRACT=pass
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$PREVIEW_URL/" -o /dev/null
printf '{}' >"$RESET_REQUEST"
RESET_BODY_SHA256="$(sha256sum "$RESET_REQUEST" | cut -d' ' -f1)"
RESET_CONTENT_TYPE="$(curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  --request POST "$PREVIEW_URL/api/reset" \
  --header "Origin: $PREVIEW_URL" \
  --header 'Content-Type: application/json' \
  --header 'Sec-Fetch-Site: same-origin' \
  --header "x-amz-content-sha256: $RESET_BODY_SHA256" \
  --data-binary "@$RESET_REQUEST" \
  --output "$RESET_BODY" \
  --write-out '%{content_type}')"
test "$RESET_CONTENT_TYPE" = "application/json"
jq -e '.ok == true' "$RESET_BODY" >/dev/null
DNS_AFTER="$(dig +short dev.tollchat.ai CNAME | tr -d '\r')"
test "$DNS_AFTER" = "$DNS_BEFORE"
RESOURCE_COUNT="$(tf_dev -chdir="$ROOT/v2/infra" state list | wc -l | tr -d ' ')"
RESOURCE_TYPES="$(tf_dev -chdir="$ROOT/v2/infra" state list | awk -F. '{print $1}' | sort -u | paste -sd, -)"
test -n "$RESOURCE_TYPES"
scan_release_directory
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SOURCE_REVISION"
test "$SOURCE_TREE_SHA256" = "$(source_tree_digest)"
test "$SOURCE_DIFF_SHA256" = "$(git -C "$ROOT" diff HEAD --no-ext-diff --binary -- . ':(exclude).graph' | sha256sum | cut -d' ' -f1)"
printf '%s\n' "account=$EXPECTED_ACCOUNT" "region=$REGION" "source_revision=$(git -C "$ROOT" rev-parse HEAD)" "source_tree_sha256=$SOURCE_TREE_SHA256" "source_diff_sha256=$SOURCE_DIFF_SHA256" "foundation_sha256=$FOUNDATION_DIGEST" "phase_one_plan_sha256=$PHASE_ONE_PLAN_SHA256" "phase_two_plan_sha256=$PHASE_TWO_PLAN_SHA256" "loader_sha256=$LOADER_SHA256" "publisher_sha256=$PUBLISHER_SHA256" "agentcore_sha256=$AGENTCORE_SHA256" "chat_proxy_sha256=$PROXY_SHA256" "plan_policy=pass" "lambda_quota=$LAMBDA_QUOTA" "lambda_reservations=5,1,5" "apply=pass" "database_bootstrap=not-run" "database_contract=$DB_CONTRACT" "resource_count=$RESOURCE_COUNT" "resource_inventory=$RESOURCE_TYPES" "preview_url=$PREVIEW_URL" "smoke=pass" "dns_before=$DNS_BEFORE" "dns_after=$DNS_AFTER" >"$RELEASE_EVIDENCE"
if rg --text --ignore-case --quiet 'password|secret_arn|secretstring|920534282028|dev.tollchat.ai|cloudflare|terraform\.tfstate|\.tfplan' "$RELEASE_EVIDENCE"; then
  exit 1
elif [ "$?" -ne 1 ]; then
  exit 1
fi
)
~~~

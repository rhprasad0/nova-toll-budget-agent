### Development bootstrap/import boundary (#332)

> **Historical source note.** The bootstrap/import procedure below predates the
> route-analytics source retirement. It is retained for audit and separately
> authorized recovery only; use the reviewed protected checkout that originally
> authorized it, and do not treat its historical analytics reads, inventories, or
> mutation simulations as
> current delivery permissions. This cleanup makes no deployment claim. Any
> retirement of retained measurement resources requires separate authority and
> its existing guarded gates.

Before the first recurring GitHub `development` run, a separately authorized
development-account administrator must inventory the live resources and create
or import them into the existing `v2/infra` root and the existing
`nova-toll/v2/development/terraform.tfstate` object. This is a one-time,
bounded bootstrap operation; it is not a second Terraform root, backend, or
state, and it never uses `-target` or `ignore_changes = all`.
This activation is a post-merge operator gate: review and merge this change
first, then run the procedure from a clean checkout of the protected
`origin/main`; no live bootstrap or recurring delivery is authorized from a
dirty feature worktree or before that merge.

The administrator owns the following addresses and their dependencies:

- all application `aws_iam_role.*`, `aws_iam_role_policy.*`, `aws_iam_policy.*`, and
  `aws_iam_role_policy_attachment.*` resources;
- `aws_bedrockagentcore_agent_runtime.tollchat`,
  `aws_bedrockagentcore_agent_runtime_endpoint.tollchat`, and every instance
  of `aws_bedrockagentcore_resource_policy.tollchat`;
- `aws_s3_bucket.agent_measurement`,
  `aws_s3_bucket_public_access_block.agent_measurement`,
  `aws_s3_bucket_policy.agent_measurement`,
  `aws_kms_key.agent_measurement`, and `aws_kms_alias.agent_measurement`;
- `aws_lambda_function_url.public_chat`,
  `aws_lambda_permission.public_chat_url`, and
  `aws_lambda_permission.public_chat_invoke`;
- the site KMS key/alias, site bucket policy, CloudFront distribution and
  origin controls, WAF, and other dependent exposure resources when they are
  absent from the application state.

For every item, retain only a non-secret live identifier, the normal Terraform
address, and a development-only refresh/read result. A missing resource or
import is a bootstrap failure. The administrator fixes it at that address and
does not widen the OIDC role. The bootstrap administrator also applies the
required `environment=development` and `version=v2` tags to application KMS
keys before enabling CI; the delivery role's exact allowlist is stored in seven
customer-managed policies `nova-toll-v2-development-delivery-{state,compute,observability,storage,data,runtime,edge}`
under path `/nova-toll/v2/development/`, attached only to that role. These policies use the two
exact application key ARNs and cannot retarget an alias to a foundation or
state key.

The following is the executable, fail-closed inventory and repair procedure.
Run it from this checkout as a development-account administrator. It writes
only non-secret inventory and Terraform state; it refuses every profile other
than `nova-toll-dev`, refuses any account other than `903859731897`, and never
uses a Terraform target or a second state. Leave `BOOTSTRAP_APPROVED` unset while
reviewing the inventory, rendered documents, and exact commands; set it to `YES`
only after the listed create/import/rollback commands have been reviewed. The
procedure fetches `origin/main`, derives the reviewed commit from that trusted
remote, and requires a clean checkout at that exact commit before any admin
command or package build. A feature worktree must stop at this gate.

The versioned development state bucket uses SSE-KMS. The bootstrap
administrator's exact minimum policy for this lock is
`s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, and
`s3:DeleteObjectVersion`, all on the one lock object
`arn:aws:s3:::nova-toll-tfstate-903859731897/nova-toll/v2/development/bootstrap-lock`.
The only KMS permission needed is `kms:GenerateDataKey` on the exact key ARN
returned by `aws --region us-east-1 kms describe-key --key-id
alias/nova-toll-tfstate --query KeyMetadata.Arn --output text`, conditioned on
`kms:EncryptionContext:aws:s3:arn` equal to that lock ARN. The procedure never
reads lock bytes, so it needs no `kms:Decrypt`, wildcard KMS action, bucket
listing, or object-version read permission. The recurring delivery role has no
permission on this object.
The lock uses the
existing versioned development Terraform-state bucket and S3 conditional
requests: `PutObject --if-none-match '*'` acquires it, and
`DeleteObject --if-match` plus the returned version ID (when present) releases
it. A crashed run leaves the object in place: a new run must stop. Manual stale
recovery is allowed only after proving no bootstrap invocation is active,
recording the observed ETag/version without logging the owner value, and
obtaining explicit approval for the exact fixed-key conditional delete. There
is no overwrite, expiry, retry, or lock stealing. The approved operator command
must use the observed values (and never a value fetched before the no-invocation
check), for example:
`aws --region us-east-1 s3api delete-object --bucket nova-toll-tfstate-903859731897
--key nova-toll/v2/development/bootstrap-lock --if-match OBSERVED_ETAG
--version-id OBSERVED_VERSION_ID`; a versionless bucket uses only `--if-match`.

```sh
set -euo pipefail
umask 077

ROOT="$(git rev-parse --show-toplevel)"
EXPECTED_PROFILE="nova-toll-dev"
EXPECTED_ACCOUNT="903859731897"
REGION="us-east-1"
ROLE_NAME="nova-toll-v2-development-delivery"
FUNCTION_NAME="tollchat-v2-chat-proxy-dev"
QUALIFIER="tollchat_live"
DISTRIBUTION_ID="E33DVF3KT7BTAC"
DISTRIBUTION_DOMAIN="d1wqry4fbd92w5.cloudfront.net"
: "${AWS_PROFILE:?invoke this procedure with AWS_PROFILE=nova-toll-dev}"

die() { printf 'bootstrap stopped: %s\n' "$*" >&2; exit 1; }
assert_dev_account() {
  test "$AWS_PROFILE" = "$EXPECTED_PROFILE" || die "unexpected AWS profile before mutation"
  test "${AWS_REGION:-}" = "$REGION" || die "unexpected AWS region before mutation"
  test "${AWS_DEFAULT_REGION:-}" = "$REGION" || die "unexpected AWS region before mutation"
  test "$(aws sts get-caller-identity --query Account --output text)" = "$EXPECTED_ACCOUNT" ||
    die "unexpected caller account before mutation"
}
test "$(git -C "$ROOT" rev-parse --show-toplevel)" = "$ROOT" ||
  die "checkout root could not be verified"
test "$AWS_PROFILE" = "$EXPECTED_PROFILE" || die "unexpected AWS profile"
case "$AWS_PROFILE" in *prod*|*production*) die "production profile rejected" ;; esac
if test -n "${AWS_REGION:-}" && test "$AWS_REGION" != "$REGION"; then
  die "AWS_REGION must be us-east-1"
fi
if test -n "${AWS_DEFAULT_REGION:-}" && test "$AWS_DEFAULT_REGION" != "$REGION"; then
  die "AWS_DEFAULT_REGION must be us-east-1"
fi
if test -n "${AWS_REGION:-}" && test -n "${AWS_DEFAULT_REGION:-}" &&
  test "$AWS_REGION" != "$AWS_DEFAULT_REGION"; then
  die "AWS_REGION and AWS_DEFAULT_REGION conflict"
fi
export AWS_PROFILE="$EXPECTED_PROFILE"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
ORIGIN_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null)" || die "trusted origin is not configured"
case "$ORIGIN_URL" in
  git@github.com:rhprasad0/nova-toll-budget-agent.git|https://github.com/rhprasad0/nova-toll-budget-agent.git) ;;
  *) die "origin URL is not the trusted repository" ;;
esac
git -C "$ROOT" fetch --no-tags origin main || die "could not fetch trusted origin/main"
PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"
printf '%s' "$PROTECTED_MAIN_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || die "origin/main is not a commit SHA"
test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT" ||
  die "checkout is not the fetched protected origin/main commit"
test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ||
  die "checkout has tracked or untracked changes; run only from clean protected origin/main"
git -C "$ROOT" diff --quiet HEAD -- || die "tracked checkout changes are not permitted"
git -C "$ROOT" diff --cached --quiet HEAD -- || die "staged checkout changes are not permitted"
CALLER_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
test "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT" || die "unexpected caller account"
: "${TF_VAR_budget_notification_email:?set a non-secret development notification address}"
test "${TF_VAR_tailscale_advertise_routes:-false}" = false ||
  die "development bootstrap must disable Tailscale route advertisement"

EVIDENCE_DIR="${BOOTSTRAP_EVIDENCE_DIR:?set an evidence directory outside this checkout}"
case "$EVIDENCE_DIR" in
  /*) ;;
  *) die "evidence directory must be an absolute path" ;;
esac
EVIDENCE_DIR="$(realpath -m -- "$EVIDENCE_DIR")" || die "evidence directory cannot be resolved"
case "$EVIDENCE_DIR" in "$ROOT"|"$ROOT"/*) die "evidence must be outside checkout" ;; esac
mkdir -p -- "$EVIDENCE_DIR"
chmod 700 -- "$EVIDENCE_DIR"
INVENTORY="$EVIDENCE_DIR/inventory.json"
test ! -e "$INVENTORY" || die "refusing to overwrite inventory"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tollchat-dev-bootstrap.XXXXXX")"
trap 'rm -rf -- "$WORK_DIR"' EXIT

FETCHER_BUILD="$ROOT/v2/scripts/build_fetcher_zip.sh"
FETCHER_INPUT="$ROOT/v2/lambdas/fetcher/handler.py"
FETCHER_PACKAGE="$ROOT/infra/build/fetcher.zip"
CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"
EXPECTED_FETCHER_SHA256="${EXPECTED_FETCHER_SHA256:?set the reviewed canonical fetcher SHA-256}"
REVIEWED_COMMIT="$PROTECTED_MAIN_COMMIT"
git -C "$ROOT" cat-file -e "$REVIEWED_COMMIT^{commit}" || die "trusted origin/main commit is not present"
test "$EXPECTED_FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256" ||
  die "expected fetcher digest is not the reviewed canonical value"
require_reviewed_file() {
  local path="$1" relative
  test -f "$path" && test ! -L "$path" || die "build input must be a regular non-symlink file: $path"
  relative="${path#"$ROOT"/}"
  test "$relative" != "$path" || die "build input must be inside the reviewed checkout"
  test "$(git -C "$ROOT" ls-files -- "$relative")" = "$relative" ||
    die "build input is not tracked by the reviewed commit: $relative"
  test -z "$(git -C "$ROOT" status --porcelain -- "$relative")" ||
    die "build input is modified or untracked: $relative"
  test -z "$(git -C "$ROOT" ls-files --others --exclude-standard -- "$relative")" ||
    die "build input is untracked: $relative"
  git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative" ||
    die "build input differs from reviewed protected-main: $relative"
  git -C "$ROOT" diff --cached --quiet -- "$relative" ||
    die "staged build input differs from reviewed protected-main: $relative"
}
require_reviewed_file "$FETCHER_BUILD"
require_reviewed_file "$FETCHER_INPUT"
test -d "$ROOT/infra/build" && test ! -L "$ROOT/infra/build" || die "fetcher output directory must be a regular directory"
test ! -L "$FETCHER_PACKAGE" || die "fetcher output must not be a symlink"
test ! -L "$ROOT/infra/build/fetcher" || die "fetcher staging directory must not be a symlink"
test -x "$FETCHER_BUILD" || die "canonical fetcher build script is not executable"
env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD" >"$WORK_DIR/fetcher-build.log"
test -f "$FETCHER_PACKAGE" && test -s "$FETCHER_PACKAGE" ||
  die "canonical fetcher artifact is missing or empty"
test "$(readlink -f -- "$FETCHER_PACKAGE")" = "$FETCHER_PACKAGE" ||
  die "canonical fetcher artifact must not be a symlink"
test "$(basename -- "$FETCHER_PACKAGE")" != placeholder.zip ||
  die "placeholder fetcher artifact is not permitted"
FETCHER_SHA256="$(sha256sum "$FETCHER_PACKAGE" | awk '{print $1}')"
test "$FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256" ||
  die "canonical fetcher digest does not match operator evidence"

one() {
  local label="$1"; shift
  local result
  result="$("$@")"
  jq -e 'type == "array" and length == 1' <<<"$result" >/dev/null ||
    die "$label is missing or ambiguous"
  jq -c '.[0]' <<<"$result"
}

printf '%s\n' '{' >"$INVENTORY"
printf '  "account": "%s",\n' "$CALLER_ACCOUNT" >>"$INVENTORY"
printf '  "api": ' >>"$INVENTORY"
one api aws apigateway get-rest-apis --query 'items[?id==`ocw8sg0wlb`].{id:id,name:name}' --output json >>"$INVENTORY"
printf ',\n  "guardrail": ' >>"$INVENTORY"
one guardrail aws bedrock list-guardrails --query 'guardrails[?id==`vdyqrh31xgca`].{id:id,name:name}' --output json >>"$INVENTORY"
printf ',\n  "runtime": ' >>"$INVENTORY"
one runtime aws bedrock-agentcore-control list-agent-runtimes --query 'agentRuntimes[?agentRuntimeId==`nova_toll_v2_development-Y69XBf88Bl`].{id:agentRuntimeId,arn:agentRuntimeArn}' --output json >>"$INVENTORY"
printf ',\n  "endpoint": ' >>"$INVENTORY"
one endpoint aws bedrock-agentcore-control list-agent-runtime-endpoints --agent-runtime-id nova_toll_v2_development-Y69XBf88Bl --query 'runtimeEndpoints[?id==`preview`].{id:id,arn:agentRuntimeEndpointArn}' --output json >>"$INVENTORY"
printf ',\n  "distribution": ' >>"$INVENTORY"
DISTRIBUTION_INFO="$(one cloudfront aws cloudfront list-distributions --query 'DistributionList.Items[?Id==`E33DVF3KT7BTAC` && DomainName==`d1wqry4fbd92w5.cloudfront.net`].{id:Id,domain:DomainName}' --output json)"
jq -e --arg id "$DISTRIBUTION_ID" --arg domain "$DISTRIBUTION_DOMAIN" \
  '.id == $id and .domain == $domain' <<<"$DISTRIBUTION_INFO" >/dev/null ||
  die "unexpected CloudFront distribution identity"
printf '%s' "$DISTRIBUTION_INFO" >>"$INVENTORY"
SITE_OAC_INFO="$(one 'site CloudFront' aws cloudfront list-origin-access-controls --query 'OriginAccessControlList.Items[?Name==`tollchat-v2-site-dev`].{id:Id,name:Name}' --output json)"
PUBLIC_CHAT_OAC_INFO="$(one 'public-chat CloudFront' aws cloudfront list-origin-access-controls --query 'OriginAccessControlList.Items[?Name==`tollchat-v2-public-chat-dev`].{id:Id,name:Name}' --output json)"
RESPONSE_HEADERS_INFO="$(one "response-headers CloudFront" aws cloudfront list-response-headers-policies --type custom --query 'ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name==`tollchat-v2-development-noindex`].{id:ResponseHeadersPolicy.Id,name:ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name}' --output json)"
WAF_INFO="$(one WAF aws wafv2 list-web-acls --scope CLOUDFRONT --query 'WebACLs[?Name==`tollchat-v2-public-chat-dev`].{id:Id,arn:ARN,name:Name}' --output json)"
WAF_ARN="$(jq -r '.arn' <<<"$WAF_INFO")"
aws wafv2 get-web-acl --scope CLOUDFRONT --id "$(jq -r '.id' <<<"$WAF_INFO")" \
  --name tollchat-v2-public-chat-dev --query 'WebACL.{id:Id,arn:ARN,name:Name}' --output json \
  >"$WORK_DIR/waf.json" || die "WAF ACL is unreadable"
aws wafv2 get-logging-configuration --resource-arn "$WAF_ARN" \
  >"$WORK_DIR/waf-logging.json" || die "WAF logging configuration is unreadable"

for bucket in \
  "tollchat-site-$EXPECTED_ACCOUNT-dev" \
  "aws-waf-logs-tollchat-agent-reports-$EXPECTED_ACCOUNT-dev" \
  "nova-toll-agentcore-$EXPECTED_ACCOUNT"; do
  aws s3api head-bucket --bucket "$bucket" >/dev/null || die "missing bucket $bucket"
done
MEASUREMENT_BUCKET="aws-waf-logs-tollchat-agent-reports-$EXPECTED_ACCOUNT-dev"
SITE_BUCKET="tollchat-site-$EXPECTED_ACCOUNT-dev"
aws s3api get-public-access-block --bucket "$MEASUREMENT_BUCKET" \
  >"$WORK_DIR/measurement-public-access-block.json" ||
  die "missing measurement public-access block"
aws s3api get-bucket-policy --bucket "$MEASUREMENT_BUCKET" \
  >"$WORK_DIR/measurement-bucket-policy.json" ||
  die "missing measurement bucket policy"
aws s3api get-public-access-block --bucket "$SITE_BUCKET" \
  >"$WORK_DIR/site-public-access-block.json" || die "missing site public-access block"
aws s3api get-bucket-policy --bucket "$SITE_BUCKET" \
  >"$WORK_DIR/site-bucket-policy.json" || die "missing site bucket policy"

aws athena get-named-query \
  --named-query-id 097b778f-c9ed-4bd9-af53-1e05770e1d53 \
  --query 'NamedQuery.{id:NamedQueryId,name:Name,workgroup:WorkGroup}' --output json \
  >"$WORK_DIR/named-query-top-routes.json"
jq -e '.id == "097b778f-c9ed-4bd9-af53-1e05770e1d53" and .workgroup == "tollchat-agent-reports-dev"' \
  "$WORK_DIR/named-query-top-routes.json" >/dev/null || die "wrong top-routes query"
aws athena get-named-query \
  --named-query-id 6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d \
  --query 'NamedQuery.{id:NamedQueryId,name:Name,workgroup:WorkGroup}' --output json \
  >"$WORK_DIR/named-query-recent-routes.json"
jq -e '.id == "6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d" and .workgroup == "tollchat-agent-reports-dev"' \
  "$WORK_DIR/named-query-recent-routes.json" >/dev/null || die "wrong recent-routes query"
aws athena get-work-group --work-group tollchat-agent-reports-dev \
  --query 'WorkGroup.{name:Name}' --output json >"$WORK_DIR/athena-workgroup.json" ||
  die "missing Athena workgroup"

for role in \
  toll-v2-pricing-loader-dev toll-v2-report-publisher-dev \
  toll-v2-report-publisher-scheduler-dev nova-toll-v2-timed-checks-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev \
  tollchat-v2-agent-usage-rollup-dev; do
  aws iam get-role --role-name "$role" --query 'Role.{name:RoleName,arn:Arn}' \
    --output json >"$WORK_DIR/role-$role.json" ||
    die "missing application role $role"
done
for role in \
  toll-v2-pricing-loader-dev toll-v2-report-publisher-dev \
  toll-v2-report-publisher-scheduler-dev nova-toll-v2-timed-checks-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev \
  tollchat-v2-agent-usage-rollup-dev; do
  aws iam list-role-policies --role-name "$role" --query PolicyNames --output json \
    >"$WORK_DIR/role-policies-$role.json" || die "cannot list inline policies for $role"
  aws iam list-attached-role-policies --role-name "$role" \
    --query 'AttachedPolicies[].PolicyArn' --output json \
    >"$WORK_DIR/role-attachments-$role.json" || die "cannot list attachments for $role"
done

for alias in alias/tollchat-v2-agent-measurement-dev alias/tollchat-v2-site-dev; do
  aws kms describe-key --key-id "$alias" --query 'KeyMetadata.{arn:Arn,id:KeyId}' \
    --output json >"$WORK_DIR/kms-${alias#alias/}.json" ||
    die "missing application KMS alias $alias"
done
for runtime_arn in \
  arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl \
  arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview; do
  aws bedrock-agentcore-control get-resource-policy --resource-arn "$runtime_arn" \
    >"$WORK_DIR/resource-policy-${runtime_arn##*/}.json" ||
    die "missing AgentCore resource policy $runtime_arn"
done
for endpoint_name in DEFAULT preview; do
  one "AgentCore log group $endpoint_name" aws logs describe-log-groups \
    --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-$endpoint_name" \
    --query 'logGroups[?logGroupName==`/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT` || logGroupName==`/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview`].{name:logGroupName,arn:arn}' \
    --output json >"$WORK_DIR/agentcore-log-group-$endpoint_name.json"
done
for security_group_name in \
  nova-toll-v2-pricing-loader-dev nova-toll-v2-report-publisher-dev \
  nova-toll-v2-agentcore-runtime-dev nova-toll-v2-chat-proxy-dev; do
  one "security group $security_group_name" aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$security_group_name" \
    --query 'SecurityGroups[].{id:GroupId,name:GroupName,vpc:VpcId}' --output json \
    >"$WORK_DIR/security-group-$security_group_name.json"
done
terraform -chdir="$ROOT/infra" init -input=false -backend-config=backend.development.hcl

canonicalize_json() {
  local input="$1" output="$2"
  python3 - "$input" "$output" <<'PY'
import json
import sys
import urllib.parse
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text())
if isinstance(value, str):
    value = json.loads(urllib.parse.unquote(value))
Path(sys.argv[2]).write_text(
    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
)
PY
  chmod 600 -- "$output"
}

render_document() {
  local expression="$1" output="$2" raw="$WORK_DIR/rendered-policy.raw"
  printf 'jsonencode(jsondecode(%s))\n' "$expression" |
    terraform -chdir="$ROOT/infra" console -var environment=development |
    tail -n 1 >"$raw"
  canonicalize_json "$raw" "$output"
}

decode_lambda_policy_response() {
  local raw="$1" output="$2"
  local policy_value="$WORK_DIR/lambda-policy-value.raw"
  local policy_document="$WORK_DIR/lambda-policy-document.json"
  jq -e '.Policy' "$raw" >"$policy_value" || return 1
  canonicalize_json "$policy_value" "$policy_document" || return 1
  jq -n --slurpfile document "$policy_document" '{PolicyDocument:$document[0]}' >"$output"
}

ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"
EXPECTED_TRUST="$WORK_DIR/expected-trust.json"
ACTUAL_TRUST="$WORK_DIR/actual-trust.json"
EXPECTED_POLICY_DIR="$WORK_DIR/expected-policies"
ACTUAL_POLICY_DIR="$WORK_DIR/actual-policies"
mkdir -p -- "$EXPECTED_POLICY_DIR" "$ACTUAL_POLICY_DIR"
declare -a EXPECTED_POLICY_KEYS=(state compute observability storage data runtime edge)
EXPECTED_POLICY_PATH="/nova-toll/v2/development/"
declare -A EXPECTED_POLICY_NAMES=()
declare -A EXPECTED_POLICY_ARNS=()
declare -A EXPECTED_POLICIES=()
declare -A ACTUAL_POLICIES=()
declare -A PREVIOUS_POLICIES=()
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  EXPECTED_POLICY_NAMES["$policy_key"]="$ROLE_NAME-$policy_key"
  EXPECTED_POLICY_ARNS["$policy_key"]="arn:aws:iam::$EXPECTED_ACCOUNT:policy${EXPECTED_POLICY_PATH}${EXPECTED_POLICY_NAMES[$policy_key]}"
  EXPECTED_POLICIES["$policy_key"]="$EXPECTED_POLICY_DIR/$policy_key.json"
  ACTUAL_POLICIES["$policy_key"]="$ACTUAL_POLICY_DIR/$policy_key.json"
done
ROLE_INFO="$WORK_DIR/delivery-role.json"
ROLE_POLICY_NAMES="$WORK_DIR/delivery-role-policies.json"
ROLE_ATTACHMENTS="$WORK_DIR/delivery-role-attachments.json"
ROLE_PRESENT=0
ROLE_CREATED=0
POLICY_NEEDS_ATTACH=0
MUTATION_AMBIGUOUS=0
declare -A STATE_PREEXISTING=()
declare -A STATE_IMPORTED_BY_THIS_RUN=()
declare -A POLICY_PRESENT=()
declare -A ATTACHMENT_CREATED_BY_THIS_RUN=()

render_document 'data.aws_iam_policy_document.development_delivery_assume.json' "$EXPECTED_TRUST" ||
  die "could not render expected delivery trust policy"
TRUST_SHA256="$(sha256sum "$EXPECTED_TRUST" | awk '{print $1}')"
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  render_document "local.development_delivery_policy_documents.${policy_key}" "${EXPECTED_POLICIES[$policy_key]}" ||
    die "could not render expected delivery managed policy: $policy_key"
done
POLICY_SHA256="$(for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  sha256sum "${EXPECTED_POLICIES[$policy_key]}" | awk '{print $1}'
done | sha256sum | awk '{print $1}')"
EXPECTED_POLICY_ARNS_JSON="$(printf '%s\n' "${EXPECTED_POLICY_KEYS[@]}" | jq -R -s --arg account "$EXPECTED_ACCOUNT" --arg path "$EXPECTED_POLICY_PATH" --arg role "$ROLE_NAME" 'split("\n") | map(select(length > 0) | ("arn:aws:iam::" + $account + ":policy" + $path + $role + "-" + .))')"

STATE_BUCKET="nova-toll-tfstate-${EXPECTED_ACCOUNT}"
LOCK_KEY="nova-toll/v2/development/bootstrap-lock"
LOCK_ARN="arn:aws:s3:::${STATE_BUCKET}/${LOCK_KEY}"
LOCK_TOKEN="$(od -An -N16 -tx1 /dev/urandom | tr -d '[:space:]')"
LOCK_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s' "$LOCK_TOKEN" | grep -Eq '^[0-9a-f]{32}$' || die "could not generate a random lock token"
LOCK_VALUE="${LOCK_TOKEN}|${LOCK_STARTED_AT}"
LOCK_BODY="$WORK_DIR/bootstrap-lock.body"
LOCK_PUT="$WORK_DIR/bootstrap-lock-put.json"
LOCK_HEAD="$WORK_DIR/bootstrap-lock-head.json"
LOCK_ETAG=""
LOCK_VERSION_ID=""
LOCK_ACQUIRED=0

acquire_bootstrap_lock() {
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES ||
    die "set BOOTSTRAP_APPROVED=YES before aws s3api put-object --region $REGION --bucket $STATE_BUCKET --key $LOCK_KEY --if-none-match '*' --body '<owner-token>|<utc-timestamp>' (target $LOCK_ARN)"
  printf '%s' "$LOCK_VALUE" >"$LOCK_BODY"
  chmod 600 -- "$LOCK_BODY"
  if ! aws s3api put-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    --body "$LOCK_BODY" --if-none-match '*' >"$LOCK_PUT" 2>"$WORK_DIR/bootstrap-lock-put.error"; then
    if grep -qiE 'PreconditionFailed|ConditionalRequestConflict|412|409' "$WORK_DIR/bootstrap-lock-put.error"; then
      die "bootstrap lock is already held at $LOCK_ARN; refusing overwrite, retry, or steal"
    fi
    if aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
      >"$WORK_DIR/bootstrap-lock-ambiguous.json" 2>/dev/null; then
      die "bootstrap lock acquisition result is ambiguous and the lock is present"
    fi
    die "bootstrap lock acquisition failed; refusing protected mutation"
  fi
  LOCK_ETAG="$(jq -er '.ETag | strings' "$LOCK_PUT")" || die "bootstrap lock response has no ETag"
  LOCK_VERSION_ID="$(jq -r '.VersionId // empty' "$LOCK_PUT")" || die "bootstrap lock response is malformed"
  test -n "$LOCK_ETAG" || die "bootstrap lock response has an empty ETag"
  lock_is_current || die "bootstrap lock owner changed during acquisition"
  LOCK_ACQUIRED=1
}

lock_is_current() {
  test -n "$LOCK_ETAG" || return 1
  aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    --query '{ETag:ETag,VersionId:VersionId}' --output json >"$LOCK_HEAD" 2>"$WORK_DIR/bootstrap-lock-head.error" || return 1
  jq -e --arg etag "$LOCK_ETAG" --arg version "$LOCK_VERSION_ID" \
    '.ETag == $etag and (.VersionId // "") == $version' "$LOCK_HEAD" >/dev/null
}

release_bootstrap_lock() {
  local status="${1:-0}"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return "$status"
  if test "$AWS_PROFILE" != "$EXPECTED_PROFILE" ||
    test "${AWS_REGION:-}" != "$REGION" ||
    test "${AWS_DEFAULT_REGION:-}" != "$REGION" ||
    test "$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" != "$EXPECTED_ACCOUNT"; then
    printf 'bootstrap lock release stopped: development account guard failed; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if ! lock_is_current; then
    printf 'bootstrap lock release stopped: current ETag/version does not match; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if test "${BOOTSTRAP_APPROVED:-}" != YES; then
    printf 'bootstrap lock release stopped: set BOOTSTRAP_APPROVED=YES before aws s3api delete-object --region %s --bucket %s --key %s --if-match %s (target %s)\n' \
      "$REGION" "$STATE_BUCKET" "$LOCK_KEY" "$LOCK_ETAG" "$LOCK_ARN" >&2
    return 1
  fi
  local -a delete_args=(aws s3api delete-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" --if-match "$LOCK_ETAG")
  test -n "$LOCK_VERSION_ID" && delete_args+=(--version-id "$LOCK_VERSION_ID")
  "${delete_args[@]}" >"$WORK_DIR/bootstrap-lock-delete.json" 2>"$WORK_DIR/bootstrap-lock-delete.error" || {
    printf 'bootstrap lock release failed; lock left in place (%s)\n' "$LOCK_ARN" >&2
    return 1
  }
  if aws s3api head-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" \
    >"$WORK_DIR/bootstrap-lock-after-delete.json" 2>"$WORK_DIR/bootstrap-lock-after-delete.error"; then
    printf 'bootstrap lock release could not verify absence; lock may remain (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  if ! grep -qiE 'Not Found|404|NoSuchKey' "$WORK_DIR/bootstrap-lock-after-delete.error"; then
    printf 'bootstrap lock release returned an unexpected verification response (%s)\n' "$LOCK_ARN" >&2
    return 1
  fi
  LOCK_ACQUIRED=0
  return "$status"
}

bootstrap_cleanup() {
  local status=$? release_status=0
  trap - EXIT
  if test "$status" -ne 0; then
    set +e
    if test "$MUTATION_AMBIGUOUS" -eq 0; then
      if declare -F rollback_created_role >/dev/null; then rollback_created_role; fi
      if test "$MUTATION_AMBIGUOUS" -eq 0 && test "$ROLE_CREATED" -eq 0 && declare -F rollback_created_attachments >/dev/null; then
        rollback_created_attachments || MUTATION_AMBIGUOUS=1
      fi
      if test "$MUTATION_AMBIGUOUS" -eq 0 && declare -F rollback_delivery_state >/dev/null; then
        rollback_delivery_state || MUTATION_AMBIGUOUS=1
      fi
      if test "$MUTATION_AMBIGUOUS" -ne 0; then
        printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
      fi
    else
      printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
    fi
    set -e
  fi
  release_bootstrap_lock "$status" || release_status=$?
  rm -rf -- "$WORK_DIR"
  test "$release_status" -eq 0 || status=1
  exit "$status"
}
trap bootstrap_cleanup EXIT

read_role() {
  aws iam get-role --role-name "$ROLE_NAME" --output json \
    >"$ROLE_INFO" 2>"$WORK_DIR/delivery-role.error" || return 1
  jq -e '.Role | type == "object" and .RoleName != null and .Arn != null and .Path != null' \
    "$ROLE_INFO" >/dev/null || return 1
  jq -c '.Role.AssumeRolePolicyDocument' "$ROLE_INFO" >"$WORK_DIR/actual-trust.raw"
  canonicalize_json "$WORK_DIR/actual-trust.raw" "$ACTUAL_TRUST"
}

role_identity_matches() {
  jq -e --arg role "$ROLE_NAME" --arg arn "$ROLE_ARN" \
    '.Role.RoleName == $role and .Role.Arn == $arn and .Role.Path == "/" and .Role.MaxSessionDuration == 3600 and (.Role.PermissionsBoundary? // null) == null' \
    "$ROLE_INFO" >/dev/null && cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"
}

read_policy_set() {
  aws iam list-role-policies --role-name "$ROLE_NAME" --output json >"$ROLE_POLICY_NAMES" || return 1
  aws iam list-attached-role-policies --role-name "$ROLE_NAME" --output json >"$ROLE_ATTACHMENTS" || return 1
  jq -e '(.PolicyNames | type == "array") and (.NextToken? // null) == null' "$ROLE_POLICY_NAMES" >/dev/null || return 1
    jq -e '(.AttachedPolicies | type == "array") and (.NextToken? // null) == null' "$ROLE_ATTACHMENTS" >/dev/null
}

policy_set_is_safe_subset() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e --argjson expected "$EXPECTED_POLICY_ARNS_JSON" \
      'all(.AttachedPolicies[]?.PolicyArn; . as $arn | ($expected | index($arn)) != null)' \
      "$ROLE_ATTACHMENTS" >/dev/null
}

read_managed_policy_inventory() {
  local policy_key policy_info="$WORK_DIR/managed-policy-info"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
      --output json >"$policy_info-$policy_key.json" 2>"$WORK_DIR/managed-policy-$policy_key.error"; then
      jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
        --arg name "${EXPECTED_POLICY_NAMES[$policy_key]}" --arg path "$EXPECTED_POLICY_PATH" \
        '.Policy | .Arn == $arn and .PolicyName == $name and .Path == $path and .DefaultVersionId != null' \
        "$policy_info-$policy_key.json" >/dev/null ||
        die "existing delivery managed policy identity does not match exactly: $policy_key"
      POLICY_PRESENT["$policy_key"]=1
    elif grep -qi 'NoSuchEntity' "$WORK_DIR/managed-policy-$policy_key.error"; then
      POLICY_PRESENT["$policy_key"]=0
    else
      die "could not inventory delivery managed policy: $policy_key"
    fi
  done
}

policy_set_is_empty() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e '.AttachedPolicies == []' "$ROLE_ATTACHMENTS" >/dev/null
}

policy_set_is_exact() {
  jq -e '.PolicyNames == []' "$ROLE_POLICY_NAMES" >/dev/null &&
    jq -e --argjson expected "$EXPECTED_POLICY_ARNS_JSON" '[.AttachedPolicies[]?.PolicyArn] | sort == ($expected | sort)' "$ROLE_ATTACHMENTS" >/dev/null
}

read_expected_policy() {
  local policy_key="$1" policy_info="$WORK_DIR/actual-policy-info-$1.json"
  local policy_version="$WORK_DIR/actual-policy-version-$1.raw" default_version
  aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --output json >"$policy_info" || return 1
  jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --arg name "${EXPECTED_POLICY_NAMES[$policy_key]}" --arg path "$EXPECTED_POLICY_PATH" \
    '.Policy | .Arn == $arn and .PolicyName == $name and .Path == $path and .DefaultVersionId != null' \
    "$policy_info" >/dev/null || return 1
  default_version="$(jq -er '.Policy.DefaultVersionId | strings' "$policy_info")" || return 1
  aws iam get-policy-version --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" \
    --version-id "$default_version" --query PolicyVersion.Document --output json >"$policy_version" || return 1
  canonicalize_json "$policy_version" "${ACTUAL_POLICIES[$policy_key]}" || return 1
}

read_expected_policies() {
  local policy_key
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    read_expected_policy "$policy_key" || return 1
  done
}

role_documents_match() {
  read_role && role_identity_matches && read_policy_set && policy_set_is_exact &&
    read_expected_policies || return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" || return 1
  done
}

rollback_created_attachments() {
  test "$ROLE_PRESENT" -eq 1 || test "$ROLE_CREATED" -eq 1 || return 0
  local policy_key attachment_present created=0
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1; then
      created=1
      break
    fi
  done
  test "$created" -eq 1 || return 0
  lock_is_current || die "refusing delivery attachment rollback after lock ownership changed"
  read_policy_set || die "cannot safely inspect delivery role for attachment rollback"
  policy_set_is_safe_subset || die "refusing rollback with unexpected inline policy or managed attachment"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1 || continue
    attachment_present="$(jq -r --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]? | select(.PolicyArn == $arn)] | length' "$ROLE_ATTACHMENTS")"
    if test "$attachment_present" -eq 1; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn ${EXPECTED_POLICY_ARNS[$policy_key]} (target $ROLE_ARN)"
      if ! aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"; then
        MUTATION_AMBIGUOUS=1
        printf 'delivery managed-policy detach failed; preserving exact policy for manual reconciliation: %s\n' "$policy_key" >&2
        return 1
      fi
    fi
  done
  read_policy_set && policy_set_is_safe_subset || {
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'delivery attachment rollback could not be verified; preserving role and policies for manual reconciliation' >&2
    return 1
  }
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    test "${ATTACHMENT_CREATED_BY_THIS_RUN[$policy_key]:-0}" -eq 1 || continue
    if jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]?.PolicyArn] | index($arn) != null' "$ROLE_ATTACHMENTS" >/dev/null; then
      MUTATION_AMBIGUOUS=1
      printf 'delivery attachment rollback could not verify absence; preserving role and policies for manual reconciliation: %s\n' "$policy_key" >&2
      return 1
    fi
  done
}

rollback_created_role() {
  test "$ROLE_CREATED" -eq 1 || return 0
  rollback_created_attachments || return 1
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam delete-role --role-name $ROLE_NAME (target $ROLE_ARN)"
  if ! aws iam delete-role --role-name "$ROLE_NAME"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'delivery role deletion failed; preserving role and policies for manual exact reconciliation' >&2
    return 1
  fi
  if aws iam get-role --role-name "$ROLE_NAME" \
    >"$WORK_DIR/rollback-role.json" 2>"$WORK_DIR/rollback-role.error"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'created delivery role remained after rollback' >&2
    return 1
  fi
  if ! grep -q 'NoSuchEntity' "$WORK_DIR/rollback-role.error"; then
    MUTATION_AMBIGUOUS=1
    printf '%s\n' 'could not verify created delivery role rollback' >&2
    return 1
  fi
  ROLE_CREATED=0
}

acquire_bootstrap_lock

state_list_contains() {
  local state_file="$1" address="$2"
  awk -v address="$address" '$0 == address { found=1 } END { exit found ? 0 : 1 }' "$state_file"
}
FOUNDATION_STATE_LIST="$WORK_DIR/foundation-state.list"
APPLICATION_STATE_LIST="$WORK_DIR/application-state.list"
terraform -chdir="$ROOT/v2/infra" init -input=false -backend-config=backend.development.hcl
terraform -chdir="$ROOT/infra" state list >"$FOUNDATION_STATE_LIST"
terraform -chdir="$ROOT/v2/infra" state list >"$APPLICATION_STATE_LIST"

if read_role; then
  ROLE_PRESENT=1
  role_identity_matches || die "pre-existing delivery role identity or trust does not match exactly"
elif grep -q 'NoSuchEntity' "$WORK_DIR/delivery-role.error"; then
  ROLE_PRESENT=0
else
  die "could not read delivery role"
fi
read_managed_policy_inventory
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  if test "${POLICY_PRESENT[$policy_key]}" -eq 1; then
    read_expected_policy "$policy_key" || die "existing delivery managed policy document is unreadable: $policy_key"
    cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" ||
      die "existing delivery managed policy document does not match exactly: $policy_key"
  fi
done

URL_PRESENT=1
if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  >"$WORK_DIR/function-url.json" 2>"$WORK_DIR/function-url.error"; then
  grep -q 'ResourceNotFoundException' "$WORK_DIR/function-url.error" || die "could not read Lambda URL config"
  URL_PRESENT=0
fi
POLICY_PRESENT=1
if ! aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  --output json >"$WORK_DIR/lambda-policy-raw.json" 2>"$WORK_DIR/lambda-permissions.error"; then
  grep -q 'ResourceNotFoundException' "$WORK_DIR/lambda-permissions.error" || die "could not read Lambda URL permissions"
  POLICY_PRESENT=0
else
  decode_lambda_policy_response "$WORK_DIR/lambda-policy-raw.json" "$WORK_DIR/lambda-permissions.json" ||
    die "Lambda URL permissions are not valid JSON"
fi
URL_PREEXISTING="$URL_PRESENT"
POLICY_PREEXISTING="$POLICY_PRESENT"

if test "$ROLE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam create-role --role-name $ROLE_NAME --path / --max-session-duration 3600 --assume-role-policy-document file://$EXPECTED_TRUST (target $ROLE_ARN)"
  aws iam create-role --role-name "$ROLE_NAME" --path / --max-session-duration 3600 \
    --assume-role-policy-document "file://$EXPECTED_TRUST" \
    >"$WORK_DIR/delivery-role-created.json" 2>"$WORK_DIR/delivery-role-create.error" || {
    MUTATION_AMBIGUOUS=1
    die "delivery role create failed; preserving any matching post-state for manual exact reconciliation"
  }
  if test "$ROLE_PRESENT" -eq 0; then
    ROLE_CREATED=1
    read_role && role_identity_matches || { rollback_created_role; die "created delivery role failed exact identity/trust validation"; }
    read_policy_set && policy_set_is_empty || { rollback_created_role; die "created delivery role has unexpected effective policies"; }
    POLICY_NEEDS_ATTACH=1
  fi
fi

if test "$ROLE_PRESENT" -eq 1 && test "$ROLE_CREATED" -eq 0; then
  read_policy_set || die "delivery role policy inventory is unreadable"
  policy_set_is_safe_subset || die "delivery role has unexpected inline policies or managed attachments"
  policy_set_is_exact || POLICY_NEEDS_ATTACH=1
fi

if test "$POLICY_NEEDS_ATTACH" -eq 1; then
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if test "${POLICY_PRESENT[$policy_key]}" -eq 0; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam create-policy --policy-name ${EXPECTED_POLICY_NAMES[$policy_key]} --path $EXPECTED_POLICY_PATH --policy-document file://${EXPECTED_POLICIES[$policy_key]} (target ${EXPECTED_POLICY_ARNS[$policy_key]})"
      aws iam create-policy --policy-name "${EXPECTED_POLICY_NAMES[$policy_key]}" --path "$EXPECTED_POLICY_PATH" \
        --policy-document "file://${EXPECTED_POLICIES[$policy_key]}" \
        >"$WORK_DIR/delivery-policy-${policy_key}-created.json" 2>"$WORK_DIR/delivery-policy-${policy_key}-create.error" || {
        MUTATION_AMBIGUOUS=1
        die "delivery managed policy create failed; preserving any matching post-state for manual exact reconciliation: $policy_key"
      }
      POLICY_PRESENT["$policy_key"]=1
      read_expected_policy "$policy_key" || die "created delivery managed policy is unreadable: $policy_key"
      cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}" ||
        die "created delivery managed policy document does not match exactly: $policy_key"
    fi
  done
  read_policy_set || die "delivery role policy inventory is unreadable before managed attachments"
  policy_set_is_safe_subset || die "delivery role changed before managed attachments"
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    if ! jq -e --arg arn "${EXPECTED_POLICY_ARNS[$policy_key]}" '[.AttachedPolicies[]?.PolicyArn] | index($arn) != null' "$ROLE_ATTACHMENTS" >/dev/null; then
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn ${EXPECTED_POLICY_ARNS[$policy_key]} (target $ROLE_ARN)"
      aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}" || {
        MUTATION_AMBIGUOUS=1
        die "delivery managed policy attachment failed; preserving any matching post-state for manual exact reconciliation: $policy_key"
      }
      ATTACHMENT_CREATED_BY_THIS_RUN["$policy_key"]=1
    fi
  done
  if ! role_documents_match; then
    if test "$ROLE_CREATED" -eq 0; then rollback_created_attachments; fi
    if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
    die "delivery role failed post-attachment exact effective-policy validation"
  fi
fi

role_documents_match || {
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  die "delivery role trust, identity policy, or effective policy set is not exact"
}

state_id_matches() {
  local state_file="$1" expected="$2"
  python3 - "$state_file" "$expected" <<'PY'
import re
import sys

state_file, expected = sys.argv[1:]
pattern = re.compile(r"^\s*id\s*=\s*\"" + re.escape(expected) + r"\"\s*$")
if any(pattern.fullmatch(line.rstrip("\n")) for line in open(state_file, encoding="utf-8")):
    raise SystemExit(0)
raise SystemExit(1)
PY
}
rollback_delivery_state() {
  local address target failed=0 state_list="$WORK_DIR/foundation-state-rollback.list"
  if test "${MUTATION_AMBIGUOUS:-0}" -ne 0; then
    printf 'state rollback stopped: ambiguous IAM mutation result preserved for manual reconciliation\n' >&2
    return 1
  fi
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  terraform -chdir="$ROOT/infra" state list >"$state_list" || return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    for kind in attachment policy; do
      if test "$kind" = policy; then
        address="aws_iam_policy.development_delivery[\"$policy_key\"]"
        target="${EXPECTED_POLICY_ARNS[$policy_key]}"
      else
        address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
        target="$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}"
      fi
      test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
      if state_list_contains "$state_list" "$address"; then
        if ! verify_foundation_state "$address" "$target" "$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"; then
          printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
          failed=1
          continue
        fi
        assert_dev_account
        test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra state rm $address (target $target)"
        if ! terraform -chdir="$ROOT/infra" state rm "$address"; then
          MUTATION_AMBIGUOUS=1
          printf 'delivery managed-policy state removal failed; preserving role and policies for manual exact reconciliation: %s\n' "$policy_key" >&2
          return 1
        fi
      fi
      STATE_IMPORTED_BY_THIS_RUN["$address"]=0
    done
  done
  address='aws_iam_role.development_delivery[0]'
  if test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1; then
    target="$ROLE_ARN"
    if state_list_contains "$state_list" "$address"; then
      if ! verify_foundation_state "$address" "$target" "$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"; then
        printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
        failed=1
      else
        assert_dev_account
        test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra state rm $address (target $target)"
        if ! terraform -chdir="$ROOT/infra" state rm "$address"; then
          MUTATION_AMBIGUOUS=1
          printf '%s\n' 'delivery role state removal failed; preserving role and policies for manual exact reconciliation' >&2
          return 1
        fi
      fi
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=0
  fi
  return "$failed"
}
verify_foundation_state() {
  local address="$1" identifier="$2" state_file="$3"
  terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$state_file" || return 1
  state_id_matches "$state_file" "$identifier" || return 1
  if test "$address" = 'aws_iam_role.development_delivery[0]'; then
    grep -Fxq "    arn                = \"$ROLE_ARN\"" "$state_file" ||
      grep -Fxq "    arn = \"$ROLE_ARN\"" "$state_file" || return 1
  fi
}

if state_list_contains "$FOUNDATION_STATE_LIST" 'aws_iam_role.development_delivery[0]'; then
  STATE_PREEXISTING['aws_iam_role.development_delivery[0]']=1
else
  role_documents_match || die "delivery role changed before state import"
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra import -input=false -var environment=development aws_iam_role.development_delivery[0] $ROLE_ARN (target $ROLE_ARN)"
  if ! terraform -chdir="$ROOT/infra" import -input=false \
    -var environment=development \
    'aws_iam_role.development_delivery[0]' "$ROLE_ARN" \
    >"$WORK_DIR/delivery-role-import.log" 2>&1; then
    if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/delivery-role-import.log"; then
      die "delivery role import is already managed or concurrent; refusing state removal"
    fi
    die "delivery role import failed; state ownership is unproven and was retained"
  fi
  STATE_IMPORTED_BY_THIS_RUN['aws_iam_role.development_delivery[0]']=1
  verify_foundation_state 'aws_iam_role.development_delivery[0]' "$ROLE_NAME" \
    "$WORK_DIR/delivery-role-import.state" ||
    die "delivery role import state ID or ARN is not the exact target"
fi
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  for kind in policy attachment; do
    if test "$kind" = policy; then
      address="aws_iam_policy.development_delivery[\"$policy_key\"]"
      target="${EXPECTED_POLICY_ARNS[$policy_key]}"
    else
      address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
      target="$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}"
    fi
    if state_list_contains "$FOUNDATION_STATE_LIST" "$address"; then
      STATE_PREEXISTING["$address"]=1
    else
      role_documents_match || die "delivery role changed before managed-policy state import: $policy_key"
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/infra import -input=false -var environment=development $address $target (target $target)"
      if ! terraform -chdir="$ROOT/infra" import -input=false \
        -var environment=development \
        "$address" "$target" \
        >"$WORK_DIR/delivery-${kind}-${policy_key}-import.log" 2>&1; then
        if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/delivery-${kind}-${policy_key}-import.log"; then
          die "delivery managed-policy import is already managed or concurrent; refusing state removal: $policy_key/$kind"
        fi
        die "delivery managed-policy import failed; state ownership is unproven and was retained: $policy_key/$kind"
      fi
      STATE_IMPORTED_BY_THIS_RUN["$address"]=1
      verify_foundation_state "$address" "$target" \
        "$WORK_DIR/delivery-${kind}-${policy_key}-import.state" ||
        die "delivery managed-policy import state ID is not the exact target: $policy_key/$kind"
    fi
  done
done
if ! role_documents_match; then
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "delivery role changed after foundation state imports; state rollback was not proven"
  fi
  die "delivery role changed after foundation state imports; imported state was rolled back"
fi

verify_delivery_state() {
  terraform -chdir="$ROOT/infra" state show -no-color \
    'aws_iam_role.development_delivery[0]' >"$WORK_DIR/delivery-role.state" ||
    return 1
  grep -Fxq "    id                 = \"$ROLE_NAME\"" "$WORK_DIR/delivery-role.state" ||
    grep -Fxq "    id = \"$ROLE_NAME\"" "$WORK_DIR/delivery-role.state" ||
    return 1
  grep -Fxq "    arn                = \"$ROLE_ARN\"" "$WORK_DIR/delivery-role.state" ||
    grep -Fxq "    arn = \"$ROLE_ARN\"" "$WORK_DIR/delivery-role.state" ||
    return 1
  for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
    address="aws_iam_policy.development_delivery[\"$policy_key\"]"
    terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$WORK_DIR/delivery-policy-${policy_key}.state" ||
      return 1
    grep -Fxq "    id                 = \"${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-policy-${policy_key}.state" ||
      grep -Fxq "    id = \"${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-policy-${policy_key}.state" ||
      return 1
    address="aws_iam_role_policy_attachment.development_delivery[\"$policy_key\"]"
    terraform -chdir="$ROOT/infra" state show -no-color "$address" >"$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      return 1
    grep -Fxq "    id                 = \"$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      grep -Fxq "    id = \"$ROLE_NAME/${EXPECTED_POLICY_ARNS[$policy_key]}\"" "$WORK_DIR/delivery-attachment-${policy_key}.state" ||
      return 1
  done
}
if ! verify_delivery_state; then
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "delivery Terraform state verification failed; state rollback was not proven"
  fi
  die "delivery Terraform state verification failed for the imported role/policy addresses"
fi

FOUNDATION_OUTPUT="$(terraform -chdir="$ROOT/infra" output -json foundation)" || {
  if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
  if ! rollback_delivery_state; then
    MUTATION_AMBIGUOUS=1
    die "development foundation output verification failed; state rollback was not proven"
  fi
  die "development foundation output verification failed; imported state was rolled back"
}
BOOTSTRAP_FOUNDATION_VARS="$WORK_DIR/foundation.tfvars.json"
jq -n --argjson foundation "$FOUNDATION_OUTPUT" '{foundation: $foundation}' >"$BOOTSTRAP_FOUNDATION_VARS"
QUALIFIED_FUNCTION_ARN="arn:aws:lambda:${REGION}:${EXPECTED_ACCOUNT}:function:${FUNCTION_NAME}:${QUALIFIER}"
CLOUDFRONT_SOURCE_ARN="arn:aws:cloudfront::${EXPECTED_ACCOUNT}:distribution/${DISTRIBUTION_ID}"
PREVIOUS_FUNCTION_URL="$WORK_DIR/previous-function-url.json"
PREVIOUS_LAMBDA_POLICY="$WORK_DIR/previous-lambda-policy.json"
URL_CREATED=0
URL_PERMISSION_URL_CREATED=0
URL_PERMISSION_INVOKE_CREATED=0
if test "$URL_PREEXISTING" -eq 1; then
  cp -- "$WORK_DIR/function-url.json" "$PREVIOUS_FUNCTION_URL"
fi
if test "$POLICY_PREEXISTING" -eq 1; then
  cp -- "$WORK_DIR/lambda-policy-raw.json" "$PREVIOUS_LAMBDA_POLICY"
fi
for snapshot in "$PREVIOUS_FUNCTION_URL" "$PREVIOUS_LAMBDA_POLICY"; do
  test -e "$snapshot" && chmod 600 -- "$snapshot"
done
EXPECTED_URL_PERMISSION="$WORK_DIR/expected-url-permission.json"
EXPECTED_INVOKE_PERMISSION="$WORK_DIR/expected-invoke-permission.json"
jq -n --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" \
  '{Sid:"AllowCloudFrontFunctionUrlV2",Effect:"Allow",Action:"lambda:InvokeFunctionUrl",Resource:$function_arn,Principal:{Service:"cloudfront.amazonaws.com"},Condition:{StringEquals:{"lambda:FunctionUrlAuthType":"AWS_IAM"},ArnLike:{"AWS:SourceArn":$source_arn}}}' \
  >"$EXPECTED_URL_PERMISSION"
jq -n --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" \
  '{Sid:"AllowCloudFrontFunctionInvokeV2",Effect:"Allow",Action:"lambda:InvokeFunction",Resource:$function_arn,Principal:{Service:"cloudfront.amazonaws.com"},Condition:{Bool:{"lambda:InvokedViaFunctionUrl":"true"},ArnLike:{"AWS:SourceArn":$source_arn}}}' \
  >"$EXPECTED_INVOKE_PERMISSION"
canonicalize_json "$EXPECTED_URL_PERMISSION" "$EXPECTED_URL_PERMISSION.canonical"
canonicalize_json "$EXPECTED_INVOKE_PERMISSION" "$EXPECTED_INVOKE_PERMISSION.canonical"
mv -- "$EXPECTED_URL_PERMISSION.canonical" "$EXPECTED_URL_PERMISSION"
mv -- "$EXPECTED_INVOKE_PERMISSION.canonical" "$EXPECTED_INVOKE_PERMISSION"
PERMISSION_POLICY_SNAPSHOT="$WORK_DIR/lambda-policy-before-all.json"
if test "$POLICY_PREEXISTING" -eq 1; then
  canonicalize_json "$WORK_DIR/lambda-permissions.json" "$PERMISSION_POLICY_SNAPSHOT"
fi

read_lambda_policy() {
  local output="$1" revision_output="$2" raw="$WORK_DIR/lambda-policy-read.raw"
  if aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --output json >"$raw" 2>"$WORK_DIR/lambda-policy-read.error"; then
    decode_lambda_policy_response "$raw" "$output" || return 1
    jq -e '(.RevisionId? // "") | type == "string"' "$raw" >/dev/null || return 1
    jq -r '.RevisionId // empty' "$raw" >"$revision_output"
  else
    grep -q 'ResourceNotFoundException' "$WORK_DIR/lambda-policy-read.error" || return 1
    printf '%s\n' '{"PolicyDocument":{"Statement":[]}}' >"$output"
    : >"$revision_output"
  fi
}

extract_lambda_statement() {
  local policy="$1" sid="$2" output="$3" raw="$WORK_DIR/lambda-statement.raw" count
  count="$(jq -r --arg sid "$sid" '[.PolicyDocument.Statement[]? | select(.Sid == $sid)] | length' "$policy")" || return 1
  test "$count" -le 1 || return 1
  if test "$count" -eq 1; then
    jq -c --arg sid "$sid" '.PolicyDocument.Statement[] | select(.Sid == $sid)' "$policy" >"$raw" || return 1
    canonicalize_json "$raw" "$output"
  else
    printf '%s\n' null >"$output"
  fi
}

validate_existing_lambda_policy() {
  jq -e --slurpfile url "$EXPECTED_URL_PERMISSION" --slurpfile invoke "$EXPECTED_INVOKE_PERMISSION" '
    .PolicyDocument.Statement as $statements |
    ($statements | type == "array" and length <= 2) and
    ([$statements[] | select(.Sid == "AllowCloudFrontFunctionUrlV2")] | length <= 1) and
    ([$statements[] | select(.Sid == "AllowCloudFrontFunctionInvokeV2")] | length <= 1) and
    all($statements[]; . == $url[0] or . == $invoke[0])
  ' "$WORK_DIR/lambda-permissions.json" >/dev/null
}

snapshot_lambda_permission() {
  local sid="$1" stem="$2" policy="$WORK_DIR/lambda-policy-before-$stem.json"
  local revision="$WORK_DIR/lambda-revision-before-$stem.txt"
  local statement="$WORK_DIR/lambda-statement-before-$stem.json" present=0
  read_lambda_policy "$policy" "$revision" || die "could not snapshot Lambda permission policy before $sid"
  extract_lambda_statement "$policy" "$sid" "$statement" || die "Lambda permission SID snapshot is ambiguous: $sid"
  jq -e 'type == "object"' "$statement" >/dev/null && present=1
  printf -v "${stem}_PRE_PRESENT" '%s' "$present"
  printf -v "${stem}_PRE_REVISION" '%s' "$(<"$revision")"
  printf -v "${stem}_PRE_STATEMENT" '%s' "$statement"
}

reconcile_lambda_permission() {
  local sid="$1" stem="$2" expected="$3"
  local policy="$WORK_DIR/lambda-policy-after-$stem.json"
  local revision="$WORK_DIR/lambda-revision-after-$stem.txt"
  local statement="$WORK_DIR/lambda-statement-after-$stem.json"
  local pre_present_var="${stem}_PRE_PRESENT" pre_revision_var="${stem}_PRE_REVISION"
  local pre_present="${!pre_present_var}" pre_revision="${!pre_revision_var}" post_revision
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  read_lambda_policy "$policy" "$revision" || return 1
  extract_lambda_statement "$policy" "$sid" "$statement" || return 1
  cmp -s "$expected" "$statement" || return 1
  test "$pre_present" -eq 0 || return 2
  post_revision="$(<"$revision")"
  if test -n "$pre_revision"; then
    test -n "$post_revision" || return 3
    test "$post_revision" != "$pre_revision" || return 3
  fi
  printf -v "${stem}_CREATED" '%s' 1
  return 0
}

validate_function_url() {
  local document="${1:-$WORK_DIR/function-url.json}"
  jq -e --arg function_arn "$QUALIFIED_FUNCTION_ARN" \
    '.AuthType == "AWS_IAM" and .InvokeMode == "RESPONSE_STREAM" and .FunctionArn == $function_arn' \
    "$document" >/dev/null
}
validate_lambda_policy() {
  jq -e --arg function_arn "$QUALIFIED_FUNCTION_ARN" --arg source_arn "$CLOUDFRONT_SOURCE_ARN" '
    .PolicyDocument as $policy |
    ($policy.Statement | (type == "array" and length == 2)) and
    any($policy.Statement[];
      .Sid == "AllowCloudFrontFunctionUrlV2" and
      .Effect == "Allow" and
      .Action == "lambda:InvokeFunctionUrl" and
      .Resource == $function_arn and
      .Principal == {Service: "cloudfront.amazonaws.com"} and
      .Condition.StringEquals."lambda:FunctionUrlAuthType" == "AWS_IAM" and
      ((.Condition.ArnLike."AWS:SourceArn" // .Condition.StringEquals."AWS:SourceArn") == $source_arn)) and
    any($policy.Statement[];
      .Sid == "AllowCloudFrontFunctionInvokeV2" and
      .Effect == "Allow" and
      .Action == "lambda:InvokeFunction" and
      .Resource == $function_arn and
      .Principal == {Service: "cloudfront.amazonaws.com"} and
      .Condition.Bool."lambda:InvokedViaFunctionUrl" == "true" and
      ((.Condition.ArnLike."AWS:SourceArn" // .Condition.StringEquals."AWS:SourceArn") == $source_arn))
  ' "$WORK_DIR/lambda-permissions.json" >/dev/null
}
verify_owned_lambda_permission() {
  local sid="$1" expected="$2"
  local current_policy="$WORK_DIR/lambda-permission-owned-check.json"
  local current_revision="$WORK_DIR/lambda-permission-owned-revision.txt"
  local current_statement="$WORK_DIR/lambda-permission-owned-statement.json"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  read_lambda_policy "$current_policy" "$current_revision" || return 1
  extract_lambda_statement "$current_policy" "$sid" "$current_statement" || return 1
  cmp -s "$expected" "$current_statement"
}
rollback_created_url() {
  local removed=0 current_policy="$WORK_DIR/lambda-policy-rollback.json" current_revision="$WORK_DIR/lambda-revision-rollback.txt"
  test "$URL_PERMISSION_INVOKE_CREATED" -eq 1 && {
    verify_owned_lambda_permission AllowCloudFrontFunctionInvokeV2 "$EXPECTED_INVOKE_PERMISSION" ||
      die "refusing Lambda invoke permission rollback after ownership changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda remove-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionInvokeV2 (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda remove-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --statement-id AllowCloudFrontFunctionInvokeV2
    URL_PERMISSION_INVOKE_CREATED=0
    removed=1
  }
  test "$URL_PERMISSION_URL_CREATED" -eq 1 && {
    verify_owned_lambda_permission AllowCloudFrontFunctionUrlV2 "$EXPECTED_URL_PERMISSION" ||
      die "refusing Lambda URL permission rollback after ownership changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda remove-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionUrlV2 (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda remove-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --statement-id AllowCloudFrontFunctionUrlV2
    URL_PERMISSION_URL_CREATED=0
    removed=1
  }
  if test "$removed" -eq 1; then
    if test "$POLICY_PREEXISTING" -eq 1; then
      read_lambda_policy "$current_policy" "$current_revision" || die "cannot verify Lambda permission rollback"
      canonicalize_json "$current_policy" "$current_policy.canonical"
      cmp -s "$PERMISSION_POLICY_SNAPSHOT" "$current_policy.canonical" ||
        die "Lambda rollback changed a pre-existing or concurrent permission statement"
    elif aws lambda get-policy --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      --output json >"$WORK_DIR/rollback-lambda-policy-raw.json" 2>"$WORK_DIR/rollback-lambda-policy.error"; then
      die "rollback found an unexpected Lambda permission policy"
    else
      grep -q 'ResourceNotFoundException' "$WORK_DIR/rollback-lambda-policy.error" ||
        die "cannot verify absent Lambda permission policy after rollback"
    fi
  fi
  test "$URL_CREATED" -eq 1 && {
    lock_is_current || die "refusing Lambda URL rollback after lock ownership changed"
    aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      >"$WORK_DIR/rollback-function-url-current.json" 2>"$WORK_DIR/rollback-function-url-current.error" ||
      die "cannot verify Lambda URL before rollback"
    validate_function_url "$WORK_DIR/rollback-function-url-current.json" ||
      die "refusing Lambda URL rollback after its auth, invoke mode, or function identity changed"
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda delete-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER (target $QUALIFIED_FUNCTION_ARN)"
    aws lambda delete-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER"
    URL_CREATED=0
    if aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
      >"$WORK_DIR/rollback-function-url.json" 2>"$WORK_DIR/rollback-function-url.error"; then
      die "new Lambda URL remained after rollback"
    fi
    grep -q 'ResourceNotFoundException' "$WORK_DIR/rollback-function-url.error" ||
      die "cannot verify Lambda URL rollback"
  }
}
BOOTSTRAP_COMPLETE=0
cleanup_on_failure() {
  local status=$?
  trap - EXIT
  if test "$status" -ne 0 && test "$BOOTSTRAP_COMPLETE" -eq 0; then
    set +e
    if test "$MUTATION_AMBIGUOUS" -eq 0; then
      if declare -F rollback_url_state >/dev/null; then rollback_url_state; fi
      rollback_created_url
      if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi
      if test "$MUTATION_AMBIGUOUS" -eq 0; then
        rollback_delivery_state || MUTATION_AMBIGUOUS=1
      fi
    else
      printf 'bootstrap cleanup stopped: ambiguous mutation result preserved for manual reconciliation\n' >&2
    fi
    set -e
  fi
  if ! release_bootstrap_lock "$status"; then status=1; fi
  rm -rf -- "$WORK_DIR"
  exit "$status"
}
trap cleanup_on_failure EXIT
if test "$POLICY_PRESENT" -eq 1; then
  validate_existing_lambda_policy || die "Lambda URL permissions contain an unexpected or duplicate statement"
fi
if test "$URL_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES ||
    die "set BOOTSTRAP_APPROVED=YES before aws lambda create-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER --auth-type AWS_IAM --invoke-mode RESPONSE_STREAM (target $QUALIFIED_FUNCTION_ARN)"
  if ! aws lambda create-function-url-config --function-name "$FUNCTION_NAME" \
    --qualifier "$QUALIFIER" --auth-type AWS_IAM --invoke-mode RESPONSE_STREAM \
    >"$WORK_DIR/function-url-created.json" 2>"$WORK_DIR/function-url-create.error"; then
    MUTATION_AMBIGUOUS=1
    die "Lambda URL create failed; preserving any matching post-state for manual exact reconciliation"
  fi
  URL_CREATED=1
  URL_PRESENT=1
fi
aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
  >"$WORK_DIR/function-url.json" || { rollback_created_url; die "Lambda URL config is unreadable after bootstrap"; }
validate_function_url || { rollback_created_url; die "Lambda URL auth, invoke mode, or function identity is not the reviewed value"; }
snapshot_lambda_permission AllowCloudFrontFunctionUrlV2 URL_PERMISSION_URL
if test "$URL_PERMISSION_URL_PRE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionUrlV2 --action lambda:InvokeFunctionUrl --principal cloudfront.amazonaws.com --source-arn $CLOUDFRONT_SOURCE_ARN (target $QUALIFIED_FUNCTION_ARN)"
  URL_PERMISSION_ADD=(aws lambda add-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --statement-id AllowCloudFrontFunctionUrlV2 --action lambda:InvokeFunctionUrl \
    --principal cloudfront.amazonaws.com \
    --source-arn "$CLOUDFRONT_SOURCE_ARN" \
    --function-url-auth-type AWS_IAM)
  test -n "$URL_PERMISSION_URL_PRE_REVISION" && URL_PERMISSION_ADD+=(--revision-id "$URL_PERMISSION_URL_PRE_REVISION")
  if "${URL_PERMISSION_ADD[@]}" >"$WORK_DIR/url-permission-add.json" 2>"$WORK_DIR/url-permission-add.error"; then
    reconcile_lambda_permission AllowCloudFrontFunctionUrlV2 URL_PERMISSION_URL "$EXPECTED_URL_PERMISSION" || {
      rollback_created_url
      die "Lambda URL permission response was not the exact newly-owned statement"
    }
  else
    MUTATION_AMBIGUOUS=1
    die "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
  fi
fi
snapshot_lambda_permission AllowCloudFrontFunctionInvokeV2 URL_PERMISSION_INVOKE
if test "$URL_PERMISSION_INVOKE_PRE_PRESENT" -eq 0; then
  assert_dev_account
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER --statement-id AllowCloudFrontFunctionInvokeV2 --action lambda:InvokeFunction --principal cloudfront.amazonaws.com --source-arn $CLOUDFRONT_SOURCE_ARN (target $QUALIFIED_FUNCTION_ARN)"
  INVOKE_PERMISSION_ADD=(aws lambda add-permission --function-name "$FUNCTION_NAME" --qualifier "$QUALIFIER" \
    --statement-id AllowCloudFrontFunctionInvokeV2 --action lambda:InvokeFunction \
    --principal cloudfront.amazonaws.com \
    --source-arn "$CLOUDFRONT_SOURCE_ARN" \
    --invoked-via-function-url)
  test -n "$URL_PERMISSION_INVOKE_PRE_REVISION" && INVOKE_PERMISSION_ADD+=(--revision-id "$URL_PERMISSION_INVOKE_PRE_REVISION")
  if "${INVOKE_PERMISSION_ADD[@]}" >"$WORK_DIR/invoke-permission-add.json" 2>"$WORK_DIR/invoke-permission-add.error"; then
    reconcile_lambda_permission AllowCloudFrontFunctionInvokeV2 URL_PERMISSION_INVOKE "$EXPECTED_INVOKE_PERMISSION" || {
      rollback_created_url
      die "Lambda invoke permission response was not the exact newly-owned statement"
    }
  else
    MUTATION_AMBIGUOUS=1
    die "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
  fi
fi
read_lambda_policy "$WORK_DIR/lambda-permissions.json" "$WORK_DIR/lambda-policy-revision.txt" ||
  { rollback_created_url; die "Lambda URL permissions are unreadable after bootstrap"; }
validate_lambda_policy || { rollback_created_url; die "Lambda URL permissions are not the two reviewed CloudFront statements"; }
POLICY_PRESENT=1
rollback_url_state() {
  local address target failed=0 state_file state_list="$WORK_DIR/application-state-rollback.list"
  test "${LOCK_ACQUIRED:-0}" -eq 1 || return 1
  lock_is_current || return 1
  terraform -chdir="$ROOT/v2/infra" state list >"$state_list" || return 1
  for address in \
    'aws_lambda_permission.public_chat_invoke' \
    'aws_lambda_permission.public_chat_url' \
    'aws_lambda_function_url.public_chat'; do
    case "$address" in
      aws_lambda_permission.public_chat_invoke)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2"
        ;;
      aws_lambda_permission.public_chat_url)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2"
        ;;
      aws_lambda_function_url.public_chat)
        test "${STATE_IMPORTED_BY_THIS_RUN["$address"]:-0}" -eq 1 || continue
        target="$FUNCTION_NAME,$QUALIFIER"
        ;;
    esac
    if state_list_contains "$state_list" "$address"; then
      state_file="$WORK_DIR/rollback-${address//[^A-Za-z0-9]/_}.state"
      if ! terraform -chdir="$ROOT/v2/infra" state show -no-color "$address" >"$state_file" ||
        ! state_id_matches "$state_file" "$target"; then
        printf 'refusing rollback of %s: current state ID is not the exact target %s\n' "$address" "$target" >&2
        failed=1
        continue
      fi
      assert_dev_account
      test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/v2/infra state rm $address (target $target)"
      terraform -chdir="$ROOT/v2/infra" state rm "$address"
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=0
  done
  return "$failed"
}
import_url_state() {
  local address="$1" identifier="$2" label="$3"
  if ! state_list_contains "$APPLICATION_STATE_LIST" "$address"; then
    assert_dev_account
    test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before terraform -chdir=$ROOT/v2/infra import -input=false $address $identifier (target $identifier)"
    if ! terraform -chdir="$ROOT/v2/infra" import -input=false \
      -var-file=development.tfvars -var-file="$BOOTSTRAP_FOUNDATION_VARS" \
      "$address" "$identifier" >"$WORK_DIR/${label// /-}-import.log" 2>&1; then
      if grep -qiE 'already managed|already exists|state.*managed' "$WORK_DIR/${label// /-}-import.log"; then
        die "$label import is already managed or concurrent; refusing state removal"
      fi
      die "$label import failed; state ownership is unproven and was retained"
    fi
    STATE_IMPORTED_BY_THIS_RUN["$address"]=1
  else
    STATE_PREEXISTING["$address"]=1
  fi
  if ! terraform -chdir="$ROOT/v2/infra" state show -no-color "$address" >"$WORK_DIR/${label// /-}.state"; then
    die "$label state verification failed"
  fi
  state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier" ||
    die "$label Terraform state ID does not match exact target $identifier"
}
import_url_state 'aws_lambda_function_url.public_chat' "$FUNCTION_NAME,$QUALIFIER" \
  'Lambda URL'
import_url_state 'aws_lambda_permission.public_chat_url' "$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2" \
  'Lambda URL permission'
import_url_state 'aws_lambda_permission.public_chat_invoke' "$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2" \
  'Lambda invoke permission'

ADDRESS_INVENTORY="$EVIDENCE_DIR/terraform-addresses.tsv"
printf 'terraform_address\tlive_identifier\n' >"$ADDRESS_INVENTORY"
printf 'aws_api_gateway_rest_api.tollchat\tocw8sg0wlb\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrock_guardrail.tollchat\tvdyqrh31xgca\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_agent_runtime.tollchat\tnova_toll_v2_development-Y69XBf88Bl\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_agent_runtime_endpoint.tollchat\tpreview\n' >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_resource_policy.tollchat["runtime"]\t%s\n' "$(jq -r '.runtime.arn' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_bedrockagentcore_resource_policy.tollchat["endpoint"]\t%s\n' "$(jq -r '.endpoint.arn' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudwatch_log_group.agentcore_runtime["DEFAULT"]\t%s\n' "$(jq -r '.arn' "$WORK_DIR/agentcore-log-group-DEFAULT.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudwatch_log_group.agentcore_runtime["preview"]\t%s\n' "$(jq -r '.arn' "$WORK_DIR/agentcore-log-group-preview.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_function_url.public_chat\t%s,%s\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_permission.public_chat_url\t%s,%s,AllowCloudFrontFunctionUrlV2\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_lambda_permission.public_chat_invoke\t%s,%s,AllowCloudFrontFunctionInvokeV2\n' "$FUNCTION_NAME" "$QUALIFIER" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_distribution.site\t%s\n' "$(jq -r '.distribution.id' "$INVENTORY")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_origin_access_control.site\t%s\n' "$(jq -r '.id' <<<"$SITE_OAC_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_origin_access_control.public_chat\t%s\n' "$(jq -r '.id' <<<"$PUBLIC_CHAT_OAC_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_cloudfront_response_headers_policy.development_noindex\t%s\n' "$(jq -r '.id' <<<"$RESPONSE_HEADERS_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_wafv2_web_acl.public_chat\t%s\n' "$(jq -r '.arn' <<<"$WAF_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_wafv2_web_acl_logging_configuration.agent_reports\t%s\n' "$(jq -r '.arn' <<<"$WAF_INFO")" >>"$ADDRESS_INVENTORY"
printf 'aws_iam_role.development_delivery[0]\t%s\n' "$ROLE_ARN" >>"$ADDRESS_INVENTORY"
for policy_key in "${EXPECTED_POLICY_KEYS[@]}"; do
  printf 'aws_iam_policy.development_delivery["%s"]\t%s\n' \
    "$policy_key" "${EXPECTED_POLICY_ARNS[$policy_key]}" >>"$ADDRESS_INVENTORY"
  printf 'aws_iam_role_policy_attachment.development_delivery["%s"]\t%s/%s\n' \
    "$policy_key" "$ROLE_NAME" "${EXPECTED_POLICY_ARNS[$policy_key]}" >>"$ADDRESS_INVENTORY"
done
printf 'aws_kms_alias.agent_measurement\talias/tollchat-v2-agent-measurement-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_kms_alias.site\talias/tollchat-v2-site-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket.agent_measurement\taws-waf-logs-tollchat-agent-reports-%s-dev\n' "$EXPECTED_ACCOUNT" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket.site\ttollchat-site-%s-dev\n' "$EXPECTED_ACCOUNT" >>"$ADDRESS_INVENTORY"
for role_mapping in \
  'loader toll-v2-pricing-loader-dev' \
  'publisher toll-v2-report-publisher-dev' \
  'publisher_scheduler toll-v2-report-publisher-scheduler-dev' \
  'timed_checks nova-toll-v2-timed-checks-dev' \
  'tollchat_runtime nova-toll-v2-agentcore-runtime-dev' \
  'tollchat_proxy nova-toll-v2-chat-proxy-dev' \
  'agent_usage_rollup tollchat-v2-agent-usage-rollup-dev'; do
  IFS=' ' read -r address role_name <<<"$role_mapping"
  printf 'aws_iam_role.%s\tarn:aws:iam::%s:role/%s\n' "$address" "$EXPECTED_ACCOUNT" "$role_name" >>"$ADDRESS_INVENTORY"
done
for policy_mapping in \
  'loader toll-v2-pricing-loader-dev toll-v2-pricing-loader-dev' \
  'publisher toll-v2-report-publisher-dev toll-v2-report-publisher-dev' \
  'publisher_scheduler toll-v2-report-publisher-scheduler-dev toll-v2-report-publisher-scheduler-dev' \
  'timed_checks nova-toll-v2-timed-checks-dev nova-toll-v2-route-live-checks-dev' \
  'tollchat_runtime nova-toll-v2-agentcore-runtime-dev nova-toll-v2-agentcore-runtime-dev' \
  'tollchat_proxy nova-toll-v2-chat-proxy-dev nova-toll-v2-chat-proxy-dev' \
  'agent_usage_rollup tollchat-v2-agent-usage-rollup-dev tollchat-v2-agent-usage-rollup-dev'; do
  IFS=' ' read -r address role_name policy_name <<<"$policy_mapping"
  printf 'aws_iam_role_policy.%s\t%s:%s\n' "$address" "$role_name" "$policy_name" >>"$ADDRESS_INVENTORY"
done
for attachment_mapping in \
  'loader_vpc toll-v2-pricing-loader-dev' \
  'publisher_vpc toll-v2-report-publisher-dev' \
  'tollchat_proxy_vpc nova-toll-v2-chat-proxy-dev'; do
  IFS=' ' read -r address role_name <<<"$attachment_mapping"
  printf 'aws_iam_role_policy_attachment.%s\t%s/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole\n' "$address" "$role_name" >>"$ADDRESS_INVENTORY"
done
printf 'aws_athena_named_query.top_routes\t097b778f-c9ed-4bd9-af53-1e05770e1d53\n' >>"$ADDRESS_INVENTORY"
printf 'aws_athena_named_query.recent_routes\t6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d\n' >>"$ADDRESS_INVENTORY"
printf 'aws_athena_workgroup.agent_reports\ttollchat-agent-reports-dev\n' >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_public_access_block.agent_measurement\t%s\n' "$MEASUREMENT_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_policy.agent_measurement\t%s\n' "$MEASUREMENT_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_public_access_block.site\t%s\n' "$SITE_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_s3_bucket_policy.site\t%s\n' "$SITE_BUCKET" >>"$ADDRESS_INVENTORY"
printf 'aws_kms_key.agent_measurement\t%s\n' "$(jq -r '.arn' "$WORK_DIR/kms-tollchat-v2-agent-measurement-dev.json")" >>"$ADDRESS_INVENTORY"
printf 'aws_kms_key.site\t%s\n' "$(jq -r '.arn' "$WORK_DIR/kms-tollchat-v2-site-dev.json")" >>"$ADDRESS_INVENTORY"

printf ',\n  "site_oac": %s,\n  "public_chat_oac": %s,\n  "response_headers_policy": %s,\n  "waf": %s,\n  "delivery_role_present": %s,\n  "function_url_present": %s,\n  "permission_policy_present": %s\n' \
  "$SITE_OAC_INFO" "$PUBLIC_CHAT_OAC_INFO" "$RESPONSE_HEADERS_INFO" "$WAF_INFO" \
  "$ROLE_PRESENT" "$URL_PRESENT" "$POLICY_PRESENT" >>"$INVENTORY"
printf ',\n  "reviewed_commit": "%s",\n  "fetcher_sha256": "%s",\n  "delivery_trust_sha256": "%s",\n  "delivery_policy_sha256": "%s"\n' \
  "$REVIEWED_COMMIT" "$FETCHER_SHA256" "$TRUST_SHA256" "$POLICY_SHA256" >>"$INVENTORY"
printf '%s\n' '}' >>"$INVENTORY"
jq -e '.account == "903859731897"' "$INVENTORY" >/dev/null

require_external_file() {
  local path="$1"
  case "$path" in
    /*) ;;
    *) die "evidence input must be an absolute path" ;;
  esac
  test -f "$path" && test ! -L "$path" || die "evidence input must be a regular non-symlink file"
  case "$(realpath -m -- "$path")" in "$ROOT"|"$ROOT"/*) die "evidence input must be outside checkout" ;; esac
}

run_iam_simulation() {
  local label="$1" action="$2" resource="$3" expected="$4" raw decision
  local -a context_args=()
  case "$label" in
    runtime-role-pass|unrelated-runtime-role-pass|role-pass) context_args=(
      --context-entries ContextKeyName=iam:PassedToService,ContextKeyValues=bedrock-agentcore.amazonaws.com,ContextKeyType=string
    ) ;;
    runtime-role-wrong-service) context_args=(
      --context-entries ContextKeyName=iam:PassedToService,ContextKeyValues=lambda.amazonaws.com,ContextKeyType=string
    ) ;;
    alias-list|managed-cache-read|managed-origin-read) context_args=(
      --context-entries ContextKeyName=aws:RequestedRegion,ContextKeyValues=us-east-1,ContextKeyType=string
    ) ;;
    alias-list-wrong-region) context_args=(
      --context-entries ContextKeyName=aws:RequestedRegion,ContextKeyValues=us-west-2,ContextKeyType=string
    ) ;;
    kms-*) context_args=(
      --context-entries
      ContextKeyName=aws:ResourceTag/environment,ContextKeyValues=development,ContextKeyType=string
      ContextKeyName=aws:ResourceTag/version,ContextKeyValues=v2,ContextKeyType=string
    ) ;;
  esac
  raw="$WORK_DIR/iam-simulation-$label.json"
  assert_dev_account
  aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" \
    --action-names "$action" --resource-arns "$resource" "${context_args[@]}" --output json >"$raw" ||
    die "IAM simulation failed: $label"
  jq -e '.EvaluationResults | type == "array" and length == 1' "$raw" >/dev/null ||
    die "IAM simulation result is missing or ambiguous: $label"
  decision="$(jq -r '.EvaluationResults[0].EvalDecision' "$raw")"
  if test "$expected" = allowed; then
    test "$decision" = allowed || die "expected IAM allow was not returned: $label"
  else
    case "$decision" in explicitDeny|implicitDeny) ;; *) die "expected IAM deny was not returned: $label" ;; esac
  fi
  jq -cn --arg label "$label" --arg action "$action" --arg resource "$resource" \
    --arg expected "$expected" --arg decision "$decision" \
    '{label:$label,action:$action,resource:$resource,expected:$expected,decision:$decision}' >>"$IAM_SIMULATION_LINES"
}

run_post_bootstrap_gates() {
  test "${BOOTSTRAP_APPROVED:-}" = YES || die "set BOOTSTRAP_APPROVED=YES before post-bootstrap gates"
  IAM_SIMULATION_LINES="$WORK_DIR/iam-simulation-lines.jsonl"
  IAM_SIMULATION_EVIDENCE="$EVIDENCE_DIR/iam-simulations.json"
  test ! -e "$IAM_SIMULATION_EVIDENCE" || die "refusing to overwrite IAM simulation evidence"
  : >"$IAM_SIMULATION_LINES"
  # API deployment DELETE and Glue catalog tag simulations have unresolved
  # resource-pair denials. Keep this gate fail-closed; do not widen IAM for them.
  SIMULATION_EXPECTED_COUNT=126
  SIMULATION_MATRIX="$WORK_DIR/iam-simulation-matrix.tsv"
  cat >"$SIMULATION_MATRIX" <<EOF
state-foundation-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/development/terraform.tfstate|allowed
state-application-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate|allowed
state-application-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate|allowed
state-lock-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
state-lock-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
state-lock-delete|s3:DeleteObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/v2/development/terraform.tfstate.tflock|allowed
lambda-code|lambda:UpdateFunctionCode|$QUALIFIED_FUNCTION_ARN|allowed
lambda-version|lambda:PublishVersion|arn:aws:lambda:${REGION}:${EXPECTED_ACCOUNT}:function:${FUNCTION_NAME}|allowed
lambda-alias|lambda:UpdateAlias|$QUALIFIED_FUNCTION_ARN|allowed
lambda-retire|lambda:DeleteFunction|$QUALIFIED_FUNCTION_ARN|allowed
site-upload|s3:PutObject|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|allowed
site-delete|s3:DeleteObject|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|denied
artifact-upload|s3:PutObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
artifact-delete|s3:DeleteObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
cloudfront-update|cloudfront:UpdateFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-publish|cloudfront:PublishFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
guardrail-version|bedrock:CreateGuardrailVersion|arn:aws:bedrock:${REGION}:${EXPECTED_ACCOUNT}:guardrail/vdyqrh31xgca|allowed
api-deployment-create|apigateway:POST|arn:aws:apigateway:${REGION}::/restapis/ocw8sg0wlb/deployments|allowed
api-deployment-delete|apigateway:DELETE|arn:aws:apigateway:${REGION}::/restapis/ocw8sg0wlb/deployments/reviewed|allowed
agentcore-runtime-update|bedrock-agentcore:UpdateAgentRuntime|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
agentcore-endpoint-update|bedrock-agentcore:UpdateAgentRuntimeEndpoint|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl/runtime-endpoint/preview|allowed
events-targets|events:PutTargets|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|allowed
logs-retention|logs:PutRetentionPolicy|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
alarm-tags|cloudwatch:TagResource|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|allowed
queue-read|sqs:GetQueueAttributes|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|allowed
athena-read|athena:GetNamedQuery|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
workgroup-update|athena:UpdateWorkGroup|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
sessions-update|dynamodb:UpdateTable|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
catalog-update|glue:UpdateTable|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/*|allowed
schedule-update|scheduler:UpdateSchedule|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule/default/toll-v2-report-publisher-dev|allowed
kms-use|kms:Encrypt|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
site-ownership|s3:PutBucketOwnershipControls|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-tags|s3:PutBucketTagging|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-versioning|s3:PutBucketVersioning|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|denied
site-encryption|s3:PutEncryptionConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-lifecycle|s3:PutLifecycleConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|denied
registry-upload|s3:PutObject|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
registry-delete|s3:DeleteObject|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
artifact-abort|s3:AbortMultipartUpload|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
lambda-tag|lambda:TagResource|$QUALIFIED_FUNCTION_ARN|allowed
lambda-untag|lambda:UntagResource|$QUALIFIED_FUNCTION_ARN|allowed
events-disable|events:DisableRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|allowed
events-enable|events:EnableRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|allowed
events-remove-targets|events:RemoveTargets|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|denied
events-tag|events:TagResource|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|allowed
events-untag|events:UntagResource|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/toll-v2-pricing-raw-objects-dev|allowed
logs-tag|logs:TagResource|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
logs-untag|logs:UntagResource|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|allowed
alarm-untag|cloudwatch:UntagResource|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|allowed
sessions-tag|dynamodb:TagResource|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-untag|dynamodb:UntagResource|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-backups|dynamodb:UpdateContinuousBackups|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
sessions-ttl|dynamodb:UpdateTimeToLive|arn:aws:dynamodb:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat-v2-anonymous-sessions-dev|allowed
catalog-tag|glue:TagResource|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/agent_registry|allowed
catalog-untag|glue:UntagResource|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:table/tollchat_agent_reports_development/agent_registry|allowed
catalog-database|glue:UpdateDatabase|arn:aws:glue:${REGION}:${EXPECTED_ACCOUNT}:database/tollchat_agent_reports_development|allowed
athena-tag|athena:TagResource|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
athena-untag|athena:UntagResource|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
schedule-tag|scheduler:TagResource|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule-group/default|allowed
schedule-untag|scheduler:UntagResource|arn:aws:scheduler:${REGION}:${EXPECTED_ACCOUNT}:schedule-group/default|allowed
agentcore-tag|bedrock-agentcore:TagResource|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
agentcore-untag|bedrock-agentcore:UntagResource|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/nova_toll_v2_development-Y69XBf88Bl|allowed
cloudfront-tag|cloudfront:TagResource|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-test|cloudfront:TestFunction|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
cloudfront-untag|cloudfront:UntagResource|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:function/tollchat-v2-public-chat-routes-dev|allowed
kms-decrypt|kms:Decrypt|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
kms-generate-data-key|kms:GenerateDataKey|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:key/076e8341-894b-405c-96e9-2b037f96e2a6|allowed
foundation-state-write|s3:PutObject|arn:aws:s3:::nova-toll-tfstate-${EXPECTED_ACCOUNT}/nova-toll/development/terraform.tfstate|denied
production-state-read|s3:GetObject|arn:aws:s3:::nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate|denied
unrelated-site-write|s3:PutObject|arn:aws:s3:::unrelated-development-site/index.html|denied
unrelated-artifact-write|s3:PutObject|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v1/release.zip|denied
role-create|iam:CreateRole|$ROLE_ARN|denied
role-policy-write|iam:PutRolePolicy|$ROLE_ARN|denied
role-pass|iam:PassRole|$ROLE_ARN|denied
url-admin|lambda:AddPermission|$QUALIFIED_FUNCTION_ARN|denied
lambda-config-admin|lambda:UpdateFunctionConfiguration|$QUALIFIED_FUNCTION_ARN|denied
agentcore-create|bedrock-agentcore:CreateAgentRuntime|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/unrelated|denied
agentcore-policy-write|bedrock-agentcore:PutResourcePolicy|arn:aws:bedrock-agentcore:${REGION}:${EXPECTED_ACCOUNT}:runtime/unrelated|denied
events-rule-write|events:PutRule|arn:aws:events:${REGION}:${EXPECTED_ACCOUNT}:rule/tollchat-v2-agent-usage-rollup-dev|denied
logs-filter-write|logs:PutMetricFilter|arn:aws:logs:${REGION}:${EXPECTED_ACCOUNT}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev|denied
alarm-write|cloudwatch:PutMetricAlarm|arn:aws:cloudwatch:${REGION}:${EXPECTED_ACCOUNT}:alarm/tollchat-v2-chat-proxy-errors-dev|denied
waf-logging-write|wafv2:PutLoggingConfiguration|arn:aws:wafv2:${REGION}:${EXPECTED_ACCOUNT}:global/webacl/tollchat-v2-public-chat-dev/unrelated|denied
kms-alias-write|kms:CreateAlias|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:alias/tollchat-v2-site-dev|denied
sg-write|ec2:AuthorizeSecurityGroupIngress|arn:aws:ec2:${REGION}:${EXPECTED_ACCOUNT}:security-group/sg-unrelated|denied
sqs-policy-write|sqs:SetQueueAttributes|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
sqs-policy-add|sqs:AddPermission|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
sqs-policy-remove|sqs:RemovePermission|arn:aws:sqs:${REGION}:${EXPECTED_ACCOUNT}:toll-v2-pricing-loader-invoke-failure-dev|denied
athena-query-write|athena:CreateNamedQuery|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|denied
measurement-policy-write|s3:PutBucketPolicy|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|denied
measurement-exposure-write|s3:PutBucketPublicAccessBlock|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|denied
iam-attachment-write|iam:AttachRolePolicy|$ROLE_ARN|denied
kms-alias-update|kms:UpdateAlias|arn:aws:kms:${REGION}:${EXPECTED_ACCOUNT}:alias/tollchat-v2-site-dev|denied
site-cors-read|s3:GetBucketCORS|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-website-read|s3:GetBucketWebsite|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-accelerate-read|s3:GetAccelerateConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-payment-read|s3:GetBucketRequestPayment|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-logging-read|s3:GetBucketLogging|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-replication-read|s3:GetReplicationConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
site-object-lock-read|s3:GetBucketObjectLockConfiguration|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev|allowed
measurement-cors-read|s3:GetBucketCORS|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-website-read|s3:GetBucketWebsite|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-accelerate-read|s3:GetAccelerateConfiguration|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-payment-read|s3:GetBucketRequestPayment|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-logging-read|s3:GetBucketLogging|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-replication-read|s3:GetReplicationConfiguration|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
measurement-object-lock-read|s3:GetBucketObjectLockConfiguration|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev|allowed
site-object-tags-read|s3:GetObjectTagging|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|allowed
site-object-tags-write|s3:PutObjectTagging|arn:aws:s3:::tollchat-site-${EXPECTED_ACCOUNT}-dev/index.html|allowed
registry-tags-read|s3:GetObjectTagging|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
registry-tags-write|s3:PutObjectTagging|arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${EXPECTED_ACCOUNT}-dev/registry/agent_registry.ndjson|allowed
runtime-artifact-tags-read|s3:GetObjectTagging|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
runtime-artifact-tags-write|s3:PutObjectTagging|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v2/release.zip|allowed
lambda-artifact-tags-read|s3:GetObjectTagging|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/lambda/v2/release.zip|allowed
lambda-artifact-tags-write|s3:PutObjectTagging|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/lambda/v2/release.zip|allowed
lambda-code-signing-read|lambda:GetFunctionCodeSigningConfig|arn:aws:lambda:${REGION}:${EXPECTED_ACCOUNT}:function:${FUNCTION_NAME}|allowed
alias-list|kms:ListAliases|*|allowed
managed-cache-read|cloudfront:GetCachePolicy|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad|allowed
managed-origin-read|cloudfront:GetOriginRequestPolicy|arn:aws:cloudfront::${EXPECTED_ACCOUNT}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac|allowed
runtime-role-pass|iam:PassRole|arn:aws:iam::${EXPECTED_ACCOUNT}:role/nova-toll-v2-agentcore-runtime-dev|allowed
runtime-role-wrong-service|iam:PassRole|arn:aws:iam::${EXPECTED_ACCOUNT}:role/nova-toll-v2-agentcore-runtime-dev|denied
unrelated-runtime-role-pass|iam:PassRole|arn:aws:iam::${EXPECTED_ACCOUNT}:role/unrelated-runtime-dev|denied
unrelated-object-tags|s3:PutObjectTagging|arn:aws:s3:::nova-toll-agentcore-${EXPECTED_ACCOUNT}/runtime/v1/release.zip|denied
production-object-tags|s3:GetObjectTagging|arn:aws:s3:::tollchat-site-920534282028/index.html|denied
alias-list-wrong-region|kms:ListAliases|*|denied
unrelated-athena-read|athena:GetNamedQuery|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/unrelated|denied
athena-workgroup-tags-read|athena:ListTagsForResource|arn:aws:athena:${REGION}:${EXPECTED_ACCOUNT}:workgroup/tollchat-agent-reports-dev|allowed
EOF
  SIMULATION_COUNT=0
  while IFS='|' read -r label action resource expected; do
    test -n "$label" || continue
    run_iam_simulation "$label" "$action" "$resource" "$expected"
    SIMULATION_COUNT=$((SIMULATION_COUNT + 1))
  done <"$SIMULATION_MATRIX"
  test "$SIMULATION_COUNT" -eq "$SIMULATION_EXPECTED_COUNT" || die "IAM simulation matrix is incomplete"

  REVIEWED_V2_PACKAGE_DIR="${REVIEWED_V2_PACKAGE_DIR:?set the absolute path to trusted v2 release packages}"
  REVIEWED_V2_PACKAGE_MANIFEST="${REVIEWED_V2_PACKAGE_MANIFEST:?set the absolute path to the reviewed package digest manifest}"
  case "$REVIEWED_V2_PACKAGE_DIR" in /*) ;; *) die "package directory must be absolute" ;; esac
  case "$(realpath -m -- "$REVIEWED_V2_PACKAGE_DIR")" in "$ROOT"|"$ROOT"/*) die "packages must be trusted artifacts outside checkout" ;; esac
  test -d "$REVIEWED_V2_PACKAGE_DIR" && test ! -L "$REVIEWED_V2_PACKAGE_DIR" || die "package directory must be a regular directory"
  require_external_file "$REVIEWED_V2_PACKAGE_MANIFEST"
  test "$(realpath -m -- "$REVIEWED_V2_PACKAGE_MANIFEST")" != "$INVENTORY" || die "package manifest cannot be inventory"
  for package in loader.zip publisher.zip agentcore.zip chat-proxy.zip; do
    require_external_file "$REVIEWED_V2_PACKAGE_DIR/$package"
  done
  PACKAGE_DIGESTS="$WORK_DIR/package-digests.tsv"
  : >"$PACKAGE_DIGESTS"
  for package in loader.zip publisher.zip agentcore.zip chat-proxy.zip; do
    sha256sum "$REVIEWED_V2_PACKAGE_DIR/$package" | awk -v name="$package" '{print $1 "\t" name}' >>"$PACKAGE_DIGESTS"
  done
  PACKAGE_DIGESTS_JSON="$(jq -Rn '[inputs | split("\t") | {sha256: .[0], name: .[1]}]' <"$PACKAGE_DIGESTS")"
  python3 - "$REVIEWED_V2_PACKAGE_MANIFEST" "$REVIEWED_V2_PACKAGE_DIR" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

expected = {"loader.zip", "publisher.zip", "agentcore.zip", "chat-proxy.zip"}
manifest = Path(sys.argv[1])
directory = Path(sys.argv[2])
entries = {}
for line in manifest.read_text().splitlines():
    fields = line.split()
    if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
        raise SystemExit("invalid package digest manifest")
    if fields[1] not in expected or fields[1] in entries:
        raise SystemExit("unexpected or duplicate package in manifest")
    entries[fields[1]] = fields[0]
if set(entries) != expected:
    raise SystemExit("package digest manifest is incomplete")
for name, digest in entries.items():
    actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"package digest mismatch: {name}")
PY

  REPRESENTATIVE_PLAN="$WORK_DIR/representative-development.tfplan"
  REPRESENTATIVE_PLAN_JSON="$WORK_DIR/representative-development.tfplan.json"
  REPRESENTATIVE_PLAN_EVIDENCE="$EVIDENCE_DIR/representative-plan.tsv"
  test ! -e "$REPRESENTATIVE_PLAN_EVIDENCE" || die "refusing to overwrite representative plan evidence"
  terraform -chdir="$ROOT/v2/infra" plan -input=false -out="$REPRESENTATIVE_PLAN" \
    -var-file=development.tfvars -var-file="$BOOTSTRAP_FOUNDATION_VARS" \
    -var "loader_package_path=$REVIEWED_V2_PACKAGE_DIR/loader.zip" \
    -var "publisher_package_path=$REVIEWED_V2_PACKAGE_DIR/publisher.zip" \
    -var "agentcore_package_path=$REVIEWED_V2_PACKAGE_DIR/agentcore.zip" \
    -var "chat_proxy_package_path=$REVIEWED_V2_PACKAGE_DIR/chat-proxy.zip"
  terraform -chdir="$ROOT/v2/infra" show -json "$REPRESENTATIVE_PLAN" >"$REPRESENTATIVE_PLAN_JSON"
  REPRESENTATIVE_PLAN_BODY="$WORK_DIR/representative-plan-body.tsv"
  python3 - "$REPRESENTATIVE_PLAN_JSON" "$REPRESENTATIVE_PLAN_BODY" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
changes = plan.get("resource_changes")
if not isinstance(changes, list):
    raise SystemExit("saved plan has no resource_changes array")
allowed = {"no-op", "create", "update", "delete", "read"}
rows = []
for change in changes:
    if not isinstance(change, dict) or not isinstance(change.get("address"), str):
        raise SystemExit("saved plan has an invalid resource address")
    actions = change.get("change", {}).get("actions")
    if not isinstance(actions, list) or not actions or any(action not in allowed for action in actions):
        raise SystemExit("saved plan has an invalid action array")
    rows.append((change["address"], ",".join(actions)))
Path(sys.argv[2]).write_text("terraform_address\tactions\n" + "".join(f"{a}\t{b}\n" for a, b in sorted(rows)))
PY
  PLAN_SHA256="$(sha256sum "$REPRESENTATIVE_PLAN" | awk '{print $1}')"
  EVIDENCE_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  EVIDENCE_BINDING="$EVIDENCE_DIR/evidence-binding.json"
  test ! -e "$EVIDENCE_BINDING" || die "refusing to overwrite evidence binding"
  jq -n --arg commit_sha "$REVIEWED_COMMIT" --arg account_id "$EXPECTED_ACCOUNT" \
    --arg role_arn "$ROLE_ARN" --arg trust_sha256 "$TRUST_SHA256" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg fetcher_sha256 "$FETCHER_SHA256" --arg timestamp "$EVIDENCE_TIMESTAMP" \
    --argjson package_digests "$PACKAGE_DIGESTS_JSON" \
    '{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,trust_sha256:$trust_sha256,policy_sha256:$policy_sha256,fetcher_sha256:$fetcher_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp,package_digests:$package_digests}' \
    >"$EVIDENCE_BINDING" || die "could not generate evidence binding"
  chmod 600 -- "$EVIDENCE_BINDING"
  BINDING_SHA256="$(sha256sum "$EVIDENCE_BINDING" | awk '{print $1}')"
  jq --arg commit_sha "$REVIEWED_COMMIT" --arg account_id "$EXPECTED_ACCOUNT" \
    --arg role_arn "$ROLE_ARN" --arg policy_sha256 "$POLICY_SHA256" \
    --arg plan_sha256 "$PLAN_SHA256" --arg timestamp "$EVIDENCE_TIMESTAMP" \
    --arg binding_sha256 "$BINDING_SHA256" \
    '. + {commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp,binding_sha256:$binding_sha256}' \
    "$INVENTORY" >"$WORK_DIR/inventory-bound.json" || die "could not bind inventory evidence"
  mv -- "$WORK_DIR/inventory-bound.json" "$INVENTORY"
  ADDRESS_INVENTORY_BODY="$WORK_DIR/terraform-addresses-body.tsv"
  mv -- "$ADDRESS_INVENTORY" "$ADDRESS_INVENTORY_BODY"
  {
    printf 'evidence_binding_sha256\t%s\ncommit_sha\t%s\naccount_id\t%s\nrole_arn\t%s\npolicy_sha256\t%s\nplan_sha256\t%s\ntimestamp\t%s\n' \
      "$BINDING_SHA256" "$REVIEWED_COMMIT" "$EXPECTED_ACCOUNT" "$ROLE_ARN" "$POLICY_SHA256" "$PLAN_SHA256" "$EVIDENCE_TIMESTAMP"
    cat -- "$ADDRESS_INVENTORY_BODY"
  } >"$ADDRESS_INVENTORY"
  chmod 600 -- "$ADDRESS_INVENTORY"
  {
    printf 'evidence_binding_sha256\t%s\n' "$BINDING_SHA256"
    printf 'commit_sha\t%s\naccount_id\t%s\nrole_arn\t%s\npolicy_sha256\t%s\nplan_sha256\t%s\ntimestamp\t%s\n' \
      "$REVIEWED_COMMIT" "$EXPECTED_ACCOUNT" "$ROLE_ARN" "$POLICY_SHA256" "$PLAN_SHA256" "$EVIDENCE_TIMESTAMP"
    cat -- "$REPRESENTATIVE_PLAN_BODY"
  } >"$REPRESENTATIVE_PLAN_EVIDENCE"
  chmod 600 -- "$REPRESENTATIVE_PLAN_EVIDENCE"
  jq -n --slurpfile simulations "$IAM_SIMULATION_LINES" \
    --arg binding_sha256 "$BINDING_SHA256" --arg commit_sha "$REVIEWED_COMMIT" \
    --arg account_id "$EXPECTED_ACCOUNT" --arg role_arn "$ROLE_ARN" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg timestamp "$EVIDENCE_TIMESTAMP" --argjson count "$SIMULATION_COUNT" \
    '{binding_sha256:$binding_sha256,context:{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp},simulation_count:$count,simulations:$simulations}' \
    >"$IAM_SIMULATION_EVIDENCE" || die "could not bind IAM simulation evidence"
  chmod 600 -- "$IAM_SIMULATION_EVIDENCE"

  PROTECTED_MAIN_OIDC_EVIDENCE="${PROTECTED_MAIN_OIDC_EVIDENCE:?set the sanitized protected-main OIDC proof path}"
  require_external_file "$PROTECTED_MAIN_OIDC_EVIDENCE"
  OIDC_PROOF="$EVIDENCE_DIR/protected-main-oidc.json"
  test ! -e "$OIDC_PROOF" || die "refusing to overwrite protected-main OIDC evidence"
  jq -e --arg commit "$REVIEWED_COMMIT" '
    type == "object" and (keys_unsorted | sort) == ["account", "commit_sha", "environment", "proof", "ref", "repository"] and
    .proof == "protected-main-oidc" and .account == "903859731897" and
    .commit_sha == $commit and
    .environment == "development" and .ref == "refs/heads/main" and
    .repository == "rhprasad0/nova-toll-budget-agent"
  ' "$PROTECTED_MAIN_OIDC_EVIDENCE" >/dev/null ||
    die "protected-main OIDC proof is not the exact development account proof"
  jq -n --slurpfile proof "$PROTECTED_MAIN_OIDC_EVIDENCE" \
    --arg binding_sha256 "$BINDING_SHA256" --arg commit_sha "$REVIEWED_COMMIT" \
    --arg account_id "$EXPECTED_ACCOUNT" --arg role_arn "$ROLE_ARN" \
    --arg policy_sha256 "$POLICY_SHA256" --arg plan_sha256 "$PLAN_SHA256" \
    --arg timestamp "$EVIDENCE_TIMESTAMP" \
    '{binding_sha256:$binding_sha256,context:{commit_sha:$commit_sha,account_id:$account_id,role_arn:$role_arn,policy_sha256:$policy_sha256,plan_sha256:$plan_sha256,timestamp:$timestamp},proof:$proof[0]}' \
    >"$OIDC_PROOF" || die "could not bind protected-main OIDC evidence"
  chmod 600 -- "$OIDC_PROOF"
}

run_post_bootstrap_gates
BOOTSTRAP_COMPLETE=1
printf 'non-secret inventory: %s\naddress map: %s\n' "$INVENTORY" "$ADDRESS_INVENTORY"
```

After bootstrap/import, the recurring OIDC role may refresh the same state,
perform explicitly allowed updates, upload reviewed release artifacts, and
perform only the four named immutable release families: the development API
Gateway deployment, published/retired versions of the five named development
Lambda functions, the two named development CloudFront functions, and the
named development Bedrock guardrail version (publication only; its Terraform
resource uses `skip_destroy`). It cannot create, replace, or administer the
bootstrap addresses above. The protected OIDC role's scoped development IAM
policy is the authorization boundary; the workflow applies only the exact
binary plan it just created. The foundation Terraform root owns the
route-control role, fixed SSM document, and their trust/policy resources; they
are intentionally absent from v2 application Terraform and the recurring
delivery plan.

The protected `main` branch plus the protected GitHub `development` environment
is the reviewed release source for this identity. Publishing arbitrary code to
the named development Lambda/site objects and the two named development
CloudFront functions is therefore an intentional delivery capability; the
AWS policy bounds those calls and Terraform operations to exact development
resources. The identity still cannot
switch roles, access production or foundation-write paths, create bootstrap
resources, change public URL permissions, or alter measurement exposure
controls.

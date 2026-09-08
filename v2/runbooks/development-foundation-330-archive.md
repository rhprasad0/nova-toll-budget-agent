### Development foundation handoff (#330; no application release) [historical, superseded]

Issue #330 is a two-stage handoff. This stage only generates a complete
development-account foundation plan, retains the exact copied root and binary
plan for review, and stops; a later separately authorized stage may use that
same root and plan for the foundation apply without regenerating it. This
stage does not initialize a remote backend, mutate state, apply, import, or
release the development application. The foundation plan explicitly disables
Tailscale route advertisement until #330 provisions a non-overlapping VPC and
#332 supplies an environment-specific ACL identity.

The production Budget subscriber is read ephemerally for the approved #330
plan input. Because the Budget subscription is Terraform-managed, its value is
necessarily retained in the private reviewed plan and encrypted,
access-controlled Terraform state; that is the approved protected exception.
Never write it to repository source, checked-in tfvars, logs, raw review
output, or a typed handoff. The temporary recipient files are private and
removed on every exit. The retained root and exact plan remain private for
checker/security review; only their path, plan SHA-256, and sorted
address/actions summary are displayed.

```sh
(
set -euo pipefail
set +x
umask 077
ROOT="$(git rev-parse --show-toplevel)"
DEVELOPMENT_FOUNDATION_DIR=
DEVELOPMENT_FOUNDATION_PLAN=
DEVELOPMENT_BUDGET_RECIPIENTS=
DEVELOPMENT_BUDGET_SUBSCRIBERS=
cleanup() {
  status=$?
  for temporary in "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"; do
    test -z "$temporary" || rm -f -- "$temporary"
  done
  unset TF_VAR_budget_notification_email DEVELOPMENT_BUDGET_NOTIFICATIONS \
    DEVELOPMENT_BUDGET_NOTIFICATION_LINES DEVELOPMENT_FOUNDATION_SUMMARY \
    DEVELOPMENT_FOUNDATION_PLAN_SHA DEVELOPMENT_FETCHER_PACKAGE \
    DEVELOPMENT_FETCHER_PACKAGE_SHA DEVELOPMENT_FOUNDATION_VERSIONS notification
  if test "$status" -ne 0 && test -n "$DEVELOPMENT_FOUNDATION_DIR"; then
    printf 'Development foundation plan failed; retained root: %s\n' \
      "$DEVELOPMENT_FOUNDATION_DIR" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
DEVELOPMENT_FOUNDATION_DIR="$(mktemp -d)"
chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR")" = "700"
DEVELOPMENT_FOUNDATION_PLAN="$DEVELOPMENT_FOUNDATION_DIR/development-foundation.tfplan"
DEVELOPMENT_BUDGET_RECIPIENTS="$(mktemp)"
DEVELOPMENT_BUDGET_SUBSCRIBERS="$(mktemp)"
chmod 600 -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"
test "$(stat -c '%a' "$DEVELOPMENT_BUDGET_RECIPIENTS")" = "600"
test "$(stat -c '%a' "$DEVELOPMENT_BUDGET_SUBSCRIBERS")" = "600"
unset TF_VAR_budget_notification_email
test "$(AWS_PROFILE=nova-toll-prod aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "920534282028"
if ! DEVELOPMENT_BUDGET_NOTIFICATIONS="$(
  AWS_PROFILE=nova-toll-prod aws --region us-east-1 budgets \
    describe-notifications-for-budget --account-id 920534282028 \
    --budget-name nova-toll-monthly --output json 2>/dev/null
)"; then
  printf 'Production Budget notification read failed.\n' >&2
  exit 1
fi
DEVELOPMENT_BUDGET_NOTIFICATION_LINES="$(
  jq -ce '.Notifications | if type == "array" and length > 0 and all(.[]; type == "object") then .[] else error("invalid budget notifications") end' \
    <<<"$DEVELOPMENT_BUDGET_NOTIFICATIONS"
)"
export TF_VAR_budget_notification_email="$(
  if ! while IFS= read -r notification; do
    if ! AWS_PROFILE=nova-toll-prod aws --region us-east-1 budgets \
      describe-subscribers-for-notification --account-id 920534282028 \
      --budget-name nova-toll-monthly --notification "$notification" --output json \
      >"$DEVELOPMENT_BUDGET_SUBSCRIBERS" 2>/dev/null; then
      exit 1
    fi
    if ! jq -e '
      .Subscribers
      | type == "array"
        and all(.[]; type == "object"
          and (.SubscriptionType | type == "string")
          and (.Address | type == "string"))
    ' "$DEVELOPMENT_BUDGET_SUBSCRIBERS" >/dev/null; then
      exit 1
    fi
    if ! jq -r '.Subscribers[]? | select(.SubscriptionType == "EMAIL" and (.Address | type == "string")) | .Address' \
      "$DEVELOPMENT_BUDGET_SUBSCRIBERS" >>"$DEVELOPMENT_BUDGET_RECIPIENTS"; then
      exit 1
    fi
  done <<<"$DEVELOPMENT_BUDGET_NOTIFICATION_LINES"; then
    exit 1
  fi
  jq -R -s -er '
    split("\n") | map(select(length > 0)) | unique |
    if (length == 1 and (.[0] | type == "string" and length > 0 and test("^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$")))
    then .[0]
    else error("expected exactly one non-empty EMAIL subscriber")
    end
  ' "$DEVELOPMENT_BUDGET_RECIPIENTS"
)"
rm -f -- "$DEVELOPMENT_BUDGET_RECIPIENTS" "$DEVELOPMENT_BUDGET_SUBSCRIBERS"
unset DEVELOPMENT_BUDGET_NOTIFICATIONS DEVELOPMENT_BUDGET_NOTIFICATION_LINES notification
test "$(AWS_PROFILE=nova-toll-dev aws --region us-east-1 sts get-caller-identity --query Account --output text)" = "903859731897"
test -r "$ROOT/infra/build/fetcher.zip"
test -s "$ROOT/infra/build/fetcher.zip"
cp -a "$ROOT/infra/." "$DEVELOPMENT_FOUNDATION_DIR/"
chmod 700 -- "$DEVELOPMENT_FOUNDATION_DIR"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR")" = "700"
chmod 600 -- "$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip")" = "600"
DEVELOPMENT_FETCHER_PACKAGE="$DEVELOPMENT_FOUNDATION_DIR/build/fetcher.zip"
DEVELOPMENT_FOUNDATION_VERSIONS="$DEVELOPMENT_FOUNDATION_DIR/versions.tf.with-backend"
cp "$DEVELOPMENT_FOUNDATION_DIR/versions.tf" "$DEVELOPMENT_FOUNDATION_VERSIONS"
chmod 600 -- "$DEVELOPMENT_FOUNDATION_VERSIONS"
rm -rf -- "$DEVELOPMENT_FOUNDATION_DIR/.terraform" "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.d"
rm -f -- "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate" "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.backup"
DEVELOPMENT_TF_DATA_DIR="$DEVELOPMENT_FOUNDATION_DIR/.terraform-data"
mkdir -p "$DEVELOPMENT_TF_DATA_DIR"
export TF_DATA_DIR="$DEVELOPMENT_TF_DATA_DIR"
sed -i '/^[[:space:]]*backend "s3" {}/d' "$DEVELOPMENT_FOUNDATION_DIR/versions.tf"
test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate"
test ! -e "$DEVELOPMENT_FOUNDATION_DIR/terraform.tfstate.backup"
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" init -backend=false -input=false \
  >/dev/null 2>/dev/null; then
  printf 'Development foundation Terraform init failed.\n' >&2
  exit 1
fi
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" plan \
  -input=false -lock=false -var environment=development \
  -var tailscale_advertise_routes=false \
  -var fetcher_package_path="$DEVELOPMENT_FETCHER_PACKAGE" \
  -out="$DEVELOPMENT_FOUNDATION_PLAN" >/dev/null 2>/dev/null; then
  printf 'Development foundation Terraform plan failed.\n' >&2
  exit 1
fi
chmod 600 -- "$DEVELOPMENT_FOUNDATION_PLAN"
test "$(stat -c '%a' "$DEVELOPMENT_FOUNDATION_PLAN")" = "600"
if ! AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" show -json "$DEVELOPMENT_FOUNDATION_PLAN" 2>/dev/null | jq -e '
  def foundation_create_addresses: [
    "aws_kms_key.raw",
    "aws_kms_alias.raw",
    "aws_kms_key.tfstate",
    "aws_kms_alias.tfstate",
    "aws_kms_key.audit",
    "aws_kms_alias.audit",
    "aws_kms_key.alerts",
    "aws_kms_alias.alerts",
    "aws_cloudwatch_event_rule.poll_tick",
    "aws_cloudwatch_event_target.fetcher",
    "aws_lambda_permission.eventbridge_invoke_fetcher",
    "aws_cloudwatch_event_rule.poll_tick_i66",
    "aws_cloudwatch_event_target.fetcher_i66",
    "aws_lambda_permission.eventbridge_invoke_fetcher_i66",
    "aws_s3_bucket_notification.raw",
    "aws_iam_role.fetcher",
    "aws_iam_role_policy_attachment.fetcher_basic",
    "aws_iam_role_policy.fetcher",
    "aws_iam_role.replay",
    "aws_iam_role_policy.replay",
    "aws_iam_openid_connect_provider.github",
    "aws_iam_role.tailscale_router",
    "aws_iam_role_policy.tailscale_router",
    "aws_iam_role_policy_attachment.tailscale_router_ssm",
    "aws_iam_instance_profile.tailscale_router",
    "aws_instance.tailscale_router",
    "aws_ssm_document.route_control[0]",
    "aws_iam_role.route_control[0]",
    "aws_iam_role_policy.route_control[0]",
    "aws_ssm_parameter.i95_token",
    "aws_ssm_parameter.i66_token",
    "aws_ssm_parameter.tailscale_authkey",
    "aws_s3_bucket.audit",
    "aws_s3_bucket_policy.audit",
    "aws_cloudtrail.audit",
    "aws_s3_bucket_versioning.hardened[\"raw\"]",
    "aws_s3_bucket_versioning.hardened[\"audit\"]",
    "aws_s3_bucket_versioning.hardened[\"tfstate\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"raw\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"audit\"]",
    "aws_s3_bucket_ownership_controls.hardened[\"tfstate\"]",
    "aws_s3_bucket_public_access_block.hardened[\"raw\"]",
    "aws_s3_bucket_public_access_block.hardened[\"audit\"]",
    "aws_s3_bucket_public_access_block.hardened[\"tfstate\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"raw\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"audit\"]",
    "aws_s3_bucket_server_side_encryption_configuration.hardened[\"tfstate\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"raw\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"audit\"]",
    "aws_s3_bucket_lifecycle_configuration.hardened[\"tfstate\"]",
    "aws_s3_bucket.raw",
    "aws_s3_bucket_policy.raw",
    "aws_s3_bucket.tfstate",
    "aws_s3_bucket_policy.tfstate",
    "aws_db_instance.main",
    "aws_subnet.tollchat_private_a",
    "aws_subnet.tollchat_private_c",
    "aws_eip.tollchat_nat",
    "aws_nat_gateway.tollchat",
    "aws_route_table.tollchat_private",
    "aws_route_table_association.tollchat_private[\"us_east_1a\"]",
    "aws_route_table_association.tollchat_private[\"us_east_1c\"]",
    "aws_security_group.tollchat_api_endpoint",
    "aws_vpc_security_group_ingress_rule.tollchat_api_from_tailscale",
    "aws_security_group.agentcore_endpoint",
    "aws_vpc_endpoint.agentcore",
    "aws_vpc_endpoint.tollchat_api",
    "aws_security_group.eventbridge_endpoint",
    "aws_vpc_security_group_ingress_rule.eventbridge_from_private[\"172.31.224.0/24\"]",
    "aws_vpc_security_group_ingress_rule.eventbridge_from_private[\"172.31.225.0/24\"]",
    "aws_vpc_endpoint.eventbridge",
    "aws_vpc_endpoint.dynamodb",
    "aws_s3_bucket.agentcore_artifacts",
    "aws_s3_bucket_public_access_block.agentcore_artifacts",
    "aws_s3_bucket_server_side_encryption_configuration.agentcore_artifacts",
    "aws_s3_bucket_versioning.agentcore_artifacts",
    "aws_s3_bucket_lifecycle_configuration.agentcore_artifacts",
    "aws_s3_bucket_policy.agentcore_artifacts",
    "aws_vpc_endpoint.s3",
    "aws_db_subnet_group.main",
    "aws_security_group.rds",
    "aws_security_group.tailscale_router",
    "aws_vpc_security_group_ingress_rule.rds_from_tailscale",
    "aws_vpc_security_group_egress_rule.tailscale_router_egress",
    "aws_cloudwatch_log_group.fetcher",
    "aws_lambda_function.fetcher",
    "aws_lambda_function_event_invoke_config.fetcher",
    "aws_sns_topic.alerts",
    "aws_sns_topic_subscription.alerts_email",
    "aws_cloudwatch_metric_alarm.fetcher_errors",
    "aws_cloudwatch_metric_alarm.bucket_storage[\"raw\"]",
    "aws_cloudwatch_metric_alarm.bucket_storage[\"tfstate\"]",
    "aws_cloudwatch_metric_alarm.rds_free_storage",
    "aws_cloudwatch_metric_alarm.rds_cpu",
    "aws_cloudwatch_metric_alarm.rds_free_memory",
    "aws_cloudwatch_metric_alarm.rds_connections",
    "aws_cloudwatch_metric_alarm.rds_cpu_credits",
    "aws_budgets_budget.nova_toll_monthly"
  ];
  def foundation_data_addresses: [
    "data.aws_caller_identity.current",
    "data.aws_region.current",
    "data.aws_vpc.default",
    "data.aws_subnets.default",
    "data.aws_route_tables.default",
    "data.aws_subnet.tailscale_router",
    "data.aws_iam_policy_document.route_control_assume[0]",
    "data.aws_iam_policy_document.route_control[0]"
  ];
  def expected_changes:
    ([foundation_create_addresses[] | {mode: "managed", address: ., actions: ["create"]}] +
     [foundation_data_addresses[] | {mode: "data", address: ., actions: ["read"]}])
    | sort_by([.mode, .address, (.actions | join(","))]);
  def actual_changes:
    if (.resource_changes | type) != "array" then error("invalid resource_changes")
    else [.resource_changes[] |
      if type != "object" or (.address | type) != "string" or (.change | type) != "object" or
        (.change.actions | type) != "array" or any(.change.actions[]; type != "string") then
        error("invalid resource change")
      else {mode, address, actions: .change.actions}
      end
    ] | sort_by([.mode, .address, (.actions | join(","))])
    end;
  actual_changes == expected_changes
' >/dev/null 2>/dev/null; then
  printf 'Development foundation plan scope gate failed.\n' >&2
  exit 1
fi
if ! DEVELOPMENT_FOUNDATION_SUMMARY="$(
  AWS_PROFILE=nova-toll-dev terraform -chdir="$DEVELOPMENT_FOUNDATION_DIR" show -json "$DEVELOPMENT_FOUNDATION_PLAN" 2>/dev/null |
    jq -ce '
      if (.resource_changes | type) != "array" then error("invalid resource_changes")
      else [.resource_changes[] |
        if (.address | type) != "string" or (.change | type) != "object" or (.change.actions | type) != "array" then
          error("invalid resource change")
        else {address: .address, actions: .change.actions}
        end
      ] | sort_by(.address)
      end
    ' 2>/dev/null
)"; then
  printf 'Development foundation plan summary failed.\n' >&2
  exit 1
fi
DEVELOPMENT_FOUNDATION_PLAN_SHA="$(sha256sum "$DEVELOPMENT_FOUNDATION_PLAN" | awk '{print $1}')"
printf 'Development foundation root: %s\n' "$DEVELOPMENT_FOUNDATION_DIR"
printf 'Development foundation plan SHA-256: %s\n' "$DEVELOPMENT_FOUNDATION_PLAN_SHA"
printf '%s\n' "$DEVELOPMENT_FOUNDATION_SUMMARY"
)
```

#### Later authorized exact-plan apply and recovery

After checker and security approval, a separately authorized operator may run
this complete #330 success path. It consumes only the retained root and binary
plan recorded in `.graph/change.md`; it never regenerates a plan, changes a
plan input, targets/imports a resource, or initializes a remote backend before
the local apply. Terraform/provider/AWS output is suppressed or reduced to
scalar predicates. A failure prints only its fixed stage category, preserves
the root and state, and stops without retry or cleanup.

##### Successful exact-plan apply, migration, and evidence

```sh
(
set -euo pipefail
set +x
umask 077
ROOT=/tmp/tmp.1nuZtAcl8L
PLAN="$ROOT/development-foundation.tfplan"
FETCHER="$ROOT/build/fetcher.zip"
REGION=us-east-1
DEV_ACCOUNT=903859731897
PROD_ACCOUNT=920534282028
EXPECTED_PLAN=0efda359505d7142a45792ec79e12d40d0540b7e3e961a7e04891328ca94e597
EXPECTED_FETCHER=9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1
EXPECTED_MANIFEST=d42489b4f0e971e6eeb06d0ba033b68584ab95ff19763a0e40724db657e8acc8
STATE_BUCKET=nova-toll-tfstate-903859731897
STATE_KEY=nova-toll/development/terraform.tfstate
failure_stage=preflight
fail() { exit 1; }
cleanup() {
  status=$?
  if test "$status" -ne 0; then
    printf 'Development foundation handoff failed at %s; retained root preserved.\n' "$failure_stage" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'failure_stage=interrupted; exit 130' HUP INT TERM
expect_absent_error() {
  local expected_error error_text return_code
  expected_error=$1
  shift
  set +e
  error_text="$("$@" 2>&1 >/dev/null)"
  return_code=$?
  set -e
  test "$return_code" -ne 0
  printf '%s' "$error_text" | grep -qiE "$expected_error"
}
absent_s3_bucket() { expect_absent_error '404|NoSuchBucket|Not Found' "$@"; }
absent_kms_key() { expect_absent_error 'NotFoundException' "$@"; }
absent_rds_instance() { expect_absent_error 'DBInstanceNotFound' "$@"; }
absent_lambda_function() { expect_absent_error 'ResourceNotFoundException' "$@"; }
absent_sns_topic() { expect_absent_error 'NotFound' "$@"; }
absent_cloudtrail() { expect_absent_error 'TrailNotFoundException' "$@"; }
absent_event_rule() { expect_absent_error 'ResourceNotFoundException' "$@"; }
absent_iam_role() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_instance_profile() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_rds_subnet_group() { expect_absent_error 'DBSubnetGroupNotFoundFault' "$@"; }
absent_oidc_provider() { expect_absent_error 'NoSuchEntity' "$@"; }
absent_budget() { expect_absent_error 'NotFoundException' "$@"; }
test "$(stat -c '%a' "$ROOT")" = 700
test "$(stat -c '%a' "$PLAN")" = 600
test "$(stat -c '%a' "$FETCHER")" = 600
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"
test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
test -d "$ROOT/.terraform-data"
test ! -e "$ROOT/terraform.tfstate"; test ! -e "$ROOT/terraform.tfstate.backup"; test ! -e "$ROOT/terraform.tfstate.d"
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf" || true)" = 0
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf.with-backend" || true)" = 1
manifest_digest() {
  (
    cd -- "$ROOT"
    {
      find . -maxdepth 1 -type f \( -name '*.tf' -o -name '*.tf.json' \) -printf '%P\0'
      find .terraform-data/providers -type f -perm /111 -name 'terraform-provider-*' -printf '.terraform-data/providers/%P\0'
      printf '%s\0' account-contract.json .terraform.lock.hcl lambda-stub/handler.py versions.tf.with-backend backend.development.hcl build/fetcher.zip @terraform-cli @terraform-version
    } | LC_ALL=C sort -z -u | while IFS= read -r -d '' rel; do
      case "$rel" in
        @terraform-cli) digest="$(sha256sum -- "$(readlink -f "$(command -v terraform)")" | awk '{print $1}')" ;;
        @terraform-version) digest="$(terraform version -json | jq -er '.terraform_version + "\t" + .platform')" ;;
        *) digest="$(sha256sum -- "$rel" | awk '{print $1}')" ;;
      esac
      test -n "$digest"; printf '%s\t%s\n' "$rel" "$digest"
    done
  ) | LC_ALL=C sha256sum | awk '{print $1}'
}
FIRST="$(manifest_digest)"; SECOND="$(manifest_digest)"; test "$FIRST" = "$SECOND"; test "$FIRST" = "$EXPECTED_MANIFEST"
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$DEV_ACCOUNT"
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)" = "$REGION"
for bucket in nova-toll-tfstate-$DEV_ACCOUNT nova-toll-raw-$DEV_ACCOUNT nova-toll-audit-$DEV_ACCOUNT nova-toll-agentcore-$DEV_ACCOUNT; do absent_s3_bucket env AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$bucket"; done
for alias in alias/nova-toll-raw alias/nova-toll-tfstate alias/nova-toll-audit alias/nova-toll-alerts; do absent_kms_key env AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id "$alias"; done
absent_rds_instance env AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-instances --db-instance-identifier nova-toll-db
absent_lambda_function env AWS_PROFILE=nova-toll-dev aws --region "$REGION" lambda get-function --function-name toll-fetcher
absent_sns_topic env AWS_PROFILE=nova-toll-dev aws --region "$REGION" sns get-topic-attributes --topic-arn "arn:aws:sns:$REGION:$DEV_ACCOUNT:nova-toll-alerts"
absent_cloudtrail env AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail --name nova-toll-audit
for rule in toll-poll-tick toll-poll-tick-i66; do absent_event_rule env AWS_PROFILE=nova-toll-dev aws --region "$REGION" events describe-rule --name "$rule"; done
for role in toll-fetcher toll-raw-replay nova-toll-tailscale-router; do absent_iam_role env AWS_PROFILE=nova-toll-dev aws iam get-role --role-name "$role"; done
absent_instance_profile env AWS_PROFILE=nova-toll-dev aws iam get-instance-profile --instance-profile-name nova-toll-tailscale-router
for parameter in /nova-toll/i95-token /nova-toll/i66-token /nova-toll/tailscale-authkey; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'length(Parameters)' --output text)" = 0; done
VPC_ID="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"; test -n "$VPC_ID"; test "$VPC_ID" != None
absent_rds_subnet_group env AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-subnet-groups --db-subnet-group-name nova-toll-db
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" logs describe-log-groups --log-group-name-prefix /aws/lambda/toll-fetcher --query 'length(logGroups[?logGroupName==`/aws/lambda/toll-fetcher`])' --output text)" = 0
absent_oidc_provider env AWS_PROFILE=nova-toll-dev aws iam get-open-id-connect-provider --open-id-connect-provider-arn "arn:aws:iam::$DEV_ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
absent_budget env AWS_PROFILE=nova-toll-dev aws --region "$REGION" budgets describe-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudwatch describe-alarms --alarm-names toll-fetcher-errors nova-toll-raw-storage-10gb nova-toll-tfstate-storage-10gb toll-rds-free-storage toll-rds-cpu toll-rds-free-memory toll-rds-connections toll-rds-cpu-credits --query 'length(MetricAlarms)' --output text)" = 0
for sg in nova-toll-rds nova-toll-tailscale-router nova-toll-preview-api-endpoint nova-toll-agentcore-endpoint nova-toll-eventbridge-endpoint; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$sg" --query 'length(SecurityGroups)' --output text)" = 0; done
for service in bedrock-agentcore execute-api events dynamodb s3; do
  ENDPOINT_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpc-endpoints --filters Name=vpc-id,Values="$VPC_ID" --query "length(VpcEndpoints[?contains(ServiceName, '$service')])" --output text)"
  test "$ENDPOINT_COUNT" = 0
done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-nat-gateways --filter Name=tag:Name,Values=nova-toll-preview --query 'length(NatGateways)' --output text)" = 0
for cidr in 172.31.224.0/24 172.31.225.0/24; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=cidr-block,Values="$cidr" --query 'length(Subnets)' --output text)" = 0; done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-instance-type-offerings --location-type availability-zone --filters Name=instance-type,Values=t4g.nano --query 'length(InstanceTypeOfferings)' --output text)" -ge 1
RDS_OPTIONS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-orderable-db-instance-options --engine postgres --db-instance-class db.t4g.small --query 'length(OrderableDBInstanceOptions[?starts_with(EngineVersion, `17.`)])' --output text)"; test "$(printf '%s\n' "$RDS_OPTIONS" | awk '{sum += $1} END {print sum + 0}')" -ge 1
test "$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$PROD_ACCOUNT"
printf 'preflight=passed; manifest=%s; plan_sha=%s; fetcher_sha=%s; account=%s; region=%s\n' "$FIRST" "$EXPECTED_PLAN" "$EXPECTED_FETCHER" "$DEV_ACCOUNT" "$REGION"
failure_stage=apply
if ! TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" apply -input=false "$PLAN" >/dev/null 2>/dev/null; then fail; fi
failure_stage=local_state
chmod 600 -- "$ROOT/terraform.tfstate"
test "$(stat -c '%a' "$ROOT/terraform.tfstate")" = 600
STATE_LIST="$(TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" state list 2>/dev/null)"
test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | wc -l)" = 95
test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | sort | sha256sum | awk '{print $1}')" = b1d38c8b7e95452aa2fa069307a76e551ab59f4988e2f0a1af5be7824c037b57
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>/dev/null; echo $?)" = 0
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-tfstate --query KeyMetadata.KeyState --output text)" = Enabled
failure_stage=migration_preflight
test "$(stat -c '%a' "$ROOT")" = 700; test "$(stat -c '%a' "$PLAN")" = 600; test "$(stat -c '%a' "$FETCHER")" = 600; test -d "$ROOT/.terraform-data"
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"; test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
test "$(manifest_digest)" = "$EXPECTED_MANIFEST"; test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf" || true)" = 0
state_object_absent() { local key error_text return_code; set +e; error_text="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$key" 2>&1 >/dev/null)"; return_code=$?; set -e; test "$return_code" -ne 0; printf '%s' "$error_text" | grep -qiE '404|Not Found|NoSuchKey'; }
state_object_absent "$STATE_KEY"; state_object_absent "$STATE_KEY.tflock"
cp -- "$ROOT/versions.tf.with-backend" "$ROOT/versions.tf"; chmod 600 -- "$ROOT/versions.tf"
test "$(grep -Ec '^[[:space:]]*backend "'s3'"' "$ROOT/versions.tf")" = 1
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$DEV_ACCOUNT"; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)" = "$REGION"
test "$(sha256sum "$PLAN" | awk '{print $1}')" = "$EXPECTED_PLAN"; test "$(sha256sum "$FETCHER" | awk '{print $1}')" = "$EXPECTED_FETCHER"
failure_stage=migration
if ! TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" init -migrate-state -force-copy -input=false -backend-config="$ROOT/backend.development.hcl" >/dev/null 2>/dev/null; then fail; fi
failure_stage=postcheck
STATE_KMS_ARN="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-tfstate --query KeyMetadata.Arn --output text)"
case "$STATE_KMS_ARN" in arn:aws:kms:$REGION:$DEV_ACCOUNT:key/????????-????-????-????-????????????) : ;; *) fail ;; esac
STATE_HEAD="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY" --query '{sse:ServerSideEncryption,kms:SSEKMSKeyId}' --output json)"; jq -e --arg arn "$STATE_KMS_ARN" '.sse == "aws:kms" and .kms == $arn' <<<"$STATE_HEAD" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-versioning --bucket "$STATE_BUCKET" --query Status --output text)" = Enabled
PAB="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-public-access-block --bucket "$STATE_BUCKET" --query PublicAccessBlockConfiguration --output json)"; jq -e '(.BlockPublicAcls and .BlockPublicPolicy and .IgnorePublicAcls and .RestrictPublicBuckets)' <<<"$PAB" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-ownership-controls --bucket "$STATE_BUCKET" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" = BucketOwnerEnforced
ENC="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-encryption --bucket "$STATE_BUCKET" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault' --output json)"; jq -e --arg arn "$STATE_KMS_ARN" '.SSEAlgorithm == "aws:kms" and .KMSMasterKeyID == $arn' <<<"$ENC" >/dev/null
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-policy-status --bucket "$STATE_BUCKET" --query PolicyStatus.IsPublic --output text)" = False
# Terraform 1.15.8 exposes no lock flags for state list; bound the read. The migration acquired/released the native lock; this proves no stale lockfile.
STATE_LIST="$(timeout 30s env TF_DATA_DIR="$ROOT/.terraform-data" AWS_PROFILE=nova-toll-dev terraform -chdir="$ROOT" state list 2>/dev/null)"; test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | wc -l)" = 95; test "$(printf '%s\n' "$STATE_LIST" | awk '$0 !~ /^data[.]/ {print}' | sort | sha256sum | awk '{print $1}')" = b1d38c8b7e95452aa2fa069307a76e551ab59f4988e2f0a1af5be7824c037b57
if AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY.tflock" >/dev/null 2>/dev/null; then fail; fi
for bucket in "$STATE_BUCKET" nova-toll-raw-$DEV_ACCOUNT nova-toll-audit-$DEV_ACCOUNT nova-toll-agentcore-$DEV_ACCOUNT; do AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api head-bucket --bucket "$bucket" >/dev/null 2>/dev/null; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)" = Enabled; PAB="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-public-access-block --bucket "$bucket" --query PublicAccessBlockConfiguration --output json)"; jq -e '(.BlockPublicAcls and .BlockPublicPolicy and .IgnorePublicAcls and .RestrictPublicBuckets)' <<<"$PAB" >/dev/null; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" s3api get-bucket-ownership-controls --bucket "$bucket" --query 'OwnershipControls.Rules[0].ObjectOwnership' --output text)" = BucketOwnerEnforced; done
for alias in alias/nova-toll-raw alias/nova-toll-tfstate alias/nova-toll-audit alias/nova-toll-alerts; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id "$alias" --query KeyMetadata.KeyState --output text)" = Enabled; done
ALIAS_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms list-aliases --query "length(Aliases[?AliasName=='alias/nova-toll-raw' || AliasName=='alias/nova-toll-tfstate' || AliasName=='alias/nova-toll-audit' || AliasName=='alias/nova-toll-alerts'])" --output text)"; test "$ALIAS_COUNT" = 4
VPC_ID="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"; for cidr in 172.31.224.0/24 172.31.225.0/24; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=cidr-block,Values="$cidr" --query 'length(Subnets)' --output text)" = 1; done
for service in bedrock-agentcore execute-api events dynamodb s3; do
  ENDPOINT_COUNT="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-vpc-endpoints --filters Name=vpc-id,Values="$VPC_ID" --query "length(VpcEndpoints[?contains(ServiceName, '$service')])" --output text)"
  test "$ENDPOINT_COUNT" = 1
done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" lambda get-function --function-name toll-fetcher --query Configuration.FunctionName --output text)" = toll-fetcher
for role in toll-fetcher toll-raw-replay nova-toll-tailscale-router; do test "$(AWS_PROFILE=nova-toll-dev aws iam get-role --role-name "$role" --query 'Role.RoleName' --output text 2>/dev/null)" = "$role"; done
for rule in toll-poll-tick toll-poll-tick-i66; do test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" events describe-rule --name "$rule" --query State --output text)" = ENABLED; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" events list-targets-by-rule --rule "$rule" --query 'length(Targets)' --output text)" = 1; done
for attempt in $(seq 1 30); do status="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" rds describe-db-instances --db-instance-identifier nova-toll-db --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || true)"; test "$status" = available && break; test "$attempt" -lt 30 || fail; sleep 10; done
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ec2 describe-instances --filters Name=tag:Name,Values=nova-toll-tailscale-router Name=instance-state-name,Values=running --query 'length(Reservations[].Instances[])' --output text)" = 1
PROFILE_ROLES="$(AWS_PROFILE=nova-toll-dev aws iam get-instance-profile --instance-profile-name nova-toll-tailscale-router --query InstanceProfile.Roles --output json)"; test "$(jq 'length' <<<"$PROFILE_ROLES")" = 1
TOPIC_ARN="arn:aws:sns:$REGION:$DEV_ACCOUNT:nova-toll-alerts"; test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" sns list-subscriptions-by-topic --topic-arn "$TOPIC_ARN" --query 'Subscriptions[].Protocol' --output text)" = email
BUDGET="$(AWS_PROFILE=nova-toll-dev aws budgets describe-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly --query '{name:Budget.BudgetName,amount:Budget.BudgetLimit.Amount,unit:Budget.BudgetLimit.Unit,time:Budget.TimeUnit}' --output json)"; jq -e '.name == "nova-toll-monthly" and (.amount | tonumber) == 100 and .unit == "USD" and .time == "MONTHLY"' <<<"$BUDGET" >/dev/null
NOTIFICATIONS="$(AWS_PROFILE=nova-toll-dev aws budgets describe-notifications-for-budget --account-id "$DEV_ACCOUNT" --budget-name nova-toll-monthly --query 'Notifications[].{Type:NotificationType,Threshold:Threshold}' --output json)"; jq -e 'length == 3 and (map({Type,Threshold}) | sort_by(.Type,.Threshold)) == [{Type:"ACTUAL",Threshold:80},{Type:"ACTUAL",Threshold:100},{Type:"FORECASTED",Threshold:80}]' <<<"$NOTIFICATIONS" >/dev/null
SSM_COUNT=0; for parameter in /nova-toll/i95-token /nova-toll/i66-token /nova-toll/tailscale-authkey; do name="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'Parameters[0].Name' --output text 2>/dev/null || true)"; type="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" ssm describe-parameters --parameter-filters "Key=Name,Option=Equals,Values=$parameter" --query 'Parameters[0].Type' --output text 2>/dev/null || true)"; test "$name" = "$parameter"; test "$type" = SecureString; SSM_COUNT=$((SSM_COUNT + 1)); done; test "$SSM_COUNT" = 3
test "$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail-status --name nova-toll-audit --query IsLogging --output text 2>/dev/null || true)" = True
TRAIL="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-trail --name nova-toll-audit --query Trail --output json)"; AUDIT_KMS_ARN="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" kms describe-key --key-id alias/nova-toll-audit --query KeyMetadata.Arn --output text)"; jq -e --arg arn "$AUDIT_KMS_ARN" '.IsMultiRegionTrail and .IncludeGlobalServiceEvents and .LogFileValidationEnabled and .KmsKeyId == $arn' <<<"$TRAIL" >/dev/null
SELECTORS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudtrail get-event-selectors --trail-name nova-toll-audit --query AdvancedEventSelectors --output json)"; jq -e 'length == 2 and (map(.Name) | sort) == ["Management events","Protected S3 objects"] and (map(select(.Name == "Protected S3 objects"))[0] | tostring | contains("resources.ARN"))' <<<"$SELECTORS" >/dev/null
ALARMS="$(AWS_PROFILE=nova-toll-dev aws --region "$REGION" cloudwatch describe-alarms --alarm-names toll-fetcher-errors nova-toll-raw-storage-10gb nova-toll-tfstate-storage-10gb toll-rds-free-storage toll-rds-cpu toll-rds-free-memory toll-rds-connections toll-rds-cpu-credits --query 'MetricAlarms[].{name:AlarmName,state:StateValue}' --output json)"; jq -e 'length == 8 and ([.[].name] | sort) == ["nova-toll-raw-storage-10gb","nova-toll-tfstate-storage-10gb","toll-fetcher-errors","toll-rds-connections","toll-rds-cpu","toll-rds-cpu-credits","toll-rds-free-memory","toll-rds-free-storage"] and all(.[]; (.state | type == "string"))' <<<"$ALARMS" >/dev/null
failure_stage=production_isolation
test "$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" sts get-caller-identity --query Account --output text)" = "$PROD_ACCOUNT"
probe_denied() { local expected error_text return_code; expected=AccessDenied; test "$1" = s3api && expected='AccessDenied|403|Forbidden'; set +e; error_text="$(AWS_PROFILE=nova-toll-prod aws --region "$REGION" "$@" 2>&1 >/dev/null)"; return_code=$?; set -e; test "$return_code" -ne 0; if printf '%s' "$error_text" | grep -qiE "$expected"; then :; else fail; fi; }
probe_denied s3api head-object --bucket "$STATE_BUCKET" --key "$STATE_KEY"
probe_denied kms describe-key --key-id "$STATE_KMS_ARN"
trap - EXIT
printf 'state_bucket=%s; state_key=%s; state_kms_arn=%s; state_sse=aws:kms; state_versioning=Enabled; state_public_access_block=true; state_lockfile_absent=true; native_lock_migration=true; managed_state_count=95; managed_state_set=match; alias_count=4; bucket_count=4; network_endpoints=5; rds=available; fetcher=present; iam_roles=3; development_iam_roles_present=true; poll_rules=2; alert_email_subscriptions=1; budget_limit_usd=100; budget_notifications=3; ssm_securestring_metadata=3; cloudtrail_logging=true; cloudtrail_selectors=2; foundation_alarms=8; s3_denied=true; kms_denied=true\n' "$STATE_BUCKET" "$STATE_KEY" "$STATE_KMS_ARN"
)
```

If apply fails or is interrupted, do not restore the backend, migrate, retry,
delete, or replace the plan. Preserve the complete private root, retained
`.terraform-data`, local state/backups, binary plan, and fetcher. If migration
fails, preserve that post-restore root and all local/remote state evidence and
stop as well; only bounded read-only readiness retries in the success path are
permitted. The operator records only the fixed stage category, never an AWS or
Terraform error stream.

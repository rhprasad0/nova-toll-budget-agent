### Timed-check Scheduler bootstrap and verification (#345)

#### Descriptive evaluation-alert configuration

Descriptive evaluation alerts are a separate **administrator-reviewed**
configuration/IAM change. First, an administrator must separately authorize and
apply the exact account-local foundation planner-IAM plan before any application
plan resolves `data.aws_kms_alias.alerts`: development plan and development
delivery, plus the production planner where applicable, receive the exact
alert-key read. The production saved-plan apply-only identity does not re-plan
and receives no new read.

Second, an administrator must privately save and review an exact application
plan limited to `aws_iam_role_policy.timed_checks_lambda`,
`aws_lambda_function.timed_checks`, and
`aws_cloudwatch_metric_alarm.timed_checks_errors`. It must contain only the
approved IAM, literal environment, and alarm changes; the old handler safely
ignores the new variables. The plan must remain private, saved, and reviewed.
Stop and report the operational gate if alias
resolution lacks the foundation read, any unrelated or dependency-expanded
address appears, `aws_s3_object.timed_checks` has an action, the Lambda changes
`s3_key`, `filename`, `source_code_hash`, an equivalent package/code field, or
removes an existing environment variable, or the plan is not private, saved,
and reviewed. Do not widen the validator, add a path, or deliver code early to
bypass a stop. Only after that exact private saved plan is separately authorized
and applied may ordinary protected timed package delivery proceed.

Package delivery runs last and activates the reviewed handler; it cannot apply
IAM or Lambda-environment changes. This PR and runbook do not themselves
authorize either prerequisite apply.

Until this administrator step, a missing alert flag deliberately preserves the
generic Lambda error path. Inspect configuration and the existing terminal
records without sending a test email or logging payloads/secrets. The email's
CloudWatch log-stream URL is a best-effort console convenience link, not a
stable AWS API contract.

The first development deployment is **administrator-owned** because the recurring
delivery role cannot create IAM roles, Lambda configuration, queues, security
groups, alarms, or schedules. Build all five reviewed packages and the reviewed
development foundation variables as described in this runbook, then save a plan
with only these targets:

```bash
TIMED_TARGETS=(
  -target=aws_s3_object.timed_checks
  -target=aws_sqs_queue.timed_checks_invoke_failure
  -target=aws_sqs_queue.timed_checks_delivery_failure
  -target=aws_iam_role.timed_checks_lambda
  -target=aws_iam_role_policy_attachment.timed_checks_lambda_vpc
  -target=aws_iam_role_policy.timed_checks_lambda
  -target=aws_iam_role.timed_checks_scheduler
  -target=aws_iam_role_policy.timed_checks_scheduler
  -target=aws_security_group.timed_checks
  -target=aws_vpc_security_group_ingress_rule.rds_from_timed_checks
  -target=aws_vpc_security_group_egress_rule.timed_checks_to_rds
  -target=aws_vpc_security_group_egress_rule.timed_checks_https
  -target=aws_cloudwatch_log_group.timed_checks
  -target=aws_lambda_function.timed_checks
  -target=aws_lambda_function_event_invoke_config.timed_checks
  -target=aws_scheduler_schedule.timed_checks
  -target=aws_cloudwatch_metric_alarm.timed_checks_errors
  -target=aws_cloudwatch_metric_alarm.timed_checks_failure_queues
)
terraform -chdir="$ROOT/v2/infra" plan -input=false \
  -var-file=development.tfvars -var-file="$DEV_FOUNDATION_VARS" \
  -var loader_package_path="$ROOT/v2/infra/build/loader.zip" \
  -var publisher_package_path="$ROOT/v2/infra/build/publisher.zip" \
  -var agentcore_package_path="$ROOT/v2/infra/build/agentcore.zip" \
  -var chat_proxy_package_path="$ROOT/v2/infra/build/chat-proxy.zip" \
  -var timed_checks_package_path="$ROOT/v2/infra/build/timed-checks.zip" \
  "${TIMED_TARGETS[@]}" -out="$ROOT/v2/infra/build/timed-checks-bootstrap.tfplan"
```

An administrator must review the saved plan and apply that exact file. It must
create only the targets above in account `903859731897`; stop for any update,
delete, replacement, production value, public subnet/RDS path, or additional
address. Do not grant the recurring delivery identity create, IAM-policy,
network-write, alarm-write, or Lambda-configuration permissions. After bootstrap,
the ordinary development plan must pass the finite release validator and contain
only the reviewed package upload, Lambda code update, and exact schedule updates.

Verify deployment without logging payloads or secrets:

```bash
aws --region us-east-1 scheduler list-schedules \
  --query 'Schedules[?starts_with(Name, `nova-toll-v2-`) && ends_with(Name, `-dev`) && contains(Name, `i95`) || starts_with(Name, `nova-toll-v2-greenway-`) && ends_with(Name, `-dev`)].{Name:Name,State:State}'
aws --region us-east-1 lambda get-function-configuration \
  --function-name nova-toll-v2-timed-checks-dev \
  --query '{State:State,LastUpdateStatus:LastUpdateStatus,VpcId:VpcConfig.VpcId}'
aws --region us-east-1 logs tail /aws/lambda/nova-toll-v2-timed-checks-dev \
  --since 24h --filter-pattern timed_checks_result
```

Confirm **28 enabled schedules** and one successful terminal result for each of
the five window IDs before treating development as verified. Production remains
plan-only until the protected production delivery pipeline supports this exact
resource set.

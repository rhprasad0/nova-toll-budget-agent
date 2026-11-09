# Organization circuit breaker

Takes the production and development accounts down when organization-wide AWS
spend for the month passes the budget limit ($250). This is a deliberate outage.

An hourly Lambda in the management account reads the budget. Over the limit, it
attaches a deny-all SCP to both child accounts, then in every region stops RDS
and EC2 instances, sets Lambda reserved concurrency to 0, and disables the
primary CloudFront distributions. Everything stays down, including across month
boundaries, until someone restores it.

It is a backstop, not a hard cap: AWS billing data can lag by up to a day. VPC
endpoints, WAF, KMS keys and storage keep billing while it is tripped. OpenAI
spend is not on the AWS bill.

## Apply

Use the management account (`nova-toll-org`). Enabling SCPs is one-time:

```sh
ROOT=$(aws organizations list-roots --query 'Roots[0].Id' --output text)
aws organizations enable-policy-type --root-id "$ROOT" --policy-type SERVICE_CONTROL_POLICY
terraform init
TF_VAR_alert_email=you@example.com terraform apply
```

Confirm the SNS subscription email, or Lambda failure alarms will not arrive.

## Test on development only

Attaching the SCP by hand trips only that account:

```sh
aws organizations attach-policy --policy-id "$(terraform output -raw scp_policy_id)" --target-id 903859731897
aws lambda invoke --function-name org-circuit-breaker --cli-read-timeout 0 /dev/stdout
```

## Recover

Investigate first. Development `AdministratorAccess` SSO sessions keep working
while tripped, but the production root login is denied, so assume
`OrganizationAccountAccessRole` from the management account instead. Do not run
`terraform apply` in a child account while it is tripped: it can remove the tags
that restore depends on.

If spend is still over the limit, raise `monthly_limit_usd` and apply, or the
restore will refuse. Keep passing the raised value until the month ends, because
an apply without it resets the limit and can trip again.

Then run this. If a resource is still stopping, run it again within the hour,
because the next hourly sweep shuts a partly restored account back down:

```sh
aws lambda invoke --function-name org-circuit-breaker --cli-read-timeout 0 \
  --cli-binary-format raw-in-base64-out --payload '{"action":"restore"}' /dev/stdout
```

Restore uses the `circuit-breaker-prior` tag on each changed resource and detaches
the SCP from an account only after that account is fully restored. RDS and
CloudFront can take several minutes to come back.

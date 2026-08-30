# Legacy development inventory

This is a **point-in-time, read-only** inventory of legacy development resources
in production account `920534282028`. It is the authoritative cleanup input for
#333, not a destruction plan. Before any approved cleanup, #333 must refresh and
reconcile it.

Evidence was collected on 2026-08-30 from the legacy Terraform backend key
`nova-toll/v2/development/terraform.tfstate` and a production Resource Groups
Tagging API cross-check.

## Terraform-state inventory

- 5 Lambda functions; 1 AgentCore runtime and 1 endpoint; 1 DynamoDB table.
- 2 S3 buckets and 25 managed S3 objects. The objects are deployment artifacts
  and site content, not independent buckets.
- 1 CloudFront distribution; 1 API Gateway REST API/stage; 1 WAF ACL.
- 4 SQS queues; 7 IAM roles; 4 security groups with 13 managed rules.
- 5 EventBridge rules/targets; 7 log groups; 20 alarms.
- Athena/Glue reporting resources and related IAM, KMS, and S3 policy resources.

The tagging API returned 77 resources tagged `environment=development`. It is an
incomplete cross-check because non-taggable resources and some state resources
are not returned; Terraform state is the cleanup source of truth.

The production PostgreSQL database `nova_toll_development` and its
`_development` roles are **unverified targets** for #333. They were not
enumerated through the read-only AWS APIs used for this inventory.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- toll-fetcher ---------------------------------------------------------

resource "aws_iam_role" "fetcher" {
  name               = "toll-fetcher"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "fetcher_basic" {
  role       = aws_iam_role.fetcher.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "fetcher" {
  statement {
    sid     = "PutRawObjects"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
  }

  statement {
    sid       = "EncryptRawObjects"
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.raw.arn]
  }

  statement {
    sid     = "ReadTokens"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.i95_token_param_name}",
      "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.i66_token_param_name}",
    ]
  }

  statement {
    sid       = "PutPollMetric"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # CloudWatch metrics have no resource ARNs; scoped by namespace condition below.
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["NovaToll"]
    }
  }
}

resource "aws_iam_role_policy" "fetcher" {
  name   = "toll-fetcher"
  role   = aws_iam_role.fetcher.id
  policy = data.aws_iam_policy_document.fetcher.json
}

# The replay role is intentionally separate from Terraform and the Lambda
# execution roles. An account identity must have both sts:AssumeRole and an
# MFA-authenticated session to use it.
data "aws_iam_policy_document" "replay_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role" "replay" {
  name                 = "toll-raw-replay"
  assume_role_policy   = data.aws_iam_policy_document.replay_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "replay" {
  statement {
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.raw.arn}/raw/feed=i95/*",
      "${aws_s3_bucket.raw.arn}/raw/feed=i66/*",
    ]
  }

  statement {
    actions   = ["kms:Encrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.raw.arn]
  }
}

resource "aws_iam_role_policy" "replay" {
  name   = "toll-raw-replay"
  role   = aws_iam_role.replay.id
  policy = data.aws_iam_policy_document.replay.json
}

# --- GitHub Actions OIDC foundation retained for v2 timed checks -----------

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# --- GitHub Actions development delivery ----------------------------------
# This role is deliberately managed by the account-local foundation root, but
# only exists when that root is applying the development account.

locals {
  development_delivery_account_id = "903859731897"
  development_delivery_region     = "us-east-1"
  development_delivery_role_names = [
    "toll-v2-pricing-loader-dev",
    "toll-v2-report-publisher-dev",
    "toll-v2-report-publisher-scheduler-dev",
    "nova-toll-v2-timed-checks-dev",
    "nova-toll-v2-agentcore-runtime-dev",
    "nova-toll-v2-chat-proxy-dev",
    "tollchat-v2-agent-usage-rollup-dev",
  ]
  development_delivery_role_arns = [
    for role_name in local.development_delivery_role_names :
    "arn:aws:iam::${local.development_delivery_account_id}:role/${role_name}"
  ]
  development_delivery_lambda_arns = [
    for function_name in [
      "toll-v2-pricing-loader-dev",
      "toll-v2-report-publisher-dev",
      "tollchat-v2-chat-proxy-dev",
    ] : "arn:aws:lambda:${local.development_delivery_region}:${local.development_delivery_account_id}:function:${function_name}"
  ]
  development_delivery_lambda_resources = flatten([
    for arn in local.development_delivery_lambda_arns : [arn, "${arn}:*"]
  ])
  # Retained for state refresh only; the retired rollup is not a delivery target.
  development_delivery_legacy_rollup_lambda_resources = [
    "arn:aws:lambda:${local.development_delivery_region}:${local.development_delivery_account_id}:function:tollchat-v2-agent-usage-rollup-dev",
    "arn:aws:lambda:${local.development_delivery_region}:${local.development_delivery_account_id}:function:tollchat-v2-agent-usage-rollup-dev:*",
  ]
  development_delivery_queue_arns = [
    for queue_name in [
      "toll-v2-pricing-loader-invoke-failure-dev",
      "toll-v2-pricing-loader-delivery-failure-dev",
      "toll-v2-report-publisher-invoke-failure-dev",
      "toll-v2-report-publisher-delivery-failure-dev",
    ] : "arn:aws:sqs:${local.development_delivery_region}:${local.development_delivery_account_id}:${queue_name}"
  ]
  development_delivery_event_rule_arns = [
    for rule_name in [
      "toll-v2-pricing-raw-objects-dev",
    ] : "arn:aws:events:${local.development_delivery_region}:${local.development_delivery_account_id}:rule/${rule_name}"
  ]
  development_delivery_legacy_rollup_event_rule_arn = "arn:aws:events:${local.development_delivery_region}:${local.development_delivery_account_id}:rule/tollchat-v2-agent-usage-rollup-dev"
  development_delivery_log_group_arns = [
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/toll-v2-pricing-loader-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/toll-v2-report-publisher-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-usage-publisher-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
  ]
  development_delivery_legacy_rollup_log_group_arn = "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-agent-usage-rollup-dev"
  development_delivery_alarm_arns = [
    for alarm_name in [
      "toll-v2-pricing-freshness-i66-dev",
      "toll-v2-pricing-freshness-i95-dev",
      "toll-v2-pricing-loader-delivery-failure-queue-dev",
      "toll-v2-pricing-loader-errors-dev",
      "toll-v2-pricing-loader-invoke-failure-queue-dev",
      "toll-v2-report-generation-freshness-dev",
      "toll-v2-report-publisher-delivery-failure-queue-dev",
      "toll-v2-report-publisher-errors-dev",
      "toll-v2-report-publisher-invoke-failure-queue-dev",
      "tollchat-v2-agentcore-active-sessions-dev",
      "tollchat-v2-chat-proxy-errors-dev",
      "tollchat-v2-chat-proxy-failures-dev",
      "tollchat-v2-chat-proxy-latency-dev",
    ] : "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:${alarm_name}"
  ]
  development_delivery_legacy_rollup_alarm_arns = [
    "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:tollchat-v2-agent-usage-log-coverage-dev",
    "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:tollchat-v2-agent-usage-rollup-errors-dev",
    "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:tollchat-v2-agent-usage-rollup-missing-dev",
  ]
  # Exact, one-time teardown targets for the retired stateless usage writer.
  # Historical usage data and its log group are deliberately not in this set.
  development_delivery_usage_publisher_role_arn   = "arn:aws:iam::${local.development_delivery_account_id}:role/tollchat-v2-usage-publisher-dev"
  development_delivery_usage_publisher_lambda_arn = "arn:aws:lambda:${local.development_delivery_region}:${local.development_delivery_account_id}:function:tollchat-v2-usage-publisher-dev"
  development_delivery_usage_publisher_rule_arn   = "arn:aws:events:${local.development_delivery_region}:${local.development_delivery_account_id}:rule/tollchat-v2-usage-publisher-dev"
  development_delivery_usage_publisher_alarm_arns = [
    "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:tollchat-v2-usage-publisher-errors-dev",
    "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:tollchat-v2-usage-publisher-failed-invocations-dev",
  ]
  development_delivery_api_id                 = "ocw8sg0wlb"
  development_delivery_distribution_arn       = "arn:aws:cloudfront::${local.development_delivery_account_id}:distribution/E33DVF3KT7BTAC"
  development_delivery_guardrail_arn          = "arn:aws:bedrock:${local.development_delivery_region}:${local.development_delivery_account_id}:guardrail/vdyqrh31xgca"
  development_delivery_agentcore_runtime_arn  = "arn:aws:bedrock-agentcore:${local.development_delivery_region}:${local.development_delivery_account_id}:runtime/nova_toll_v2_development-Y69XBf88Bl"
  development_delivery_agentcore_endpoint_arn = "${local.development_delivery_agentcore_runtime_arn}/runtime-endpoint/preview"
  development_delivery_api_deployment_arns = [
    "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/deployments",
    "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/deployments/*",
  ]
  development_delivery_application_key_arns = [
    "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:key/3bc78b60-9cbe-4abd-9744-8772c78d8379",
  ]
  development_delivery_measurement_key_arn    = "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:key/076e8341-894b-405c-96e9-2b037f96e2a6"
  development_delivery_site_bucket_arn        = "arn:aws:s3:::tollchat-site-${local.development_delivery_account_id}-dev"
  development_delivery_measurement_bucket_arn = "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${local.development_delivery_account_id}-dev"
  development_delivery_artifact_bucket_arn    = "arn:aws:s3:::nova-toll-agentcore-${local.development_delivery_account_id}"
}

data "aws_iam_policy_document" "development_delivery_assume" {
  statement {
    sid     = "GitHubDevelopmentEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"]
    }
  }
}

# The migration runner is a separate, development-only identity. It can read
# the endpoint metadata needed by the protected job and authenticate only as
# the fixed schema migrator database role.
data "aws_iam_policy_document" "development_migrations_assume" {
  count = var.environment == "development" ? 1 : 0

  statement {
    sid     = "GitHubDevelopmentEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"]
    }
  }
}

data "aws_iam_policy_document" "development_migrations" {
  count = var.environment == "development" ? 1 : 0

  statement {
    sid       = "DescribeDevelopmentRds"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["arn:aws:rds:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:db:${aws_db_instance.main.identifier}"]
  }

  statement {
    sid       = "ConnectAsSchemaMigrator"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.main.resource_id}/schema_migrator_development"]
  }
}

resource "aws_iam_role" "development_migrations" {
  count                = var.environment == "development" ? 1 : 0
  name                 = "nova-toll-v2-development-migrations-dev"
  assume_role_policy   = data.aws_iam_policy_document.development_migrations_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "development_migrations" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-development-migrations-dev"
  role   = aws_iam_role.development_migrations[0].id
  policy = data.aws_iam_policy_document.development_migrations[0].json
}

data "aws_iam_policy_document" "development_delivery" {
  # Terraform state is the only shared control-plane data this role can read.
  statement {
    sid       = "ListDevelopmentState"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values = [
        "nova-toll/development/terraform.tfstate",
        "nova-toll/v2/development/terraform.tfstate",
      ]
    }
  }

  statement {
    sid       = "ReadDevelopmentFoundationState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate"]
  }

  statement {
    sid       = "ManageDevelopmentApplicationState"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate"]
  }

  statement {
    sid       = "ManageDevelopmentApplicationLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock"]
  }

  statement {
    sid       = "DecryptDevelopmentState"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock",
      ]
    }
  }

  statement {
    sid       = "WriteDevelopmentStateDataKeys"
    actions   = ["kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock",
      ]
    }
  }

  statement {
    sid = "ReadPreprovisionedApplicationRoles"
    actions = [
      "iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags",
    ]
    resources = local.development_delivery_role_arns
  }

  statement {
    sid = "ReadApplicationLambdaFunctions"
    actions = [
      "lambda:GetAlias", "lambda:GetFunction", "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionConfiguration", "lambda:GetFunctionEventInvokeConfig",
      "lambda:GetFunctionUrlConfig", "lambda:GetPolicy", "lambda:GetProvisionedConcurrencyConfig", "lambda:ListAliases",
      "lambda:ListProvisionedConcurrencyConfigs", "lambda:ListTags", "lambda:ListVersionsByFunction",
    ]
    resources = concat(
      local.development_delivery_lambda_resources,
      local.development_delivery_legacy_rollup_lambda_resources,
    )
  }

  statement {
    sid = "UpdateApplicationLambdaFunctions"
    # Code and qualified-version releases are routine; function role/configuration
    # and public URL changes remain administrator-owned bootstrap operations.
    actions   = ["lambda:TagResource", "lambda:UntagResource", "lambda:UpdateAlias", "lambda:UpdateFunctionCode"]
    resources = local.development_delivery_lambda_resources
  }

  statement {
    sid       = "PublishApplicationLambdaVersions"
    actions   = ["lambda:PublishVersion"]
    resources = local.development_delivery_lambda_arns
  }

  statement {
    sid     = "RetireApplicationLambdaVersions"
    actions = ["lambda:DeleteFunction"]
    resources = [
      for function_arn in local.development_delivery_lambda_arns : "${function_arn}:*"
    ]
  }

  statement {
    sid = "ManageApplicationQueues"
    # Queue policies and queue configuration remain manual-owned; CI is read-only.
    actions   = ["sqs:GetQueueAttributes", "sqs:ListQueueTags"]
    resources = local.development_delivery_queue_arns
  }

  statement {
    sid       = "ResolveApplicationQueueUrls"
    actions   = ["sqs:GetQueueUrl"]
    resources = ["arn:aws:sqs:${local.development_delivery_region}:${local.development_delivery_account_id}:toll-v2-*-failure-dev"]
  }

  statement {
    sid       = "ManageApplicationEventRules"
    actions   = ["events:DescribeRule", "events:DisableRule", "events:EnableRule", "events:ListTagsForResource", "events:ListTargetsByRule", "events:PutTargets", "events:RemoveTargets", "events:TagResource", "events:UntagResource"]
    resources = local.development_delivery_event_rule_arns
  }

  statement {
    sid       = "ReadRetainedRollupEventRule"
    actions   = ["events:DescribeRule", "events:ListTagsForResource", "events:ListTargetsByRule"]
    resources = [local.development_delivery_legacy_rollup_event_rule_arn]
  }

  statement {
    sid       = "ManageApplicationLogs"
    actions   = ["logs:DescribeMetricFilters", "logs:ListTagsForResource", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"]
    resources = local.development_delivery_log_group_arns
  }

  statement {
    sid       = "ReadRetainedRollupLogGroup"
    actions   = ["logs:DescribeMetricFilters", "logs:ListTagsForResource"]
    resources = [local.development_delivery_legacy_rollup_log_group_arn]
  }

  statement {
    sid       = "DescribeApplicationLogPolicies"
    actions   = ["logs:DescribeResourcePolicies"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid       = "DescribeApplicationLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid       = "ManageApplicationAlarms"
    actions   = ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource", "cloudwatch:TagResource", "cloudwatch:UntagResource"]
    resources = local.development_delivery_alarm_arns
  }

  statement {
    sid       = "ReadRetainedRollupAlarms"
    actions   = ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"]
    resources = local.development_delivery_legacy_rollup_alarm_arns
  }

  statement {
    sid       = "DescribeApplicationNetworking"
    actions   = ["ec2:DescribePrefixLists", "ec2:DescribeSecurityGroupRules", "ec2:DescribeSecurityGroups", "ec2:DescribeSubnets", "ec2:DescribeVpcs"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid       = "ManageApplicationSiteBuckets"
    actions   = ["s3:DeleteObject", "s3:GetAccelerateConfiguration", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLocation", "s3:GetBucketLogging", "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketRequestPayment", "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetBucketWebsite", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectTagging", "s3:GetObjectVersion", "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:ListBucketVersions", "s3:PutBucketOwnershipControls", "s3:PutBucketTagging", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration", "s3:PutObject", "s3:PutObjectTagging"]
    resources = [local.development_delivery_site_bucket_arn, "${local.development_delivery_site_bucket_arn}/*"]
  }

  statement {
    sid       = "ManageApplicationMeasurementBucket"
    actions   = ["s3:GetAccelerateConfiguration", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLocation", "s3:GetBucketLogging", "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketRequestPayment", "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetBucketWebsite", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:ListBucketVersions"]
    resources = [local.development_delivery_measurement_bucket_arn]
  }

  statement {
    sid       = "ReadRetainedApplicationMeasurementRegistry"
    actions   = ["s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectTagging", "s3:GetObjectVersion"]
    resources = ["${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson"]
  }

  statement {
    sid     = "PublishApplicationArtifacts"
    actions = ["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectTagging", "s3:GetObjectVersion", "s3:ListBucketMultipartUploads", "s3:ListMultipartUploadParts", "s3:PutObject", "s3:PutObjectTagging"]
    resources = [
      "${local.development_delivery_artifact_bucket_arn}/runtime/v2/*",
      "${local.development_delivery_artifact_bucket_arn}/lambda/v2/*",
    ]
  }

  statement {
    sid       = "ReadApplicationArtifactBucket"
    actions   = ["s3:GetBucketLocation"]
    resources = [local.development_delivery_artifact_bucket_arn]
  }

  statement {
    sid       = "UseApplicationKmsKeys"
    actions   = ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags"]
    resources = local.development_delivery_application_key_arns
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = ["development"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/version"
      values   = ["v2"]
    }
  }

  statement {
    sid       = "ReadRetainedMeasurementKey"
    actions   = ["kms:Decrypt", "kms:DescribeKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags"]
    resources = [local.development_delivery_measurement_key_arn]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/environment"
      values   = ["development"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/version"
      values   = ["v2"]
    }
  }

  statement {
    sid = "ReadApplicationKmsAliases"
    # The provider resolves aliases by listing regional account metadata.
    actions   = ["kms:ListAliases"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid       = "ManageApplicationSessions"
    actions   = ["dynamodb:DescribeContinuousBackups", "dynamodb:DescribeTable", "dynamodb:DescribeTimeToLive", "dynamodb:ListTagsOfResource", "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:UpdateContinuousBackups", "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive"]
    resources = ["arn:aws:dynamodb:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat-v2-anonymous-sessions-dev"]
  }

  statement {
    sid     = "ReadRetainedApplicationCatalog"
    actions = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetTags"]
    resources = [
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:catalog",
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:database/tollchat_agent_reports_development",
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat_agent_reports_development/*",
    ]
  }

  statement {
    sid = "ReadRetainedApplicationAthenaNamedQueries"
    # Retained named-query reads authorize against their workgroup, not a query ARN.
    actions   = ["athena:GetNamedQuery", "athena:ListTagsForResource"]
    resources = ["arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:workgroup/tollchat-agent-reports-dev"]
  }

  statement {
    sid     = "ReadRetainedApplicationAthenaWorkGroup"
    actions = ["athena:GetWorkGroup", "athena:ListNamedQueries", "athena:ListTagsForResource"]
    resources = [
      "arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:workgroup/tollchat-agent-reports-dev",
    ]
  }

  statement {
    sid       = "ListApplicationAthenaWorkGroups"
    actions   = ["athena:ListWorkGroups"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid     = "ManageApplicationSchedules"
    actions = ["scheduler:GetSchedule", "scheduler:ListTagsForResource", "scheduler:TagResource", "scheduler:UntagResource", "scheduler:UpdateSchedule"]
    resources = [
      "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule/*/toll-v2-report-publisher-dev",
      "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule-group/default",
    ]
  }

  statement {
    sid = "ReadRetiredUsagePublisherIam"
    actions = [
      "iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags",
    ]
    resources = [local.development_delivery_usage_publisher_role_arn]
  }

  statement {
    sid = "ReadRetiredUsagePublisherLambda"
    actions = [
      "lambda:GetAlias", "lambda:GetFunction", "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionConfiguration",
      "lambda:GetFunctionEventInvokeConfig", "lambda:GetFunctionUrlConfig", "lambda:GetPolicy", "lambda:GetProvisionedConcurrencyConfig",
      "lambda:ListAliases", "lambda:ListProvisionedConcurrencyConfigs", "lambda:ListTags", "lambda:ListVersionsByFunction",
    ]
    resources = [local.development_delivery_usage_publisher_lambda_arn]
  }

  statement {
    sid       = "ReadRetiredUsagePublisherEvents"
    actions   = ["events:DescribeRule", "events:ListTagsForResource", "events:ListTargetsByRule"]
    resources = [local.development_delivery_usage_publisher_rule_arn]
  }

  statement {
    sid       = "ReadRetiredUsagePublisherAlarms"
    actions   = ["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"]
    resources = local.development_delivery_usage_publisher_alarm_arns
  }

  statement {
    sid       = "RetireUsagePublisherIam"
    actions   = ["iam:DeleteRole", "iam:DeleteRolePolicy"]
    resources = [local.development_delivery_usage_publisher_role_arn]
  }

  statement {
    sid       = "RetireUsagePublisherLambda"
    actions   = ["lambda:DeleteFunction", "lambda:RemovePermission"]
    resources = [local.development_delivery_usage_publisher_lambda_arn]
  }

  statement {
    sid       = "RetireUsagePublisherEvents"
    actions   = ["events:DeleteRule", "events:RemoveTargets"]
    resources = [local.development_delivery_usage_publisher_rule_arn]
  }

  statement {
    sid       = "RetireUsagePublisherAlarms"
    actions   = ["cloudwatch:DeleteAlarms"]
    resources = local.development_delivery_usage_publisher_alarm_arns
  }

  statement {
    sid       = "ManageApplicationGuardrail"
    actions   = ["bedrock:GetGuardrail", "bedrock:ListTagsForResource"]
    resources = [local.development_delivery_guardrail_arn]
  }

  statement {
    sid       = "PublishApplicationGuardrailVersions"
    actions   = ["bedrock:CreateGuardrailVersion"]
    resources = [local.development_delivery_guardrail_arn]
  }

  statement {
    sid     = "ManageApplicationAgentCore"
    actions = ["bedrock-agentcore:GetAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint", "bedrock-agentcore:GetResourcePolicy", "bedrock-agentcore:ListTagsForResource", "bedrock-agentcore:TagResource", "bedrock-agentcore:UntagResource", "bedrock-agentcore:UpdateAgentRuntime", "bedrock-agentcore:UpdateAgentRuntimeEndpoint"]
    resources = [
      local.development_delivery_agentcore_runtime_arn,
      local.development_delivery_agentcore_endpoint_arn,
    ]
  }

  statement {
    sid = "PassExistingAgentCoreRuntimeRole"
    # UpdateAgentRuntime requires its existing roleArn even for code-only updates.
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock-agentcore.amazonaws.com"]
    }
  }

  statement {
    sid     = "ReadApplicationApiGateway"
    actions = ["apigateway:GET"]
    resources = [
      "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
      "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/*",
    ]
  }

  statement {
    sid       = "PublishApplicationApiGatewayDeployments"
    actions   = ["apigateway:DELETE", "apigateway:POST"]
    resources = local.development_delivery_api_deployment_arns
  }

  statement {
    sid     = "ManageApplicationCloudFront"
    actions = ["cloudfront:DescribeFunction", "cloudfront:GetFunction", "cloudfront:ListTagsForResource", "cloudfront:PublishFunction", "cloudfront:TagResource", "cloudfront:TestFunction", "cloudfront:UntagResource", "cloudfront:UpdateFunction"]
    resources = [
      "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
      "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-report-routes-dev",
    ]
  }

  statement {
    sid     = "ReadApplicationCloudFront"
    actions = ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:GetOriginAccessControl", "cloudfront:GetResponseHeadersPolicy", "cloudfront:ListTagsForResource"]
    resources = [
      local.development_delivery_distribution_arn,
      "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-access-control/*",
      "arn:aws:cloudfront::${local.development_delivery_account_id}:response-headers-policy/*",
    ]
  }

  statement {
    sid       = "ReadManagedCloudFrontPolicies"
    actions   = ["cloudfront:ListCachePolicies", "cloudfront:ListOriginRequestPolicies"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.development_delivery_region]
    }
  }

  statement {
    sid = "ReadManagedCloudFrontPolicy"
    actions = [
      "cloudfront:GetCachePolicy",
      "cloudfront:GetOriginRequestPolicy",
    ]
    resources = [
      "arn:aws:cloudfront::${local.development_delivery_account_id}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
      "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac",
    ]
  }

  statement {
    sid       = "ManageApplicationWaf"
    actions   = ["wafv2:GetLoggingConfiguration", "wafv2:GetWebACL", "wafv2:ListTagsForResource"]
    resources = ["arn:aws:wafv2:${local.development_delivery_region}:${local.development_delivery_account_id}:global/webacl/tollchat-v2-public-chat-dev/*"]
  }

  statement {
    sid       = "ReadDevelopmentCertificate"
    actions   = ["acm:DescribeCertificate", "acm:ListTagsForCertificate"]
    resources = ["arn:aws:acm:us-east-1:903859731897:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20"]
  }
}

resource "aws_iam_role" "development_delivery" {
  count                = var.environment == "development" ? 1 : 0
  name                 = "nova-toll-v2-development-delivery"
  assume_role_policy   = data.aws_iam_policy_document.development_delivery_assume.json
  max_session_duration = 3600
}

# Keep the reviewed statement order and allowlist, but store it as deterministic
# customer-managed policy documents. IAM's role-wide inline-policy quota is
# aggregate, so inline policies cannot safely represent this allowlist.
locals {
  development_delivery_policy_statements = jsondecode(data.aws_iam_policy_document.development_delivery.json).Statement
  development_delivery_policy_documents = {
    state = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 0, 7)
    })
    compute = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 7, 13)
    })
    observability = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 13, 22)
    })
    storage = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 22, 27)
    })
    data = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 27, 35)
    })
    runtime = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 35, 48)
    })
    edge = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 48, 56)
    })
  }
}

resource "aws_iam_policy" "development_delivery" {
  for_each = var.environment == "development" ? local.development_delivery_policy_documents : {}
  name     = "nova-toll-v2-development-delivery-${each.key}"
  path     = "/nova-toll/v2/development/"
  policy   = each.value
}

resource "aws_iam_role_policy_attachment" "development_delivery" {
  for_each   = var.environment == "development" ? local.development_delivery_policy_documents : {}
  role       = aws_iam_role.development_delivery[0].name
  policy_arn = aws_iam_policy.development_delivery[each.key].arn
}

# The DNS cutover is deliberately separate from both application delivery
# roles. It is the only foundation identity that can read the handoff token.
locals {
  production_foundation_dns_parameter_arn = "arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-development-dns-api-token"
}

data "aws_iam_policy_document" "production_foundation_dns_assume" {
  count = var.environment == "production" ? 1 : 0

  statement {
    sid     = "GitHubProductionFoundationDnsEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production-foundation-dns"]
    }
  }
}

data "aws_iam_policy_document" "production_foundation_dns" {
  count = var.environment == "production" ? 1 : 0

  statement {
    sid       = "ReadCloudflareDevelopmentToken"
    actions   = ["ssm:GetParameter"]
    resources = [local.production_foundation_dns_parameter_arn]
  }
}

resource "aws_iam_role" "production_foundation_dns" {
  count                = var.environment == "production" ? 1 : 0
  name                 = "nova-toll-production-foundation-dns"
  assume_role_policy   = data.aws_iam_policy_document.production_foundation_dns_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "production_foundation_dns" {
  count  = var.environment == "production" ? 1 : 0
  name   = "nova-toll-production-foundation-dns"
  role   = aws_iam_role.production_foundation_dns[0].id
  policy = data.aws_iam_policy_document.production_foundation_dns[0].json
}

# --- GitHub Actions production planner/deploy identities ------------------
# Keep the reviewed application action categories in one source document and
# translate its account-local names for production. Backend and plan access
# are separate statements below so the two roles cannot be interchanged.
locals {
  production_delivery_account_id = "920534282028"
  production_delivery_region     = "us-east-1"
  production_delivery_state_arns = [
    "${aws_s3_bucket.tfstate.arn}/nova-toll/terraform.tfstate",
    "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate",
  ]
  production_delivery_lock_arn = "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock"
  production_delivery_plan_arn = "${aws_s3_bucket.tfstate.arn}/plans/*/*/release.tfplan"

  production_delivery_agentcore_runtime_arn = "arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44"
  production_delivery_agentcore_preview_arn = "${local.production_delivery_agentcore_runtime_arn}/runtime-endpoint/preview"
  production_delivery_agentcore_default_arn = "${local.production_delivery_agentcore_runtime_arn}/runtime-endpoint/DEFAULT"
  production_delivery_guardrail_arn         = "arn:aws:bedrock:us-east-1:920534282028:guardrail/k0n0rkm24p9p"
  production_delivery_api_id                = "mxey1r2rhc"
  production_delivery_api_arn               = "arn:aws:apigateway:us-east-1::/restapis/mxey1r2rhc"
  production_delivery_waf_arn               = "arn:aws:wafv2:us-east-1:920534282028:global/webacl/tollchat-v2-public-chat/4f3f1888-76ef-4b89-9170-de501ed515d8"
  production_delivery_distribution_arn      = "arn:aws:cloudfront::920534282028:distribution/E16XVTXNFUS8T4"
  production_delivery_certificate_arn       = "arn:aws:acm:us-east-1:920534282028:certificate/a1d9cd35-9317-4f69-8146-3dbdf4d75e06"
  production_delivery_measurement_key_arn   = "arn:aws:kms:us-east-1:920534282028:key/b1d6d4b1-2370-403e-b735-f29b958703aa"
  production_delivery_site_key_arn          = "arn:aws:kms:us-east-1:920534282028:key/e6413a73-bf0f-438e-88be-74070724d5a1"
  production_delivery_cloudflare_param_arn  = "arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-read-api-token"
  production_delivery_cloudflare_key_arn    = "arn:aws:kms:us-east-1:920534282028:key/49d9dfb4-f9a7-465a-a3a1-e7bb394dd0de"

  # This is the existing reviewed development policy with only account-local
  # production identifiers changed. The first six state statements are
  # discarded; each identity gets its own narrower backend contract below.
  production_delivery_application_policy_base_json = replace(
    replace(
      replace(
        replace(
          replace(
            replace(
              replace(
                replace(
                  replace(
                    replace(
                      replace(
                        replace(
                          replace(
                            replace(
                              data.aws_iam_policy_document.development_delivery.json,
                              local.development_delivery_account_id,
                              local.production_delivery_account_id,
                            ),
                            "nova-toll/development/",
                            "nova-toll/",
                          ),
                          "nova-toll/v2/development/",
                          "nova-toll/v2/",
                        ),
                        "tollchat_agent_reports_development",
                        "tollchat_agent_reports",
                      ),
                      "\"development\"",
                      "\"production\"",
                    ),
                    "ReadDevelopmentCertificate",
                    "ReadProductionCertificate",
                  ),
                  "nova_toll_v2_development-Y69XBf88Bl",
                  "nova_toll_v2-W6989LEw44",
                ),
                split("/", local.development_delivery_guardrail_arn)[1],
                split("/", local.production_delivery_guardrail_arn)[1],
              ),
              "076e8341-894b-405c-96e9-2b037f96e2a6",
              "b1d6d4b1-2370-403e-b735-f29b958703aa",
            ),
            "3bc78b60-9cbe-4abd-9744-8772c78d8379",
            "e6413a73-bf0f-438e-88be-74070724d5a1",
          ),
          split("/", local.development_delivery_distribution_arn)[1],
          split("/", local.production_delivery_distribution_arn)[1],
        ),
        "arn:aws:wafv2:us-east-1:920534282028:global/webacl/tollchat-v2-public-chat/*",
        "arn:aws:wafv2:us-east-1:920534282028:global/webacl/tollchat-v2-public-chat/4f3f1888-76ef-4b89-9170-de501ed515d8",
      ),
      "-dev",
      "",
    ),
    "\"development\"",
    "\"production\"",
  )
  production_delivery_application_policy_api_json = replace(
    local.production_delivery_application_policy_base_json,
    "arn:aws:apigateway:${local.production_delivery_region}::/restapis/${local.development_delivery_api_id}",
    local.production_delivery_api_arn,
  )
  production_delivery_application_policy_json = replace(
    local.production_delivery_application_policy_api_json,
    "arn:aws:acm:us-east-1:920534282028:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20",
    local.production_delivery_certificate_arn,
  )
  production_delivery_application_policy_statements = [
    for statement in slice(
      jsondecode(local.production_delivery_application_policy_json).Statement,
      6,
      length(jsondecode(local.production_delivery_application_policy_json).Statement),
    ) : statement
    if !contains([
      "PassExistingAgentCoreRuntimeRole",
      "RetireUsagePublisherIam",
      "RetireUsagePublisherLambda",
      "RetireUsagePublisherEvents",
      "RetireUsagePublisherAlarms",
    ], statement.Sid)
  ]

  production_delivery_read_prefixes = ["Get", "List", "Describe", "GET"]
  production_delivery_discovery_statements = [
    for statement in local.production_delivery_application_policy_statements : merge(statement, {
      Action = [
        for action in try(tolist(statement.Action), [statement.Action]) : action
        if anytrue([
          for prefix in local.production_delivery_read_prefixes : startswith(action, "${split(":", action)[0]}:${prefix}")
        ])
      ]
    })
    if length([
      for action in try(tolist(statement.Action), [statement.Action]) : action
      if anytrue([
        for prefix in local.production_delivery_read_prefixes : startswith(action, "${split(":", action)[0]}:${prefix}")
      ])
    ]) > 0
  ]

  production_delivery_agentcore_default_statement = {
    Sid      = "ReadProductionAgentCoreDefaultEndpoint"
    Effect   = "Allow"
    Action   = ["bedrock-agentcore:GetAgentRuntimeEndpoint"]
    Resource = [local.production_delivery_agentcore_default_arn]
  }

  production_delivery_agentcore_pass_role_statement = {
    Sid      = "PassProductionAgentCoreRuntimeRole"
    Effect   = "Allow"
    Action   = ["iam:PassRole"]
    Resource = ["arn:aws:iam::920534282028:role/nova-toll-v2-agentcore-runtime"]
    Condition = {
      StringEquals = {
        "iam:PassedToService" = "bedrock-agentcore.amazonaws.com"
      }
    }
  }

  production_delivery_planner_state_statements = [
    {
      Sid      = "ListProductionPlannerState"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = [aws_s3_bucket.tfstate.arn]
      Condition = {
        StringEquals = {
          "s3:prefix" = [
            "nova-toll/terraform.tfstate",
            "nova-toll/v2/terraform.tfstate",
            "nova-toll/v2/terraform.tfstate.tflock",
          ]
        }
      }
    },
    {
      Sid      = "ReadProductionFoundationAndApplicationState"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = local.production_delivery_state_arns
    },
    {
      Sid      = "ManageProductionApplicationLock"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = [local.production_delivery_lock_arn]
    },
    {
      Sid      = "DecryptProductionStateAndLock"
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService"                   = "s3.us-east-1.amazonaws.com"
          "kms:EncryptionContext:aws:s3:arn" = concat(local.production_delivery_state_arns, [local.production_delivery_lock_arn])
        }
      }
    },
    {
      Sid      = "GenerateProductionLockDataKey"
      Effect   = "Allow"
      Action   = ["kms:GenerateDataKey"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService"                   = "s3.us-east-1.amazonaws.com"
          "kms:EncryptionContext:aws:s3:arn" = [local.production_delivery_lock_arn]
        }
      }
    },
    {
      Sid      = "PutProductionReleasePlan"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = [local.production_delivery_plan_arn]
    },
    {
      Sid      = "GenerateProductionPlanDataKey"
      Effect   = "Allow"
      Action   = ["kms:GenerateDataKey"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService" = "s3.us-east-1.amazonaws.com"
        }
        StringLike = {
          "kms:EncryptionContext:aws:s3:arn" = [local.production_delivery_plan_arn]
        }
      }
    },
    {
      Sid      = "ReadCloudflareProviderToken"
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = [local.production_delivery_cloudflare_param_arn]
    },
    {
      Sid      = "DecryptCloudflareProviderToken"
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = [local.production_delivery_cloudflare_key_arn]
      Condition = {
        StringEquals = {
          "kms:ViaService"                      = "ssm.us-east-1.amazonaws.com"
          "kms:EncryptionContext:PARAMETER_ARN" = local.production_delivery_cloudflare_param_arn
        }
      }
    },
  ]

  production_delivery_deploy_state_statements = [
    {
      Sid      = "ListProductionApplicationState"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = [aws_s3_bucket.tfstate.arn]
      Condition = {
        StringEquals = {
          "s3:prefix" = [
            "nova-toll/v2/terraform.tfstate",
            "nova-toll/v2/terraform.tfstate.tflock",
          ]
        }
      }
    },
    {
      Sid      = "ManageProductionApplicationState"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = [local.production_delivery_state_arns[1]]
    },
    {
      Sid      = "ManageProductionApplicationLock"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = [local.production_delivery_lock_arn]
    },
    {
      Sid      = "DecryptProductionApplicationStateAndLock"
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService"                   = "s3.us-east-1.amazonaws.com"
          "kms:EncryptionContext:aws:s3:arn" = [local.production_delivery_state_arns[1], local.production_delivery_lock_arn]
        }
      }
    },
    {
      Sid      = "GenerateProductionApplicationStateDataKeys"
      Effect   = "Allow"
      Action   = ["kms:GenerateDataKey"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService"                   = "s3.us-east-1.amazonaws.com"
          "kms:EncryptionContext:aws:s3:arn" = [local.production_delivery_state_arns[1], local.production_delivery_lock_arn]
        }
      }
    },
  ]

  production_delivery_deploy_release_statements = [
    {
      Sid      = "ReadVersionedReleasePlan"
      Effect   = "Allow"
      Action   = ["s3:GetObjectVersion"]
      Resource = ["${aws_s3_bucket.tfstate.arn}/plans/*"]
    },
    {
      Sid      = "DecryptVersionedReleasePlan"
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = [aws_kms_key.tfstate.arn]
      Condition = {
        StringEquals = {
          "kms:ViaService" = "s3.us-east-1.amazonaws.com"
        }
        StringLike = {
          "kms:EncryptionContext:aws:s3:arn" = ["${aws_s3_bucket.tfstate.arn}/plans/*"]
        }
      }
    },
  ]

  production_delivery_deploy_policy_documents = {
    state   = jsonencode({ Version = "2012-10-17", Statement = local.production_delivery_deploy_state_statements })
    release = jsonencode({ Version = "2012-10-17", Statement = local.production_delivery_deploy_release_statements })
    compute = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_application_policy_statements, 0, 6)
    })
    observability = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_application_policy_statements, 6, 12)
    })
    storage = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_application_policy_statements, 12, 17)
    })
    data = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_application_policy_statements, 17, 24)
    })
    runtime = jsonencode({
      Version   = "2012-10-17"
      Statement = concat(slice(local.production_delivery_application_policy_statements, 24, 28), [local.production_delivery_agentcore_default_statement, local.production_delivery_agentcore_pass_role_statement])
    })
    edge = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_application_policy_statements, 28, length(local.production_delivery_application_policy_statements))
    })
  }

  # Keep the planner's read-only discovery allowlist intact while staying
  # below IAM's 6,144-character customer-managed policy limit.
  production_delivery_planner_policy_documents = {
    state = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_planner_state_statements, 0, 5)
    })
    plan = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_planner_state_statements, 5, length(local.production_delivery_planner_state_statements))
    })
    compute = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 0, 6)
    })
    observability = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 6, 12)
    })
    storage = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 12, 17)
    })
    data = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 17, 24)
    })
    runtime = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 24, 28)
    })
    edge = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.production_delivery_discovery_statements, 28, length(local.production_delivery_discovery_statements))
    })
    endpoint = jsonencode({
      Version   = "2012-10-17"
      Statement = [local.production_delivery_agentcore_default_statement]
    })
  }
}

data "aws_iam_policy_document" "production_planner_assume" {
  count = var.environment == "production" ? 1 : 0

  statement {
    sid     = "GitHubProductionPlannerMain"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "production_deploy_assume" {
  count = var.environment == "production" ? 1 : 0

  statement {
    sid     = "GitHubProductionDeployEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production"]
    }
  }
}

data "aws_iam_policy_document" "production_deploy" {
  count = var.environment == "production" ? 1 : 0

  source_policy_documents = [jsonencode({
    Version   = "2012-10-17"
    Statement = concat(local.production_delivery_deploy_state_statements, local.production_delivery_deploy_release_statements, local.production_delivery_application_policy_statements, [local.production_delivery_agentcore_default_statement, local.production_delivery_agentcore_pass_role_statement])
  })]
}

resource "aws_iam_role" "production_planner" {
  count                = var.environment == "production" ? 1 : 0
  name                 = "nova-toll-production-planner"
  assume_role_policy   = data.aws_iam_policy_document.production_planner_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_role" "production_deploy" {
  count                = var.environment == "production" ? 1 : 0
  name                 = "nova-toll-production-deploy"
  assume_role_policy   = data.aws_iam_policy_document.production_deploy_assume[0].json
  max_session_duration = 3600
}

resource "aws_iam_policy" "production_planner" {
  for_each = var.environment == "production" ? local.production_delivery_planner_policy_documents : {}
  name     = "nova-toll-production-planner-${each.key}"
  path     = "/nova-toll/production/"
  policy   = each.value
}

resource "aws_iam_role_policy_attachment" "production_planner" {
  for_each   = var.environment == "production" ? local.production_delivery_planner_policy_documents : {}
  role       = aws_iam_role.production_planner[0].name
  policy_arn = aws_iam_policy.production_planner[each.key].arn
}

resource "aws_iam_policy" "production_deploy" {
  for_each = var.environment == "production" ? local.production_delivery_deploy_policy_documents : {}
  name     = "nova-toll-production-deploy-${each.key}"
  path     = "/nova-toll/production/"
  policy   = each.value
}

resource "aws_iam_role_policy_attachment" "production_deploy" {
  for_each   = var.environment == "production" ? local.production_delivery_deploy_policy_documents : {}
  role       = aws_iam_role.production_deploy[0].name
  policy_arn = aws_iam_policy.production_deploy[each.key].arn
}

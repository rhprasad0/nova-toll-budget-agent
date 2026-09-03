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
    "tollchat-v2-usage-publisher-dev",
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
      "tollchat-v2-usage-publisher-dev",
      "tollchat-v2-agent-usage-rollup-dev",
    ] : "arn:aws:lambda:${local.development_delivery_region}:${local.development_delivery_account_id}:function:${function_name}"
  ]
  development_delivery_lambda_resources = flatten([
    for arn in local.development_delivery_lambda_arns : [arn, "${arn}:*"]
  ])
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
      "tollchat-v2-usage-publisher-dev",
      "tollchat-v2-agent-usage-rollup-dev",
    ] : "arn:aws:events:${local.development_delivery_region}:${local.development_delivery_account_id}:rule/${rule_name}"
  ]
  development_delivery_log_group_arns = [
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/toll-v2-pricing-loader-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/toll-v2-report-publisher-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-chat-proxy-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-usage-publisher-dev",
    "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:/aws/lambda/tollchat-v2-agent-usage-rollup-dev",
  ]
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
      "tollchat-v2-agent-usage-log-coverage-dev",
      "tollchat-v2-agent-usage-rollup-errors-dev",
      "tollchat-v2-agent-usage-rollup-missing-dev",
      "tollchat-v2-agentcore-active-sessions-dev",
      "tollchat-v2-chat-proxy-errors-dev",
      "tollchat-v2-chat-proxy-failures-dev",
      "tollchat-v2-chat-proxy-latency-dev",
      "tollchat-v2-usage-publisher-errors-dev",
      "tollchat-v2-usage-publisher-failed-invocations-dev",
    ] : "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:${alarm_name}"
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
    "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:key/076e8341-894b-405c-96e9-2b037f96e2a6",
    "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:key/3bc78b60-9cbe-4abd-9744-8772c78d8379",
  ]
  development_delivery_site_bucket_arn           = "arn:aws:s3:::tollchat-site-${local.development_delivery_account_id}-dev"
  development_delivery_measurement_bucket_arn    = "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-${local.development_delivery_account_id}-dev"
  development_delivery_artifact_bucket_arn       = "arn:aws:s3:::nova-toll-agentcore-${local.development_delivery_account_id}"
  development_delivery_site_kms_alias_arn        = "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:alias/tollchat-v2-site-dev"
  development_delivery_measurement_kms_alias_arn = "arn:aws:kms:${local.development_delivery_region}:${local.development_delivery_account_id}:alias/tollchat-v2-agent-measurement-dev"
  development_delivery_athena_named_query_arns = [
    "arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:namedquery/097b778f-c9ed-4bd9-af53-1e05770e1d53",
    "arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:namedquery/6a947ac6-b2a9-45b9-a28c-1b19bfec3e1d",
  ]
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
      "lambda:GetAlias", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionEventInvokeConfig",
      "lambda:GetFunctionUrlConfig", "lambda:GetPolicy", "lambda:GetProvisionedConcurrencyConfig", "lambda:ListAliases",
      "lambda:ListProvisionedConcurrencyConfigs", "lambda:ListTags", "lambda:ListVersionsByFunction",
    ]
    resources = local.development_delivery_lambda_resources
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
    sid       = "ManageApplicationLogs"
    actions   = ["logs:DescribeMetricFilters", "logs:ListTagsForResource", "logs:PutRetentionPolicy", "logs:TagResource", "logs:UntagResource"]
    resources = local.development_delivery_log_group_arns
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
    actions   = ["s3:DeleteObject", "s3:GetBucketAcl", "s3:GetBucketLocation", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectVersion", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:ListBucketVersions", "s3:PutBucketOwnershipControls", "s3:PutBucketTagging", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration", "s3:PutLifecycleConfiguration", "s3:PutObject"]
    resources = [local.development_delivery_site_bucket_arn, "${local.development_delivery_site_bucket_arn}/*"]
  }

  statement {
    sid       = "ManageApplicationMeasurementBucket"
    actions   = ["s3:GetBucketAcl", "s3:GetBucketLocation", "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketTagging", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:ListBucketVersions"]
    resources = [local.development_delivery_measurement_bucket_arn]
  }

  statement {
    sid       = "ManageApplicationMeasurementRegistry"
    actions   = ["s3:DeleteObject", "s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectVersion", "s3:PutObject"]
    resources = ["${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson"]
  }

  statement {
    sid     = "PublishApplicationArtifacts"
    actions = ["s3:AbortMultipartUpload", "s3:DeleteObject", "s3:GetObject", "s3:GetObjectAttributes", "s3:GetObjectVersion", "s3:ListBucketMultipartUploads", "s3:ListMultipartUploadParts", "s3:PutObject"]
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
    sid       = "ReadApplicationKmsAliases"
    actions   = ["kms:DescribeKey", "kms:ListResourceTags"]
    resources = [local.development_delivery_site_kms_alias_arn, local.development_delivery_measurement_kms_alias_arn]
  }

  statement {
    sid       = "ManageApplicationSessions"
    actions   = ["dynamodb:DescribeContinuousBackups", "dynamodb:DescribeTable", "dynamodb:DescribeTimeToLive", "dynamodb:ListTagsOfResource", "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:UpdateContinuousBackups", "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive"]
    resources = ["arn:aws:dynamodb:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat-v2-anonymous-sessions-dev"]
  }

  statement {
    sid     = "ManageApplicationCatalog"
    actions = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetTags", "glue:TagResource", "glue:UntagResource", "glue:UpdateDatabase", "glue:UpdateTable"]
    resources = [
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:catalog",
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:database/tollchat_agent_reports_development",
      "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat_agent_reports_development/*",
    ]
  }

  statement {
    sid = "ManageApplicationAthenaNamedQueries"
    # Named queries are manually owned; refresh/read access is enough for CI.
    actions   = ["athena:GetNamedQuery", "athena:ListTagsForResource"]
    resources = local.development_delivery_athena_named_query_arns
  }

  statement {
    sid     = "ManageApplicationAthenaWorkGroup"
    actions = ["athena:GetWorkGroup", "athena:ListNamedQueries", "athena:TagResource", "athena:UntagResource", "athena:UpdateWorkGroup"]
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
      "arn:aws:cloudfront::aws:cache-policy/*",
      "arn:aws:cloudfront::aws:origin-request-policy/*",
    ]
  }

  statement {
    sid       = "ManageApplicationWaf"
    actions   = ["wafv2:GetLoggingConfiguration", "wafv2:GetWebACL", "wafv2:ListTagsForResource"]
    resources = ["arn:aws:wafv2:${local.development_delivery_region}:${local.development_delivery_account_id}:global/webacl/tollchat-v2-public-chat-dev/*"]
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
      Statement = slice(local.development_delivery_policy_statements, 13, 19)
    })
    storage = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 19, 24)
    })
    data = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 24, 31)
    })
    runtime = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 31, 35)
    })
    edge = jsonencode({
      Version   = "2012-10-17"
      Statement = slice(local.development_delivery_policy_statements, 35, 42)
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

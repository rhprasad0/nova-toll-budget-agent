# Account-level prerequisites for the development AgentCore trace archive.
resource "aws_cloudwatch_log_group" "development_transaction_search" {
  # AWS creates the reserved aws/spans group; import it after enabling the destination.
  for_each          = var.environment == "development" ? toset(["aws/spans", "/aws/application-signals/data"]) : toset([])
  name              = each.value
  retention_in_days = 7
}

resource "aws_cloudwatch_log_resource_policy" "development_transaction_search" {
  count       = var.environment == "development" ? 1 : 0
  policy_name = "nova-toll-v2-transaction-search-dev"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = "logs:PutLogEvents"
      Resource = [
        "arn:aws:logs:us-east-1:903859731897:log-group:aws/spans:*",
        "arn:aws:logs:us-east-1:903859731897:log-group:/aws/application-signals/data:*",
      ]
      Condition = {
        StringEquals = { "aws:SourceAccount" = "903859731897" }
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:us-east-1:903859731897:*" }
      }
    }]
  })
}

resource "aws_xray_trace_segment_destination" "development" {
  count       = var.environment == "development" ? 1 : 0
  destination = "CloudWatchLogs"
  depends_on  = [aws_cloudwatch_log_resource_policy.development_transaction_search]
}

resource "aws_iam_role_policy" "development_agentcore_trace_export" {
  count = var.environment == "development" ? 1 : 0
  name  = "nova-toll-v2-agentcore-trace-export-dev"
  role  = "nova-toll-v2-agentcore-runtime-dev"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ExportDevelopmentAgentSpans"
      Effect   = "Allow"
      Action   = "xray:PutTraceSegments"
      Resource = "*"
      Condition = {
        StringEquals = { "aws:RequestedRegion" = "us-east-1" }
      }
    }]
  })
}

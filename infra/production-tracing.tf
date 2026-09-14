# Account-level prerequisites for the production AgentCore trace archive.
resource "aws_cloudwatch_log_group" "production_transaction_search" {
  # AWS creates these groups; import them after enabling the destination.
  for_each          = var.environment == "production" ? toset(["aws/spans", "/aws/application-signals/data"]) : toset([])
  name              = each.value
  retention_in_days = 1
}

resource "aws_cloudwatch_log_resource_policy" "production_transaction_search" {
  count       = var.environment == "production" ? 1 : 0
  policy_name = "nova-toll-v2-transaction-search"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = "logs:PutLogEvents"
      Resource = [
        "arn:aws:logs:us-east-1:920534282028:log-group:aws/spans:*",
        "arn:aws:logs:us-east-1:920534282028:log-group:/aws/application-signals/data:*",
      ]
      Condition = {
        StringEquals = { "aws:SourceAccount" = "920534282028" }
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:us-east-1:920534282028:*" }
      }
    }]
  })
}

resource "aws_xray_trace_segment_destination" "production" {
  count       = var.environment == "production" ? 1 : 0
  destination = "CloudWatchLogs"
  depends_on  = [aws_cloudwatch_log_resource_policy.production_transaction_search]
}

resource "aws_iam_role_policy" "production_agentcore_trace_export" {
  count = var.environment == "production" ? 1 : 0
  name  = "nova-toll-v2-agentcore-trace-export"
  role  = "nova-toll-v2-agentcore-runtime"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ExportProductionAgentSpans"
      Effect   = "Allow"
      Action   = "xray:PutTraceSegments"
      Resource = "*"
      Condition = {
        StringEquals = { "aws:RequestedRegion" = "us-east-1" }
      }
    }]
  })
}

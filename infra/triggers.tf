# --- EventBridge tick → toll-fetcher ---------------------------------------

resource "aws_cloudwatch_event_rule" "poll_tick" {
  name                = "toll-poll-tick"
  schedule_expression = "rate(10 minutes)"
}

resource "aws_cloudwatch_event_target" "fetcher" {
  rule = aws_cloudwatch_event_rule.poll_tick.name
  arn  = aws_lambda_function.fetcher.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_fetcher" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.poll_tick.arn
}

# toll-express-fetcher shares this same rule/target list rather than its own
# schedule -- one tick, both fetchers fire together, so there's no separate
# cadence to reason about or keep in sync by hand. See docs/poller-spec.md's
# "Secondary live source" section.
resource "aws_cloudwatch_event_target" "express_fetcher" {
  rule = aws_cloudwatch_event_rule.poll_tick.name
  arn  = aws_lambda_function.express_fetcher.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_express_fetcher" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.express_fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.poll_tick.arn
}

# --- S3 raw/ ObjectCreated → toll-loader ------------------------------------

resource "aws_lambda_permission" "s3_invoke_loader" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.loader.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw.arn
}

resource "aws_s3_bucket_notification" "raw" {
  bucket = aws_s3_bucket.raw.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.loader.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
  }

  depends_on = [aws_lambda_permission.s3_invoke_loader]
}

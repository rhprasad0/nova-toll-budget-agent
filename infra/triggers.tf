# --- EventBridge tick → toll-fetcher ---------------------------------------

resource "aws_cloudwatch_event_rule" "poll_tick" {
  name = "toll-poll-tick"
  # Pinned to the wall clock rather than rate(10 minutes), which anchors to
  # whenever the rule was last created and had drifted to a steady 212s
  # (3m32s) past each 10-minute boundary. VDOT labels each interval with its
  # own 10-minute mark and calculates it exactly 10 minutes earlier
  # (docs/feed-cadence-tasks.md), so that offset was 3.5 minutes of pure
  # added staleness on every captured price.
  #
  # Firing at :00 tests whether VDOT's interval-t payload is actually ready at
  # the boundary. If it is, capture staleness drops from 13.5 to 10 minutes.
  # If it isn't, each object carries interval t-10 instead -- no data is lost
  # (the next tick picks up interval t) and `feed_cadence.py archive` reports
  # it as an interval/tick mismatch, which is the measurement. Step to
  # cron(1/10 ...), cron(2/10 ...) to find the boundary if so.
  schedule_expression = "cron(0/10 * * * ? *)"
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
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.loader.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.raw.arn
  source_account = data.aws_caller_identity.current.account_id
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

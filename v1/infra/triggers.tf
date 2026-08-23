# --- EventBridge tick → toll-fetcher ---------------------------------------

resource "aws_cloudwatch_event_rule" "poll_tick" {
  name = "toll-poll-tick"
  # Pinned to the wall clock rather than rate(10 minutes), which anchors to
  # whenever the rule was created and had drifted to a steady 212s past each
  # boundary -- 3.5 minutes of pure added staleness on every captured price.
  # Verified live: VDOT's interval-t payload is ready at the boundary, so
  # firing at :00 captures interval t, not t-10 (docs/oracle-findings.md §9).
  schedule_expression = "cron(0/10 * * * ? *)"
}

resource "aws_cloudwatch_event_target" "fetcher" {
  rule = aws_cloudwatch_event_rule.poll_tick.name
  arn  = aws_lambda_function.fetcher.arn
  # This rule now carries I-95 only; I-66 has its own, faster rule below.
  input = jsonencode({ feeds = ["i95"] })
}

resource "aws_lambda_permission" "eventbridge_invoke_fetcher" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.poll_tick.arn
}

# --- I-66 tick → toll-fetcher ----------------------------------------------

# I-66 publishes every 6 minutes, not 10 (measured in prod). The shared
# 10-minute tick captured whichever snapshot was current and never fetched the
# rest -- roughly 6 of every 10 intervals stored. 0/6 divides the hour evenly,
# so it stays phase-stable across hour boundaries the way rate() would not.
resource "aws_cloudwatch_event_rule" "poll_tick_i66" {
  name                = "toll-poll-tick-i66"
  schedule_expression = "cron(0/6 * * * ? *)"
}

resource "aws_cloudwatch_event_target" "fetcher_i66" {
  rule  = aws_cloudwatch_event_rule.poll_tick_i66.name
  arn   = aws_lambda_function.fetcher.arn
  input = jsonencode({ feeds = ["i66"] })
}

resource "aws_lambda_permission" "eventbridge_invoke_fetcher_i66" {
  statement_id  = "AllowEventBridgeInvokeI66"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.poll_tick_i66.arn
}

resource "aws_s3_bucket_notification" "raw" {
  bucket      = aws_s3_bucket.raw.id
  eventbridge = true
}

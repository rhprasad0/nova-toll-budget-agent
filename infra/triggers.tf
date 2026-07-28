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

# I-66 publishes a new interval every 6 minutes, not 10 (measured in prod --
# 345 six-minute gaps over two days, with a real 6-minute interval_start_at
# window and a variable 1:52-3:47 calculated_at lag, unlike I-95's fixed
# 10:00). Polling it on the 10-minute tick captured whichever snapshot was
# current and never saw the rest -- roughly 6 of every 10 intervals stored,
# with no raw record to backfill from since the fetcher never fetched them.
#
# 0/6 divides the hour evenly (:00 :06 :12 … :54), so this stays phase-stable
# across hour boundaries the way a rate() expression would not. Firing on the
# boundary may return interval t-6 if VDOT hasn't published yet; that costs
# nothing, since the next tick picks it up and every interval is still
# captured exactly once.
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

# toll-express-fetcher stays on the 10-minute poll_tick rule, deliberately:
# Transurban's payload changes every 10 minutes (measured -- see
# docs/poller-spec.md's "Secondary live source"), and sharing I-95's tick is
# what makes the two feeds' captures directly alignable, which is how the
# 10-minute republish relationship in docs/oracle-findings.md section 9 was
# measured. It takes no input, so it is unaffected by the feed selection above.
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

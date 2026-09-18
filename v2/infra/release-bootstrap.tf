# Only the separately reviewed bootstrap gate permits these state transitions.
import {
  to = aws_bedrockagentcore_agent_runtime.tollchat["green"]
  id = var.release_slots["green"].runtime_id
}

removed {
  from = aws_s3_object.agentcore
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_object.tollchat_proxy
  lifecycle { destroy = false }
}

moved {
  from = aws_bedrockagentcore_agent_runtime.tollchat
  to   = aws_bedrockagentcore_agent_runtime.tollchat["blue"]
}

moved {
  from = aws_bedrockagentcore_agent_runtime_endpoint.tollchat
  to   = aws_bedrockagentcore_agent_runtime_endpoint.tollchat["blue"]
}

moved {
  from = aws_cloudwatch_log_group.tollchat_proxy
  to   = aws_cloudwatch_log_group.tollchat_proxy["blue"]
}

moved {
  from = aws_lambda_function.tollchat_proxy
  to   = aws_lambda_function.tollchat_proxy["blue"]
}

moved {
  from = aws_lambda_alias.tollchat_live
  to   = aws_lambda_alias.tollchat_live["blue"]
}

moved {
  from = aws_lambda_permission.tollchat_api
  to   = aws_lambda_permission.tollchat_api["blue"]
}

moved {
  from = aws_bedrockagentcore_resource_policy.tollchat["runtime"]
  to   = aws_bedrockagentcore_resource_policy.tollchat["blue-runtime"]
}

moved {
  from = aws_bedrockagentcore_resource_policy.tollchat["endpoint"]
  to   = aws_bedrockagentcore_resource_policy.tollchat["blue-endpoint"]
}

moved {
  from = aws_lambda_function_url.public_chat
  to   = aws_lambda_function_url.public_chat["blue"]
}

moved {
  from = aws_lambda_permission.public_chat_url
  to   = aws_lambda_permission.public_chat_url["blue"]
}

moved {
  from = aws_lambda_permission.public_chat_invoke
  to   = aws_lambda_permission.public_chat_invoke["blue"]
}

removed {
  from = aws_s3_object.index
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_object.chat
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_object.faq
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_object.privacy
  lifecycle { destroy = false }
}

removed {
  from = aws_s3_object.site_assets
  lifecycle { destroy = false }
}

moved {
  from = aws_cloudwatch_log_metric_filter.proxy_failure
  to   = aws_cloudwatch_log_metric_filter.proxy_failure["blue"]
}

moved {
  from = aws_cloudwatch_metric_alarm.tollchat_proxy_errors
  to   = aws_cloudwatch_metric_alarm.tollchat_proxy_errors["blue"]
}

moved {
  from = aws_cloudwatch_metric_alarm.tollchat_proxy_failures
  to   = aws_cloudwatch_metric_alarm.tollchat_proxy_failures["blue"]
}

moved {
  from = aws_cloudwatch_metric_alarm.tollchat_proxy_latency
  to   = aws_cloudwatch_metric_alarm.tollchat_proxy_latency["blue"]
}

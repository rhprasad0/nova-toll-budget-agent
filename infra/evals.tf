resource "aws_bedrock_inference_profile" "nightly_eval" {
  name        = "nova-toll-nightly-eval"
  description = "Cost attribution for nightly simulated-user evaluations"

  model_source {
    copy_from = "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }

  tags = {
    purpose = "nightly-eval"
  }
}

resource "aws_ssm_parameter" "nightly_eval_bedrock_profile_arn" {
  name  = "/nova-toll/nightly_eval_bedrock_profile_arn"
  type  = "String"
  value = aws_bedrock_inference_profile.nightly_eval.arn
}

# Inputs for a credential-free plan of the development root. Read by
# v2/scripts/infrastructure_plan.py, which runs it on a copy without import blocks.
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
mock_provider "cloudflare" {}

variables {
  loader_package_path              = "build/loader.zip"
  publisher_package_path           = "build/publisher.zip"
  environment                      = "development"
  enable_public_dns                = false
  enable_development_custom_domain = true
  release_slots = {
    blue = {
      release_id             = "blue-release"
      runtime_id             = "nova_toll_v2_development-Blue000000"
      runtime_key            = "releases/blue-release/agentcore.zip"
      runtime_object_version = "runtime-version-blue"
      runtime_sha256         = "0000000000000000000000000000000000000000000000000000000000000000"
      proxy_key              = "releases/blue-release/chat-proxy.zip"
      proxy_object_version   = "proxy-version-blue"
      proxy_sha256           = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
      runtime_environment = {
        DB_HOST                              = "db.example"
        DB_PORT                              = "5432"
        DB_NAME                              = "nova_toll_development"
        DB_USER                              = "tollchat_agent_development"
        PRICING_DB_USER                      = "pricing_caller_development"
        DB_CA_BUNDLE_PATH                    = "/var/task/rds-ca-bundle.pem"
        TOLLCHAT_TELEMETRY_GUARDRAIL_ID      = "guardrail0"
        TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION = "1"
        UNIFIED_TRACES_DESTINATION_ENABLED   = "true"
      }
      proxy_environment = {
        AGENTCORE_VPCE_URL = "https://vpce-agentcore.example"
        SESSION_TABLE_NAME = "tollchat-v2-anonymous-sessions-dev"
        PUBLIC_ORIGINS     = "https://dev.tollchat.ai"
      }
      asset_prefix = "/releases/blue-release"
    }
    green = {
      release_id             = "green-release"
      runtime_id             = "nova_toll_v2_development_green-Green00000"
      runtime_key            = "releases/green-release/agentcore.zip"
      runtime_object_version = "runtime-version-green"
      runtime_sha256         = "1111111111111111111111111111111111111111111111111111111111111111"
      proxy_key              = "releases/green-release/chat-proxy.zip"
      proxy_object_version   = "proxy-version-green"
      proxy_sha256           = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
      runtime_environment = {
        DB_HOST                              = "db.example"
        DB_PORT                              = "5432"
        DB_NAME                              = "nova_toll_development"
        DB_USER                              = "tollchat_agent_development"
        PRICING_DB_USER                      = "pricing_caller_development"
        DB_CA_BUNDLE_PATH                    = "/var/task/rds-ca-bundle.pem"
        TOLLCHAT_TELEMETRY_GUARDRAIL_ID      = "guardrail0"
        TOLLCHAT_TELEMETRY_GUARDRAIL_VERSION = "1"
        UNIFIED_TRACES_DESTINATION_ENABLED   = "true"
      }
      proxy_environment = {
        AGENTCORE_VPCE_URL = "https://vpce-agentcore.example"
        SESSION_TABLE_NAME = "tollchat-v2-anonymous-sessions-dev"
        PUBLIC_ORIGINS     = "https://dev.tollchat.ai"
      }
      asset_prefix = "/releases/green-release"
    }
  }
  foundation = {
    vpc_id                                 = "vpc-0"
    vpc_cidr_block                         = "10.0.0.0/16"
    private_subnet_ids                     = { a = "subnet-a", c = "subnet-c" }
    rds_security_group_id                  = "sg-rds"
    agentcore_endpoint_security_group_id   = "sg-agentcore"
    eventbridge_endpoint_security_group_id = "sg-eventbridge"
    agentcore_vpc_endpoint_id              = "vpce-agentcore"
    agentcore_vpc_endpoint_dns_name        = "vpce-agentcore.example"
    tollchat_api_vpc_endpoint_id           = "vpce-api"
    raw_bucket_name                        = "raw-bucket"
    raw_kms_key_arn                        = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
    agentcore_artifacts_bucket_name        = "artifacts-bucket"
    db_instance                            = { identifier = "db", resource_id = "db-0", address = "db.example", port = 5432 }
    alerts_topic_arn                       = "arn:aws:sns:us-east-1:903859731897:nova-toll-alerts"
    telemetry_guardrail                    = { id = "guardrail0", arn = "arn:aws:bedrock:us-east-1:903859731897:guardrail/guardrail0", version = "1" }
  }
}

override_data {
  target          = data.aws_caller_identity.current
  override_during = plan
  values          = { account_id = "903859731897" }
}
override_data {
  target          = data.aws_region.current
  override_during = plan
  values          = { region = "us-east-1", name = "us-east-1" }
}
override_data {
  target          = data.aws_prefix_list.s3
  override_during = plan
  values          = { id = "pl-s3" }
}
override_data {
  target          = data.aws_prefix_list.dynamodb
  override_during = plan
  values          = { id = "pl-dynamodb" }
}
override_data {
  target          = data.aws_cloudfront_cache_policy.caching_disabled
  override_during = plan
  values          = { id = "cache-policy" }
}
override_data {
  target          = data.aws_cloudfront_origin_request_policy.all_except_host
  override_during = plan
  values          = { id = "origin-policy" }
}
override_data {
  target          = data.aws_ssm_parameter.candidate_header
  override_during = plan
  values          = { value = "candidate-header" }
}


run "development" {
  command = plan
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${data.aws_region.current.region}.s3"
}

data "aws_prefix_list" "dynamodb" {
  name = "com.amazonaws.${data.aws_region.current.region}.dynamodb"
}

data "aws_subnet" "tollchat_private_a" {
  filter {
    name   = "tag:Name"
    values = ["nova-toll-private-a"]
  }
}

data "aws_subnet" "tollchat_private_c" {
  filter {
    name   = "tag:Name"
    values = ["nova-toll-private-c"]
  }
}

data "aws_vpc_endpoint" "agentcore" {
  vpc_id       = data.aws_vpc.default.id
  service_name = "com.amazonaws.${data.aws_region.current.region}.bedrock-agentcore"
}

data "aws_vpc_endpoint" "tollchat_api" {
  vpc_id       = data.aws_vpc.default.id
  service_name = "com.amazonaws.${data.aws_region.current.region}.execute-api"
}

data "aws_security_group" "agentcore_endpoint" {
  name   = "nova-toll-agentcore-endpoint"
  vpc_id = data.aws_vpc.default.id
}

data "aws_security_group" "eventbridge_endpoint" {
  name   = "nova-toll-eventbridge-endpoint"
  vpc_id = data.aws_vpc.default.id
}

data "aws_s3_bucket" "raw" {
  bucket = "nova-toll-raw-920534282028"
}

data "aws_s3_bucket" "agentcore_artifacts" {
  bucket = "nova-toll-agentcore-920534282028"
}

data "aws_kms_alias" "raw" {
  name = "alias/nova-toll-raw"
}

data "aws_db_instance" "main" {
  db_instance_identifier = "nova-toll-db"
}

data "aws_security_group" "rds" {
  name   = "nova-toll-rds"
  vpc_id = data.aws_vpc.default.id
}

data "aws_sns_topic" "alerts" {
  name = "nova-toll-alerts"
}

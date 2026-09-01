output "foundation" {
  description = "Non-secret application inputs from this account-local foundation."
  sensitive   = false
  value = {
    vpc_id                                 = data.aws_vpc.default.id
    vpc_cidr_block                         = data.aws_vpc.default.cidr_block
    private_subnet_ids                     = { a = aws_subnet.tollchat_private_a.id, c = aws_subnet.tollchat_private_c.id }
    rds_security_group_id                  = aws_security_group.rds.id
    agentcore_endpoint_security_group_id   = aws_security_group.agentcore_endpoint.id
    eventbridge_endpoint_security_group_id = aws_security_group.eventbridge_endpoint.id
    agentcore_vpc_endpoint_id              = aws_vpc_endpoint.agentcore.id
    agentcore_vpc_endpoint_dns_name        = aws_vpc_endpoint.agentcore.dns_entry[0].dns_name
    tollchat_api_vpc_endpoint_id           = aws_vpc_endpoint.tollchat_api.id
    raw_bucket_name                        = aws_s3_bucket.raw.bucket
    raw_kms_key_arn                        = aws_kms_key.raw.arn
    agentcore_artifacts_bucket_name        = aws_s3_bucket.agentcore_artifacts.bucket
    db_instance = {
      identifier  = aws_db_instance.main.identifier
      resource_id = aws_db_instance.main.resource_id
      address     = aws_db_instance.main.address
      port        = aws_db_instance.main.port
    }
    alerts_topic_arn = aws_sns_topic.alerts.arn
  }
}

variable "loader_package_path" {
  description = "Reviewed v2 loader zip. Empty uses a validation-only placeholder."
  type        = string
  default     = ""
}

variable "publisher_package_path" {
  description = "Reviewed v2 report publisher zip. Empty uses a validation-only placeholder."
  type        = string
  default     = ""
}

variable "agentcore_package_path" {
  description = "Reviewed v2 AgentCore runtime zip. Empty uses a validation-only placeholder."
  type        = string
  default     = ""
}

variable "chat_proxy_package_path" {
  description = "Reviewed v2 private chat proxy zip. Empty uses a validation-only placeholder."
  type        = string
  default     = ""
}

variable "foundation" {
  description = "Reviewed, non-secret inputs emitted by the account-local foundation root."
  type = object({
    vpc_id                                 = string
    vpc_cidr_block                         = string
    private_subnet_ids                     = object({ a = string, c = string })
    rds_security_group_id                  = string
    agentcore_endpoint_security_group_id   = string
    eventbridge_endpoint_security_group_id = string
    agentcore_vpc_endpoint_id              = string
    agentcore_vpc_endpoint_dns_name        = string
    tollchat_api_vpc_endpoint_id           = string
    raw_bucket_name                        = string
    raw_kms_key_arn                        = string
    agentcore_artifacts_bucket_name        = string
    db_instance = object({
      identifier  = string
      resource_id = string
      address     = string
      port        = number
    })
    alerts_topic_arn = string
  })
}

variable "environment" {
  description = "Application environment. Production retains the deployed v2 identities."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "production"], var.environment)
    error_message = "environment must be development or production."
  }
}

variable "enable_public_dns" {
  description = "Whether to publish the public Cloudflare CNAME for this environment."
  type        = bool
  default     = true
}

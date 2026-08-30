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

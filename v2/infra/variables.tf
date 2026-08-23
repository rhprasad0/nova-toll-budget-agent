variable "loader_package_path" {
  description = "Reviewed v2 loader zip. Empty uses a validation-only placeholder."
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

variable "tailscale_authkey_param_name" {
  description = "SSM parameter name (SecureString) holding the Tailscale subnet-router auth key. Value is set out-of-band via CLI, never through Terraform."
  type        = string
  default     = "/nova-toll/tailscale-authkey"
}

variable "i95_token_param_name" {
  description = "SSM parameter name (SecureString) holding the I-95 feed token. Value is set out-of-band via CLI, never through Terraform."
  type        = string
  default     = "/nova-toll/i95-token"
}

variable "i66_token_param_name" {
  description = "SSM parameter name (SecureString) holding the I-66 feed token. Value is set out-of-band via CLI, never through Terraform."
  type        = string
  default     = "/nova-toll/i66-token"
}

variable "fetcher_package_path" {
  description = "Path to the toll-fetcher deployment zip. Empty falls back to the placeholder stub, which is what lets the credential-free `fmt-validate` CI job run `terraform validate` without building zips first (filebase64sha256 on a missing file is a hard error). Every real plan/apply passes the built artifact."
  type        = string
  default     = ""
}

variable "loader_package_path" {
  description = "Path to the toll-loader deployment zip. Empty falls back to the placeholder stub -- see fetcher_package_path for why that fallback exists."
  type        = string
  default     = ""
}

variable "agentcore_package_path" {
  description = "Path to the ARM64 AgentCore deployment zip. Empty uses the validation-only placeholder."
  type        = string
  default     = ""
}

variable "chat_proxy_package_path" {
  description = "Path to the chat proxy Lambda zip. Empty uses the validation-only placeholder."
  type        = string
  default     = ""
}

variable "enable_public_chat" {
  description = "Expose /api/* through CloudFront and WAF. Keep false until the public launch gate is approved."
  type        = bool
  default     = false
}

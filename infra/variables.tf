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
  description = "Path to the toll-fetcher deployment zip. Every real plan/apply passes the reviewed artifact."
  type        = string
  default     = ""
}

variable "budget_notification_email" {
  description = "Existing AWS Budget email recipient supplied only at runtime."
  type        = string
  sensitive   = true
}

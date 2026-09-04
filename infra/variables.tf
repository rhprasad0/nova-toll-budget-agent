variable "environment" {
  description = "Foundation environment boundary. Production keeps the existing router route behavior."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["development", "production"], var.environment)
    error_message = "environment must be development or production."
  }
}

variable "tailscale_advertise_routes" {
  description = "Whether the router may advertise subnet and exit-node routes. Development must leave this disabled until its VPC and ACL are approved."
  type        = bool
  default     = true
}

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

variable "development_final_snapshot_identifier" {
  description = "Unique final snapshot name supplied only for the reviewed development RDS replacement."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.development_final_snapshot_identifier == null ? true : (
      length(var.development_final_snapshot_identifier) <= 255 &&
      can(regex("^[A-Za-z]([A-Za-z0-9-]*[A-Za-z0-9])?$", var.development_final_snapshot_identifier)) &&
      !strcontains(var.development_final_snapshot_identifier, "--")
    )
    error_message = "development_final_snapshot_identifier must be 1-255 letters, digits, or hyphens; start with a letter; and have no trailing or consecutive hyphen."
  }
}

variable "budget_notification_email" {
  description = "Existing AWS Budget email recipient supplied only at runtime."
  type        = string
  sensitive   = true
}

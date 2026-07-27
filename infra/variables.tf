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

variable "cloudflare_api_token_param_name" {
  description = "SSM parameter name (SecureString) holding the Cloudflare API token used for Terraform operations. Value is set out-of-band via CLI, never through Terraform."
  type        = string
  default     = "/nova-toll/cloudflare-api-token"
}

variable "fetcher_package_path" {
  description = "Path to the toll-fetcher deployment zip. Defaults to a placeholder stub so `plan` works before WP2 ships real code; WP4 overrides with the built artifact."
  type        = string
  default     = ""
}

variable "loader_package_path" {
  description = "Path to the toll-loader deployment zip. Defaults to a placeholder stub so `plan` works before WP3 ships real code; WP4 overrides with the built artifact."
  type        = string
  default     = ""
}

variable "fetcher_handler" {
  description = "Lambda handler entrypoint for toll-fetcher."
  type        = string
  default     = "lambda_function.lambda_handler"
}

variable "loader_handler" {
  description = "Lambda handler entrypoint for toll-loader."
  type        = string
  default     = "lambda_function.lambda_handler"
}

variable "express_fetcher_package_path" {
  description = "Path to the toll-express-fetcher deployment zip. Defaults to a placeholder stub so `plan` works before real code ships; overridden with the built artifact."
  type        = string
  default     = ""
}

variable "express_fetcher_handler" {
  description = "Lambda handler entrypoint for toll-express-fetcher."
  type        = string
  default     = "lambda_function.lambda_handler"
}

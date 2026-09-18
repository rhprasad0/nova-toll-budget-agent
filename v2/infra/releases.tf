# Supplied from the protected release record, never reconstructed from latest code.
variable "release_slots" {
  description = "Exactly two retained application releases, with immutable S3 versions and frozen non-secret configuration."
  type = map(object({
    release_id             = string
    runtime_id             = string
    runtime_key            = string
    runtime_object_version = string
    runtime_sha256         = string
    proxy_key              = string
    proxy_object_version   = string
    proxy_sha256           = string
    runtime_environment    = map(string)
    proxy_environment      = map(string)
    asset_prefix           = string
  }))
  validation {
    condition = toset(keys(var.release_slots)) == toset(["blue", "green"]) && alltrue([
      for slot in values(var.release_slots) :
      can(regex("^[a-zA-Z0-9_-]{1,128}$", slot.release_id)) &&
      slot.asset_prefix == "/releases/${slot.release_id}" &&
      can(regex("^[a-f0-9]{64}$", slot.runtime_sha256)) &&
      can(regex("^[A-Za-z0-9+/]{43}=$", slot.proxy_sha256)) &&
      slot.runtime_object_version != "" && slot.runtime_object_version != "null" &&
      slot.proxy_object_version != "" && slot.proxy_object_version != "null"
    ])
    error_message = "Two complete, immutable blue/green descriptors are required."
  }
  validation {
    condition = alltrue([
      for name, slot in var.release_slots : can(regex(
        "^nova_toll_v2${var.environment == "production" ? "" : "_development"}${name == "green" ? "_green" : ""}-[A-Za-z0-9]+$",
        slot.runtime_id,
      ))
    ])
    error_message = "Runtime identities must be the exact account-local blue and green names, without wildcards."
  }
}

variable "active_slot" {
  type    = string
  default = "blue"
  validation {
    condition     = contains(["blue", "green"], var.active_slot)
    error_message = "active_slot must be blue or green."
  }
}

locals {
  inactive_slot = var.active_slot == "blue" ? "green" : "blue"
  slot_suffix   = { blue = local.suffix, green = "${local.suffix}-green" }
  slot_runtime_arns = {
    for name, slot in var.release_slots : name => "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:runtime/${slot.runtime_id}"
  }
  runtime_logs = merge(
    { for endpoint in ["DEFAULT", "preview"] : endpoint => { slot = "blue", endpoint = endpoint } },
    { for endpoint in ["DEFAULT", "preview"] : "green-${endpoint}" => { slot = "green", endpoint = endpoint } },
  )
  private_proxy_invoke_arn = replace(
    aws_lambda_function.tollchat_proxy[var.active_slot].response_streaming_invoke_arn,
    aws_lambda_function.tollchat_proxy[var.active_slot].arn,
    aws_lambda_alias.tollchat_live[var.active_slot].arn,
  )
}

output "release_state" {
  description = "Non-secret retained descriptors and the actual published identities."
  value = {
    active = var.active_slot
    slots = {
      for name, slot in var.release_slots : name => merge(slot, {
        runtime_arn     = aws_bedrockagentcore_agent_runtime.tollchat[name].agent_runtime_arn
        runtime_version = aws_bedrockagentcore_agent_runtime_endpoint.tollchat[name].agent_runtime_version
        endpoint        = aws_bedrockagentcore_agent_runtime_endpoint.tollchat[name].name
        proxy_arn       = aws_lambda_function.tollchat_proxy[name].arn
        proxy_version   = aws_lambda_alias.tollchat_live[name].function_version
        proxy_url       = aws_lambda_function_url.public_chat[name].function_url
      })
    }
  }
}

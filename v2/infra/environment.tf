locals {
  is_production  = var.environment == "production"
  suffix         = local.is_production ? "" : "-dev"
  raw_bucket_arn = "arn:aws:s3:::${var.foundation.raw_bucket_name}"
  database_name  = local.is_production ? "nova_toll" : "nova_toll_development"
  database_roles = local.is_production ? {
    pricing_caller = "pricing_caller"
    agent          = "tollchat_agent"
    loader         = "pricing_loader_writer"
    publisher      = "report_publisher"
    reader         = "pricing_reader"
    } : {
    pricing_caller = "pricing_caller_development"
    agent          = "tollchat_agent_development"
    loader         = "pricing_loader_writer_development"
    publisher      = "report_publisher_development"
    reader         = "pricing_reader_development"
  }
  domains            = local.is_production ? ["tollchat.ai", "www.tollchat.ai"] : ["dev.tollchat.ai"]
  log_retention_days = local.is_production ? 30 : 7
  alarm_actions      = local.is_production ? [var.foundation.alerts_topic_arn] : []
  rate_limit         = local.is_production ? 20 : 10
  public_site_url    = local.is_production ? "https://${local.domains[0]}" : (var.public_preview_hostname == "" ? "" : "https://${var.public_preview_hostname}")
}

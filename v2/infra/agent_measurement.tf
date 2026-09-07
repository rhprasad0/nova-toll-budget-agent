locals {
  agent_measurement_database = "tollchat_agent_reports${local.is_production ? "" : "_development"}"
  agent_measurement_bucket   = "aws-waf-logs-tollchat-agent-reports-${data.aws_caller_identity.current.account_id}${local.suffix}"
  agent_measurement_acl      = "tollchat-v2-public-chat${local.suffix}"
}

# Retained historical bucket/key state remains managed; slice 4 owns retirement.
resource "aws_s3_bucket" "agent_measurement" {
  bucket = local.agent_measurement_bucket
}

resource "aws_s3_bucket_public_access_block" "agent_measurement" {
  bucket                  = aws_s3_bucket.agent_measurement.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "agent_measurement_kms" {
  statement {
    sid       = "EnableAccountIamPolicies"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

}

resource "aws_kms_key" "agent_measurement" {
  description             = "TollChat agent-route measurement data"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.agent_measurement_kms.json
}

resource "aws_kms_alias" "agent_measurement" {
  name          = "alias/tollchat-v2-agent-measurement${local.suffix}"
  target_key_id = aws_kms_key.agent_measurement.key_id
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.agent_measurement.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id

  rule {
    id     = "expire-raw-waf-logs"
    status = "Enabled"
    filter { prefix = "AWSLogs/" }
    expiration { days = 7 }
  }

  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter { prefix = "athena-results/" }
    expiration { days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

data "aws_iam_policy_document" "agent_measurement_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.agent_measurement.arn,
      "${aws_s3_bucket.agent_measurement.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

}

resource "aws_s3_bucket_policy" "agent_measurement" {
  bucket = aws_s3_bucket.agent_measurement.id
  policy = data.aws_iam_policy_document.agent_measurement_bucket.json
}

resource "aws_s3_object" "agent_registry" {
  # Inert retained historical bytes; the removed rollup no longer consumes it.
  bucket        = aws_s3_bucket.agent_measurement.id
  key           = "registry/agent_registry.ndjson"
  source        = "${path.module}/../analytics/agent_registry.ndjson"
  source_hash   = filebase64sha256("${path.module}/../analytics/agent_registry.ndjson")
  content_type  = "application/x-ndjson"
  cache_control = "no-store"

  lifecycle {
    ignore_changes = [source, source_hash]
  }

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.agent_measurement]
}

# Historical catalog/table metadata remains managed without an active consumer.
resource "aws_glue_catalog_database" "agent_reports" {
  name = local.agent_measurement_database
}

resource "aws_glue_catalog_table" "waf_logs" {
  name          = "agent_report_waf_logs"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL                     = "TRUE"
    "projection.enabled"         = "true"
    "projection.log_date.type"   = "date"
    "projection.log_date.range"  = "2026/08/25,NOW"
    "projection.log_date.format" = "yyyy/MM/dd"
    "projection.log_hour.type"   = "integer"
    "projection.log_hour.range"  = "0,23"
    "projection.log_hour.digits" = "2"
    # CloudFront-scoped WAF logs use this literal scope token, not the region name.
    "storage.location.template" = "s3://${aws_s3_bucket.agent_measurement.id}/AWSLogs/${data.aws_caller_identity.current.account_id}/WAFLogs/cloudfront/${local.agent_measurement_acl}/$${log_date}/$${log_hour}/"
  }

  dynamic "partition_keys" {
    for_each = toset(["log_date", "log_hour"])
    content {
      name = partition_keys.value
      type = "string"
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/AWSLogs/${data.aws_caller_identity.current.account_id}/WAFLogs/cloudfront/${local.agent_measurement_acl}/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    dynamic "columns" {
      for_each = {
        timestamp           = "bigint"
        formatversion       = "int"
        webaclid            = "string"
        terminatingruleid   = "string"
        terminatingruletype = "string"
        action              = "string"
        labels              = "array<struct<name:string>>"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
    columns {
      name = "httprequest"
      type = "struct<clientip:string,country:string,headers:array<struct<name:string,value:string>>,uri:string,args:string,httpversion:string,httpmethod:string,requestid:string,fragment:string,scheme:string,host:string>"
    }

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
  }
}

resource "aws_glue_catalog_table" "agent_registry" {
  name          = "agent_registry"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE" }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/registry/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    dynamic "columns" {
      for_each = toset(["vendor_family", "user_agent_token", "agent_mode", "documentation_url"])
      content {
        name = columns.value
        type = "string"
      }
    }
    ser_de_info { serialization_library = "org.openx.data.jsonserde.JsonSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_generations" {
  name          = "agent_report_generations"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE" }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/generations/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    dynamic "columns" {
      for_each = {
        schema_version = "int"
        facility       = "string"
        generation_id  = "string"
        published_at   = "string"
        result_sha256  = "string"
        route_keys     = "array<string>"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
    ser_de_info { serialization_library = "org.openx.data.jsonserde.JsonSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_rollups" {
  name          = "agent_report_rollups"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE", classification = "parquet" }

  dynamic "partition_keys" {
    for_each = { report_date = "date", run_id = "string" }
    content {
      name = partition_keys.key
      type = partition_keys.value
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/rollups/usage/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    dynamic "columns" {
      for_each = [
        { name = "first_requested_at", type = "timestamp" },
        { name = "last_requested_at", type = "timestamp" },
        { name = "request_count", type = "bigint" },
        { name = "published_generation_age_seconds", type = "bigint" },
        { name = "origin_slug", type = "string" },
        { name = "destination_slug", type = "string" },
        { name = "representation", type = "string" },
        { name = "traffic_class", type = "string" },
        { name = "vendor_family", type = "string" },
        { name = "identity_confidence", type = "string" },
        { name = "aws_bot_name", type = "string" },
        { name = "aws_organization", type = "string" },
        { name = "aws_category", type = "string" },
        { name = "waf_action", type = "string" },
        { name = "generation_id", type = "string" },
        { name = "published_at", type = "string" },
      ]
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
  }
}

resource "aws_glue_catalog_table" "agent_report_rollup_completions" {
  name          = "agent_report_rollup_completions"
  database_name = aws_glue_catalog_database.agent_reports.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { EXTERNAL = "TRUE", classification = "parquet" }

  dynamic "partition_keys" {
    for_each = { report_date = "date", run_id = "string" }
    content {
      name = partition_keys.key
      type = partition_keys.value
    }
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.agent_measurement.id}/rollups/completions/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    columns {
      name = "completed_at"
      type = "timestamp"
    }
    ser_de_info { serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" }
  }
}

resource "aws_athena_workgroup" "agent_reports" {
  name = "tollchat-agent-reports${local.suffix}"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 1073741824

    result_configuration {
      output_location       = "s3://${aws_s3_bucket.agent_measurement.id}/athena-results/"
      expected_bucket_owner = data.aws_caller_identity.current.account_id
      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.agent_measurement.arn
      }
    }
  }
}

# Historical rollup execution logs remain managed for read-only retention; the
# rollup Lambda, schedule, and alarms are retired in this source cleanup.
resource "aws_cloudwatch_log_group" "agent_usage_rollup" {
  name              = "/aws/lambda/tollchat-v2-agent-usage-rollup${local.suffix}"
  retention_in_days = local.log_retention_days
}

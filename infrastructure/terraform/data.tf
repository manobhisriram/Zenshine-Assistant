# ── Redis (sessions + distributed rate limits) ────────────────────────────
resource "random_password" "redis_auth" {
  length  = 40
  special = false
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = local.name
  description                = "${local.name} sessions and rate limits"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  port                       = 6379
  num_cache_clusters         = 1 + var.redis_replicas
  automatic_failover_enabled = var.redis_replicas > 0
  multi_az_enabled           = var.redis_replicas > 0
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result
  parameter_group_name       = "default.redis7"
  snapshot_retention_limit   = local.is_prod ? 3 : 0
  maintenance_window         = "sun:21:00-sun:22:00"
  snapshot_window            = "20:00-21:00"
  auto_minor_version_upgrade = true
  apply_immediately          = !local.is_prod
}

# ── Leads (callback requests) ─────────────────────────────────────────────
resource "aws_dynamodb_table" "leads" {
  name         = "${local.name}-leads"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant"
  range_key    = "lead_id"

  attribute {
    name = "tenant"
    type = "S"
  }
  attribute {
    name = "lead_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled = true
  }
  deletion_protection_enabled = var.deletion_protection
}

resource "aws_sns_topic" "leads" {
  name              = "${local.name}-leads"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "leads_email" {
  for_each  = toset(var.lead_notification_emails)
  topic_arn = aws_sns_topic.leads.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

data "aws_iam_policy_document" "alarms_topic" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_topic.json
}

resource "aws_sns_topic_subscription" "alarm_email" {
  for_each  = toset(var.alarm_emails)
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = each.value
}

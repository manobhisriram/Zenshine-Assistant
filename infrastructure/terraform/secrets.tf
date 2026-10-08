# Secret *containers*. Real API keys are set out-of-band so they never enter Terraform state:
#   aws secretsmanager put-secret-value --secret-id <name> --secret-string 'sk-ant-...'

resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "${local.name}/anthropic-api-key"
  description             = "Anthropic API key"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "anthropic" {
  secret_id     = aws_secretsmanager_secret.anthropic.id
  secret_string = "REPLACE_ME"
  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "pinecone" {
  name                    = "${local.name}/pinecone-api-key"
  description             = "Pinecone API key"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "pinecone" {
  secret_id     = aws_secretsmanager_secret.pinecone.id
  secret_string = "REPLACE_ME"
  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Generated secrets (these do live in state, so keep the state bucket private and encrypted).
resource "random_password" "admin_key" {
  length  = 48
  special = false
}

resource "random_password" "metrics_token" {
  length  = 40
  special = false
}

resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "admin" {
  name                    = "${local.name}/admin-api-key"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "admin" {
  secret_id     = aws_secretsmanager_secret.admin.id
  secret_string = random_password.admin_key.result
}

resource "aws_secretsmanager_secret" "metrics" {
  name                    = "${local.name}/metrics-token"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "metrics" {
  secret_id     = aws_secretsmanager_secret.metrics.id
  secret_string = random_password.metrics_token.result
}

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${local.name}/redis-url"
  recovery_window_in_days = local.is_prod ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "rediss://:${random_password.redis_auth.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
}

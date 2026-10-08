data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.project}-${var.environment}${var.name_suffix}"
  azs  = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  is_prod         = var.environment == "prod"
  has_domain      = var.domain_name != ""
  alb_tls         = var.alb_certificate_arn != "" && var.alb_domain_name != ""
  public_url      = local.has_domain ? "https://${var.domain_name}" : "https://${aws_cloudfront_distribution.main.domain_name}"
  cors_origins    = join(",", distinct(concat([local.public_url], var.cors_origins)))
  container_port  = 8000
  api_log_group   = "/ecs/${local.name}/api"
  emf_namespace   = "ZenShineAssistant"
  frontend_bucket = "${local.name}-web-${data.aws_caller_identity.current.account_id}-${var.region}"
}

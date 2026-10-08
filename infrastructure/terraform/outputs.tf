output "public_url" {
  description = "Where users reach the assistant."
  value       = local.public_url
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "frontend_bucket" {
  value = aws_s3_bucket.web.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service" {
  value = aws_ecs_service.api.name
}

output "secret_names" {
  description = "Set the two API keys here (see docs/DEPLOYMENT.md)."
  value = {
    anthropic = aws_secretsmanager_secret.anthropic.name
    pinecone  = aws_secretsmanager_secret.pinecone.name
    admin_key = aws_secretsmanager_secret.admin.name
  }
}

output "github_deploy_role_arn" {
  value = local.deploy_enabled ? aws_iam_role.deploy[0].arn : null
}

output "leads_table" {
  value = aws_dynamodb_table.leads.name
}

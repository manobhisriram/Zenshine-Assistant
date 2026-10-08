environment         = "prod"
region              = "ap-south-1"
single_nat_gateway  = false
min_tasks           = 3
max_tasks           = 60
task_cpu            = 1024
task_memory         = 2048
redis_node_type     = "cache.r7g.large"
redis_replicas      = 1
deletion_protection = true
log_retention_days  = 365

# Custom domain + TLS all the way to the ALB (recommended):
# domain_name         = "chat.example.com"
# route53_zone_id     = "Z0123456789ABC"
# alb_domain_name     = "origin.chat.example.com"
# alb_certificate_arn = "arn:aws:acm:ap-south-1:123456789012:certificate/..."

# alarm_emails             = ["oncall@example.com"]
# lead_notification_emails = ["sales@example.com"]
# github_repository        = "your-org/zenshine-assistant"
# waf_allowed_countries    = ["IN", "AE", "SG", "GB", "US"]

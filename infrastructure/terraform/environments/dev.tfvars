environment         = "dev"
region              = "ap-south-1"
single_nat_gateway  = true
min_tasks           = 1
max_tasks           = 4
task_cpu            = 512
task_memory         = 1024
redis_node_type     = "cache.t4g.micro"
redis_replicas      = 0
deletion_protection = false
log_retention_days  = 30

# alarm_emails             = ["you@example.com"]
# lead_notification_emails = ["sales@example.com"]
# github_repository        = "your-org/zenshine-assistant"

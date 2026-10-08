variable "project" {
  description = "Short name used as a prefix for every resource."
  type        = string
  default     = "zenshine"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)."
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "region" {
  description = "AWS region for the regional stack. Deploy the stack once per market region."
  type        = string
  default     = "ap-south-1"
}

# ── Network ───────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  type    = number
  default = 3
}

variable "single_nat_gateway" {
  description = "One shared NAT gateway (cheaper, not AZ-resilient). Use false in prod."
  type        = bool
  default     = false
}

# ── Service sizing ────────────────────────────────────────────────────────
variable "container_image_tag" {
  description = "Image tag in ECR to run (the git short SHA). Required: ECR tags are immutable."
  type        = string
}

variable "cpu_architecture" {
  type    = string
  default = "X86_64"
  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "task_cpu" {
  type    = number
  default = 1024
}

variable "task_memory" {
  type    = number
  default = 2048
}

variable "min_tasks" {
  type    = number
  default = 2
}

variable "max_tasks" {
  type    = number
  default = 40
}

variable "target_cpu_percent" {
  type    = number
  default = 55
}

variable "target_requests_per_task" {
  description = "ALB requests per target per minute that triggers scale-out."
  type        = number
  default     = 600
}

# ── Application configuration ─────────────────────────────────────────────
variable "app_env_overrides" {
  description = "Extra non-secret environment variables for the API container (e.g. ANTHROPIC_MODEL)."
  type        = map(string)
  default     = {}
}

variable "default_tenant" {
  type    = string
  default = "zenshine"
}

variable "pinecone_index" {
  type    = string
  default = "zenshine-assistant"
}

variable "pinecone_cloud" {
  type    = string
  default = "aws"
}

variable "pinecone_region" {
  type    = string
  default = "us-east-1"
}

variable "trusted_proxy_hops" {
  description = "Proxies in front of the app: CloudFront + ALB = 2, ALB only = 1."
  type        = number
  default     = 2
}

# ── Edge / DNS ────────────────────────────────────────────────────────────
variable "domain_name" {
  description = "Public hostname for the app (e.g. chat.example.com). Empty = use the *.cloudfront.net domain."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone for domain_name. Required when domain_name is set (certificate validation + alias record)."
  type        = string
  default     = ""
}

variable "cors_origins" {
  description = "Extra allowed browser origins (the CloudFront/custom domain is added automatically)."
  type        = list(string)
  default     = []
}

variable "alb_domain_name" {
  description = "Hostname that points at the ALB and matches alb_certificate_arn. Enables TLS between CloudFront and the ALB (recommended in prod)."
  type        = string
  default     = ""
}

variable "alb_certificate_arn" {
  description = "Regional ACM certificate for alb_domain_name."
  type        = string
  default     = ""
}

variable "waf_rate_limit_per_5min" {
  description = "Requests per IP per 5 minutes before WAF blocks (applies to the whole site)."
  type        = number
  default     = 2000
}

variable "waf_chat_rate_limit_per_5min" {
  description = "Stricter per-IP limit for /v1/chat* (LLM cost control)."
  type        = number
  default     = 300
}

variable "waf_allowed_countries" {
  description = "ISO country codes allowed to reach the app. Empty = all countries."
  type        = list(string)
  default     = []
}

# ── Observability / ops ───────────────────────────────────────────────────
variable "alarm_emails" {
  type    = list(string)
  default = []
}

variable "lead_notification_emails" {
  type    = list(string)
  default = []
}

variable "log_retention_days" {
  type    = number
  default = 90
}

variable "leads_retention_days" {
  type    = number
  default = 90
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "redis_replicas" {
  description = "Read replicas per shard (1 = multi-AZ failover)."
  type        = number
  default     = 1
}

variable "deletion_protection" {
  type    = bool
  default = true
}

# ── CI/CD ─────────────────────────────────────────────────────────────────
variable "github_repository" {
  description = "owner/repo allowed to deploy via OIDC. Empty = do not create the deploy role."
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Set false if the account already has the token.actions.githubusercontent.com OIDC provider."
  type        = bool
  default     = true
}

variable "enable_waf_logging" {
  type    = bool
  default = true
}

variable "name_suffix" {
  description = "Appended to every resource name. Use it to run several regional stacks of the same environment in one account (e.g. \"-eu\")."
  type        = string
  default     = ""
}

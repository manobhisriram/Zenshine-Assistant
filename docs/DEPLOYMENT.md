# AWS deployment

The Terraform in `infrastructure/terraform` creates: VPC (3 AZs, private subnets, NAT per AZ), ECS Fargate service with autoscaling, ALB, ECR, ElastiCache Redis (TLS, auth, Multi-AZ), DynamoDB + SNS for leads, Secrets Manager, S3 + CloudFront for the UI and API edge, WAFv2, optional ACM/Route 53 custom domain, CloudWatch dashboard and alarms, and an optional GitHub OIDC deploy role.

> The Terraform was formatted and statically cross-checked but **not applied or provider-validated** in the environment that produced this repository (the provider registry was unreachable). Run `terraform validate` and review `terraform plan` in a sandbox account first; CI runs `validate` on every PR.

## Prerequisites

AWS account and admin credentials for the first run, Terraform >= 1.6, Docker, AWS CLI, and an Anthropic and a Pinecone API key.

## Steps

### 1. Choose region and sizing
Edit `environments/prod.tfvars` (and `dev.tfvars`). Defaults target `ap-south-1`. Set `alarm_emails` and `lead_notification_emails` (each address receives a confirmation email from SNS). For a custom domain also set `domain_name`, `route53_zone_id`, and for TLS between CloudFront and the ALB: `alb_domain_name` + `alb_certificate_arn` (a regional ACM certificate for that hostname). Without the ALB certificate the CloudFront-to-ALB hop is plain HTTP over AWS's network, protected by the header secret and security group; use TLS in production.

### 2. Create the remote-state bucket (once per account and region)
```bash
cd infrastructure/terraform/bootstrap && terraform init && terraform apply
cd .. && cp environments/prod.backend.hcl.example environments/prod.backend.hcl   # put the bucket name in
```

### 3. Provision
```bash
./infrastructure/scripts/first-deploy.sh prod
```
This creates the registry, builds and pushes the image, applies the stack, then prints the commands for step 4.

### 4. Add the API keys
```bash
aws secretsmanager put-secret-value --secret-id <name from output> --secret-string 'sk-ant-...'
aws secretsmanager put-secret-value --secret-id <name from output> --secret-string 'pcsk_...'
aws ecs update-service --cluster <cluster> --service api --force-new-deployment
```
Until both keys are set, production tasks refuse to start (fail-fast by design). On first healthy start the service creates the Pinecone index and ingests the knowledge base.

### 5. Publish the frontend
```bash
cd frontend && npm ci && npm run build
aws s3 sync dist s3://$(terraform -chdir=../infrastructure/terraform output -raw frontend_bucket) --delete
aws cloudfront create-invalidation --distribution-id $(terraform -chdir=../infrastructure/terraform output -raw cloudfront_distribution_id) --paths '/*'
```
CI does this automatically after step 6.

### 6. Turn on CI/CD
Set `github_repository = "owner/repo"` in tfvars and apply to create the OIDC deploy role. In GitHub, create environments `dev` and `prod` (add required reviewers to `prod`) and set these environment variables: `AWS_REGION`, `AWS_DEPLOY_ROLE_ARN` (output `github_deploy_role_arn`), `FRONTEND_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, `PUBLIC_URL`, and `RESOURCE_NAME` if you use `name_suffix`. Merges to `main` deploy `dev`; run the Deploy workflow manually to promote `prod`.

## Notes

- **Security group rule quota.** The CloudFront prefix list counts as about 55 rules against the ALB security group's default quota of 60; keep that group dedicated or request a quota increase.
- **Response timeout.** CloudFront's origin read timeout is 60 s (the default maximum). Streams are fine because bytes keep flowing; a single silent gap above 60 s would be cut.
- **Costs to watch.** NAT gateways (one per AZ in prod), ElastiCache, Fargate, WAF requests, and above all Anthropic tokens. WAF per-IP limits and the application rate limits are your cost-abuse controls.
- **Multiple regions.** Deploy another stack with a different `region` and `name_suffix`, then use Route 53 latency or geolocation routing. Consider a Pinecone index per region for data residency.
- **Teardown.** Set `deletion_protection = false`, apply, then `terraform destroy`. Secrets in prod have a 30-day recovery window.

#!/usr/bin/env bash
# First-time provisioning for an environment. Safe to re-run.
#   ./infrastructure/scripts/first-deploy.sh dev
# Prereqs: AWS credentials, Terraform >= 1.6, Docker, and a state bucket (see docs/DEPLOYMENT.md step 2).
set -euo pipefail

ENV="${1:?usage: first-deploy.sh <dev|staging|prod>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TF="$ROOT/infrastructure/terraform"
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD)"

cd "$TF"
terraform init -backend-config="environments/${ENV}.backend.hcl" -reconfigure

echo "==> 1/4 Creating the container registry"
terraform apply -auto-approve -var-file="environments/${ENV}.tfvars" -var "container_image_tag=${TAG}" \
  -target=aws_ecr_repository.api -target=aws_ecr_lifecycle_policy.api

REPO_URL="$(terraform output -raw ecr_repository_url)"
REGION="$(echo "$REPO_URL" | cut -d. -f4)"

echo "==> 2/4 Building and pushing ${REPO_URL}:${TAG}"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO_URL%%/*}"
docker build --platform linux/amd64 -t "${REPO_URL}:${TAG}" "$ROOT/backend"
docker push "${REPO_URL}:${TAG}"

echo "==> 3/4 Provisioning the full stack"
terraform apply -var-file="environments/${ENV}.tfvars" -var "container_image_tag=${TAG}"

cat <<MSG

==> 4/4 Add your API keys (they never touch Terraform state or Git):

  aws secretsmanager put-secret-value --region ${REGION} --secret-id "$(terraform output -json secret_names | python3 -c 'import json,sys; print(json.load(sys.stdin)["anthropic"])')" --secret-string 'sk-ant-...'
  aws secretsmanager put-secret-value --region ${REGION} --secret-id "$(terraform output -json secret_names | python3 -c 'import json,sys; print(json.load(sys.stdin)["pinecone"])')" --secret-string 'pcsk_...'
  aws ecs update-service --region ${REGION} --cluster "$(terraform output -raw ecs_cluster)" --service api --force-new-deployment

Then publish the web UI:  see docs/DEPLOYMENT.md, "Publish the frontend".
Public URL: $(terraform output -raw public_url)
MSG

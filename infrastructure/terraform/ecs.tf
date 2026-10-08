resource "aws_cloudwatch_log_group" "api" {
  name              = local.api_log_group
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

locals {
  app_environment = merge(
    {
      APP_ENV              = "production"
      LOG_LEVEL            = "INFO"
      DEFAULT_TENANT       = var.default_tenant
      CORS_ORIGINS         = local.cors_origins
      TRUSTED_PROXY_HOPS   = tostring(var.trusted_proxy_hops)
      PINECONE_INDEX       = var.pinecone_index
      PINECONE_CLOUD       = var.pinecone_cloud
      PINECONE_REGION      = var.pinecone_region
      LEADS_BACKEND        = "dynamodb"
      LEADS_DYNAMODB_TABLE = aws_dynamodb_table.leads.name
      LEADS_SNS_TOPIC_ARN  = aws_sns_topic.leads.arn
      LEADS_RETENTION_DAYS = tostring(var.leads_retention_days)
      AWS_REGION           = var.region
      EMF_ENABLED          = "true"
      EMF_NAMESPACE        = local.emf_namespace
      AUTO_INGEST          = "true"
      APP_VERSION          = var.container_image_tag
      OTEL_SERVICE_NAME    = "${local.name}-api"
    },
    var.app_env_overrides
  )
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name                   = "api"
      image                  = "${aws_ecr_repository.api.repository_url}:${var.container_image_tag}"
      essential              = true
      readonlyRootFilesystem = false
      stopTimeout            = 30
      portMappings           = [{ containerPort = local.container_port, protocol = "tcp" }]
      environment            = [for k, v in local.app_environment : { name = k, value = v }]
      secrets = [
        { name = "ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.anthropic.arn },
        { name = "PINECONE_API_KEY", valueFrom = aws_secretsmanager_secret.pinecone.arn },
        { name = "ADMIN_API_KEY", valueFrom = aws_secretsmanager_secret.admin.arn },
        { name = "METRICS_TOKEN", valueFrom = aws_secretsmanager_secret.metrics.arn },
        { name = "REDIS_URL", valueFrom = aws_secretsmanager_secret.redis_url.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "api"
        }
      }
      linuxParameters = { initProcessEnabled = true }
      ulimits         = [{ name = "nofile", softLimit = 65536, hardLimit = 65536 }]
    }
  ])
}

resource "aws_ecs_service" "api" {
  name                               = "api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.min_tasks
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = local.container_port
  }

  # CI/CD registers new task-definition revisions; autoscaling owns desired_count.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront, aws_iam_role_policy.execution_secrets]
}

resource "aws_appautoscaling_target" "api" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  min_capacity       = var.min_tasks
  max_capacity       = var.max_tasks
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  resource_id        = aws_appautoscaling_target.api.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.target_cpu_percent
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "requests" {
  name               = "${local.name}-requests"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  resource_id        = aws_appautoscaling_target.api.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.target_requests_per_task
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.api.arn_suffix}/${aws_lb_target_group.api.arn_suffix}"
    }
  }
}

resource "aws_lb" "api" {
  name                       = substr("${local.name}-api", 0, 32)
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  idle_timeout               = 120 # SSE streams stay open; must exceed the longest silent gap
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
  enable_http2               = true
}

resource "aws_lb_target_group" "api" {
  name                 = substr("${local.name}-api", 0, 32)
  port                 = local.container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener" "main" {
  load_balancer_arn = aws_lb.api.arn
  port              = local.alb_tls ? 443 : 80
  protocol          = local.alb_tls ? "HTTPS" : "HTTP"
  ssl_policy        = local.alb_tls ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  certificate_arn   = local.alb_tls ? var.alb_certificate_arn : null

  # Anything that did not come through CloudFront (no origin-verify header) is refused.
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":{\"code\":\"forbidden\",\"message\":\"Forbidden\"}}"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.main.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_verify.result]
    }
  }

  # Operational endpoints are never exposed publicly.
  condition {
    path_pattern {
      values = ["/v1/*"]
    }
  }
}

resource "aws_route53_record" "alb" {
  count   = local.alb_tls && var.route53_zone_id != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.alb_domain_name
  type    = "A"
  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

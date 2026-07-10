# API service trigger (ALB + ECS service) - active when trigger_type is:
#   ecs_api_service          - public ALB (internet-facing)
#   ecs_internal_api_service - internal ALB, reachable only from inside the VPC (service-to-service)
# Set API_DOMAIN and API_ROOT_DOMAIN in config.<env> when using a custom domain + HTTPS.

locals {
  ecs_api_service_enabled = contains(["ecs_api_service", "ecs_service", "ecs_internal_api_service"], var.trigger_type)
  api_internal            = var.trigger_type == "ecs_internal_api_service"

  # Internal mode places the ALB and tasks in private subnets; public mode uses public
  # subnets. Both fall back to all VPC subnets when none match (see main.tf locals).
  api_private_subnets_exist = length(data.aws_subnets.private.ids) > 0
  api_subnets               = local.api_internal ? local.private_subnets_or_all : local.public_subnets_or_all
  api_alb_ingress_cidrs     = local.api_internal ? [local.vpc_cidr] : ["0.0.0.0/0"]

  api_fargate_strategy = tolist([{ capacity_provider = "FARGATE", weight = 1 }])
  api_fargate_spot_strategy = tolist([
    { capacity_provider = "FARGATE", weight = 2 },
    { capacity_provider = "FARGATE_SPOT", weight = 8 },
  ])
  api_ec2_strategy = tolist([{ capacity_provider = "EC2", weight = 1 }])

  api_ecs_target = local.ecs_api_service_enabled ? {
    capacity_provider_strategy = (
      var.LAUNCH_TYPE == "FARGATE" ? local.api_fargate_strategy :
      var.LAUNCH_TYPE == "FARGATE_SPOT" ? local.api_fargate_spot_strategy :
      local.api_ec2_strategy
    )
    network_configuration = (
      var.LAUNCH_TYPE == "FARGATE" || var.LAUNCH_TYPE == "FARGATE_SPOT"
        ? {
            security_groups  = [aws_security_group.ecs_sg[0].id]
            subnets          = local.api_subnets
            # Tasks in subnets without a NAT path still need a public IP to pull from ECR.
            assign_public_ip = local.api_internal ? !local.api_private_subnets_exist : true
          }
        : {
            security_groups  = [aws_security_group.ecs_sg[0].id]
            subnets          = local.api_subnets
            assign_public_ip = false
          }
    )
  } : null
}

locals {
  api_cluster_name = local.ecs_api_service_enabled ? element(split("/", aws_ecs_cluster.ecs.arn), 1) : ""
}

data "aws_route53_zone" "api_domain" {
  count = local.ecs_api_service_enabled && var.API_ROOT_DOMAIN != "" ? 1 : 0

  name = "${var.API_ROOT_DOMAIN}."
}

# Security groups first (referenced by api_ecs_target local and ALB)
resource "aws_security_group" "ecs_sg" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name   = "${var.APP_IDENT}-ecs-sg"
  vpc_id = local.vpc_id

  # Public API keeps the historically open app port; internal API admits only the ALB.
  dynamic "ingress" {
    for_each = local.api_internal ? [] : [1]
    content {
      from_port   = 8080
      to_port     = 8080
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  dynamic "ingress" {
    for_each = local.api_internal ? [1] : []
    content {
      from_port       = 8080
      to_port         = 8080
      protocol        = "tcp"
      security_groups = [aws_security_group.alb_sg[0].id]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "alb_sg" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name   = "${var.APP_IDENT}-alb-sg"
  vpc_id = local.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = local.api_alb_ingress_cidrs
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = local.api_alb_ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "ecs_alb" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name               = "${var.APP_IDENT}-alb"
  internal           = local.api_internal
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg[0].id]
  subnets            = local.api_subnets

  enable_deletion_protection = false
  enable_http2               = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "ecs_target_group" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name        = "${var.APP_IDENT}-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"

  deregistration_delay = 30

  health_check {
    path                = "/healthcheck"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 10
    matcher             = "200"
    port                = "traffic-port"
    protocol            = "HTTP"
  }
}

resource "aws_ecs_service" "ecs_service" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name            = "${var.APP_IDENT}-service"
  cluster         = aws_ecs_cluster.ecs.arn
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count   = var.MIN_COUNT
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  # Propagate service tags (Environment/Repository/Project) onto running tasks
  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"

  dynamic "capacity_provider_strategy" {
    for_each = local.ecs_api_service_enabled ? local.api_ecs_target.capacity_provider_strategy : []
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  dynamic "network_configuration" {
    for_each = local.ecs_api_service_enabled ? [local.api_ecs_target.network_configuration] : []
    content {
      security_groups  = network_configuration.value.security_groups
      subnets          = network_configuration.value.subnets
      assign_public_ip = network_configuration.value.assign_public_ip
    }
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
    container_name   = var.APP_IDENT
    container_port   = 8080
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    create_before_destroy = true
    ignore_changes       = [desired_count]
  }
}

resource "aws_appautoscaling_target" "ecs_target" {
  count = local.ecs_api_service_enabled ? 1 : 0

  max_capacity       = var.MAX_COUNT
  min_capacity       = var.MIN_COUNT
  resource_id        = local.ecs_api_service_enabled ? "service/${local.api_cluster_name}/${aws_ecs_service.ecs_service[0].name}" : ""
  scalable_dimension  = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "scale_out" {
  count = local.ecs_api_service_enabled ? 1 : 0

  name                = "scale-out"
  service_namespace    = local.ecs_api_service_enabled ? aws_appautoscaling_target.ecs_target[0].service_namespace : "ecs"
  resource_id          = local.ecs_api_service_enabled ? aws_appautoscaling_target.ecs_target[0].resource_id : ""
  scalable_dimension   = local.ecs_api_service_enabled ? aws_appautoscaling_target.ecs_target[0].scalable_dimension : "ecs:service:DesiredCount"
  policy_type          = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    target_value = 75.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_out_cooldown = 60
    scale_in_cooldown  = 60
  }
}

resource "aws_lb_listener" "http_listener" {
  count = local.ecs_api_service_enabled ? 1 : 0

  load_balancer_arn = aws_lb.ecs_alb[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
  }
}

# Certificate and HTTPS (only when API_DOMAIN is set).
# Certificate must be in the same region as the ALB (default provider); us-east-1 is only for CloudFront/API Gateway.
resource "aws_acm_certificate" "cert" {
  count = local.ecs_api_service_enabled && var.API_DOMAIN != "" ? 1 : 0

  domain_name       = var.API_DOMAIN
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation_records" {
  for_each = local.ecs_api_service_enabled && var.API_DOMAIN != "" ? {
    for dvo in aws_acm_certificate.cert[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id = data.aws_route53_zone.api_domain[0].zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "cert_validation" {
  count = local.ecs_api_service_enabled && var.API_DOMAIN != "" ? 1 : 0

  certificate_arn         = aws_acm_certificate.cert[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation_records : r.fqdn]
}

resource "aws_lb_listener" "https_listener" {
  count = local.ecs_api_service_enabled && var.API_DOMAIN != "" ? 1 : 0

  depends_on         = [aws_acm_certificate_validation.cert_validation]
  load_balancer_arn  = aws_lb.ecs_alb[0].arn
  port               = 443
  protocol           = "HTTPS"
  ssl_policy         = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn    = aws_acm_certificate.cert[0].arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
  }
}

resource "aws_route53_record" "alb_dns_record" {
  count = local.ecs_api_service_enabled && var.API_DOMAIN != "" && var.API_ROOT_DOMAIN != "" ? 1 : 0

  zone_id = data.aws_route53_zone.api_domain[0].zone_id
  name    = var.API_DOMAIN
  type    = "A"

  alias {
    name                   = aws_lb.ecs_alb[0].dns_name
    zone_id                = aws_lb.ecs_alb[0].zone_id
    evaluate_target_health = true
  }
}

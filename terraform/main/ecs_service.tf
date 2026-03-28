# ECS trigger: Always-on ECS Service behind ALB
# Active when trigger_type = "ecs_api_service" (or legacy "ecs_service")
# Set api_domain and api_root_domain for HTTPS + Route53 (optional).

locals {
  ecs_service_enabled         = var.trigger_type == "ecs_api_service" || var.trigger_type == "ecs_service"
  ecs_service_domain_enabled  = local.ecs_service_enabled && var.api_domain != "" && var.api_root_domain != ""
  ecs_service_capacity_provider_strategy = var.launch_type == "FARGATE" ? tolist([{ capacity_provider = "FARGATE", weight = 1 }]) : var.launch_type == "FARGATE_SPOT" ? tolist([{ capacity_provider = "FARGATE", weight = 3 }, { capacity_provider = "FARGATE_SPOT", weight = 7 }]) : tolist([{ capacity_provider = "EC2", weight = 1 }])
}

resource "aws_security_group" "ecs_sg" {
  count = local.ecs_service_enabled ? 1 : 0

  name   = "${var.app_ident}-ecs-sg"
  vpc_id = data.aws_vpc.selected.id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "alb_sg" {
  count = local.ecs_service_enabled ? 1 : 0

  name   = "${var.app_ident}-alb-sg"
  vpc_id = data.aws_vpc.selected.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "ecs_alb" {
  count = local.ecs_service_enabled ? 1 : 0

  name               = "${var.app_ident}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg[0].id]
  subnets            = data.aws_subnets.public.ids
}

resource "aws_lb_target_group" "ecs_target_group" {
  count = local.ecs_service_enabled ? 1 : 0

  name        = substr("${var.app_ident}-tg", 0, 32)
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.selected.id
  target_type = "ip"

  health_check {
    path = "/ping"
  }
}

resource "aws_lb_listener" "http_listener" {
  count = local.ecs_service_enabled ? 1 : 0

  load_balancer_arn = aws_lb.ecs_alb[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
  }
}

resource "aws_ecs_service" "ecs_service" {
  count = local.ecs_service_enabled ? 1 : 0

  name            = "${var.app_ident}-service"
  cluster         = aws_ecs_cluster.ecs.arn
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count   = var.desired_count

  dynamic "capacity_provider_strategy" {
    for_each = local.ecs_service_capacity_provider_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  network_configuration {
    security_groups  = [aws_security_group.ecs_sg[0].id]
    subnets          = data.aws_subnets.public.ids
    assign_public_ip = var.launch_type == "FARGATE" || var.launch_type == "FARGATE_SPOT"
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
    container_name   = var.app_ident
    container_port   = 8080
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    create_before_destroy = true
  }
}

data "aws_route53_zone" "api_domain" {
  count = local.ecs_service_domain_enabled ? 1 : 0

  name = "${var.api_root_domain}."
}

resource "aws_acm_certificate" "cert" {
  count = local.ecs_service_domain_enabled ? 1 : 0

  domain_name       = var.api_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation_records" {
  for_each = {
    for dvo in flatten([for cert in aws_acm_certificate.cert : cert.domain_validation_options]) :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  provider = aws.useast1

  zone_id = data.aws_route53_zone.api_domain[0].zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "cert_validation" {
  count = local.ecs_service_domain_enabled ? 1 : 0

  certificate_arn         = aws_acm_certificate.cert[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation_records : record.fqdn]
}

resource "aws_lb_listener" "https_listener" {
  count = local.ecs_service_domain_enabled ? 1 : 0

  depends_on = [aws_acm_certificate_validation.cert_validation]

  load_balancer_arn = aws_lb.ecs_alb[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.cert[0].arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ecs_target_group[0].arn
  }
}

resource "aws_route53_record" "alb_dns_record" {
  count = local.ecs_service_domain_enabled ? 1 : 0

  zone_id = data.aws_route53_zone.api_domain[0].zone_id
  name    = var.api_domain
  type    = "A"

  alias {
    name                   = aws_lb.ecs_alb[0].dns_name
    zone_id                = aws_lb.ecs_alb[0].zone_id
    evaluate_target_health = true
  }
}

# Background service trigger (always-on ECS service, no ALB) - active when trigger_type = "ecs_background_service"
# Use for long-running workers that don't need HTTP ingress. MIN_COUNT sets the task count.

locals {
  ecs_background_service_enabled = var.trigger_type == "ecs_background_service"

  bg_capacity_provider_strategy = (
    var.LAUNCH_TYPE == "FARGATE" ? tolist([{ capacity_provider = "FARGATE", weight = 1 }]) :
    var.LAUNCH_TYPE == "FARGATE_SPOT" ? tolist([
      { capacity_provider = "FARGATE", weight = 2 },
      { capacity_provider = "FARGATE_SPOT", weight = 8 },
    ]) :
    tolist([{ capacity_provider = "EC2", weight = 1 }])
  )
}

# Workers take no inbound traffic at all - this group has no ingress rules. Egress uses
# the shared task baseline (443 out, plus anything in-VPC) instead of allow-all, so a
# compromised task can't reach arbitrary ports on arbitrary hosts.
resource "aws_security_group" "ecs_bg_sg" {
  count = local.ecs_background_service_enabled ? 1 : 0

  name   = "${var.APP_IDENT}-bg-sg"
  vpc_id = local.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "ecs_bg_egress" {
  for_each = local.ecs_background_service_enabled ? local.task_egress_rule_map : {}

  security_group_id = aws_security_group.ecs_bg_sg[0].id
  cidr_ipv4         = each.value.cidr_ipv4
  from_port         = each.value.from_port
  to_port           = each.value.to_port
  ip_protocol       = each.value.ip_protocol
  description       = each.value.description
}

resource "aws_ecs_service" "ecs_bg_service" {
  count = local.ecs_background_service_enabled ? 1 : 0

  name            = "${var.APP_IDENT}-service"
  cluster         = aws_ecs_cluster.ecs.arn
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count = var.MIN_COUNT

  # Propagate service tags (Environment/Repository/Project) onto running tasks
  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"

  dynamic "capacity_provider_strategy" {
    for_each = local.bg_capacity_provider_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  network_configuration {
    security_groups  = [aws_security_group.ecs_bg_sg[0].id]
    subnets          = local.public_subnets_or_all
    assign_public_ip = var.LAUNCH_TYPE == "FARGATE" || var.LAUNCH_TYPE == "FARGATE_SPOT"
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    create_before_destroy = true
  }
}

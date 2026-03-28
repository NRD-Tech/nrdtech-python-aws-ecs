# ECS trigger: Background service (always-on, no ALB)
# Active when trigger_type = "ecs_background_service"
# Use for long-running workers that don't need HTTP ingress.

locals {
  ecs_bg_enabled = var.trigger_type == "ecs_background_service"

  ecs_bg_capacity_provider_strategy = var.launch_type == "FARGATE" ? tolist([{
    capacity_provider = "FARGATE", weight = 1
  }]) : var.launch_type == "FARGATE_SPOT" ? tolist([{
    capacity_provider = "FARGATE", weight = 3
  }, {
    capacity_provider = "FARGATE_SPOT", weight = 7
  }]) : tolist([{
    capacity_provider = "EC2", weight = 1
  }])
}

resource "aws_security_group" "ecs_bg_sg" {
  count = local.ecs_bg_enabled ? 1 : 0

  name   = "${var.app_ident}-bg-sg"
  vpc_id = data.aws_vpc.selected.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_service" "ecs_bg_service" {
  count = local.ecs_bg_enabled ? 1 : 0

  name            = "${var.app_ident}-service"
  cluster         = aws_ecs_cluster.ecs.arn
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count   = var.desired_count

  dynamic "capacity_provider_strategy" {
    for_each = local.ecs_bg_capacity_provider_strategy
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      weight            = capacity_provider_strategy.value.weight
    }
  }

  network_configuration {
    security_groups  = [aws_security_group.ecs_bg_sg[0].id]
    subnets          = data.aws_subnets.public.ids
    assign_public_ip = var.launch_type == "FARGATE" || var.launch_type == "FARGATE_SPOT"
  }

  deployment_controller {
    type = "ECS"
  }

  lifecycle {
    create_before_destroy = true
  }
}

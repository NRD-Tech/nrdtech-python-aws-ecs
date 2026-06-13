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

resource "aws_security_group" "ecs_bg_sg" {
  count = local.ecs_background_service_enabled ? 1 : 0

  name   = "${var.APP_IDENT}-bg-sg"
  vpc_id = local.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_service" "ecs_bg_service" {
  count = local.ecs_background_service_enabled ? 1 : 0

  name            = "${var.APP_IDENT}-service"
  cluster         = aws_ecs_cluster.ecs.arn
  task_definition = aws_ecs_task_definition.task_definition.arn
  desired_count   = var.MIN_COUNT

  tags = data.terraform_remote_state.app_bootstrap.outputs.app_tags

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

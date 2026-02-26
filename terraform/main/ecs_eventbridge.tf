# ECS trigger: EventBridge schedule (RunTask on cron)
# Active when trigger_type = "ecs_eventbridge"

locals {
  ecs_eventbridge_target = var.launch_type == "FARGATE" ? {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = "FARGATE"
    capacity_provider_strategy = []
    network_configuration = {
      subnets          = data.aws_subnets.public.ids
      assign_public_ip = true
    }
  } : var.launch_type == "FARGATE_SPOT" ? {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = null
    capacity_provider_strategy = [{ capacity_provider = "FARGATE_SPOT", weight = 1 }]
    network_configuration = {
      subnets          = data.aws_subnets.public.ids
      assign_public_ip = true
    }
  } : {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = "EC2"
    capacity_provider_strategy = []
    network_configuration      = null
  }
}

resource "aws_cloudwatch_event_rule" "ecs_rule" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  name                = "${var.app_ident}-ecs-rule"
  schedule_expression = "cron(0 * * * ? *)"
  state               = var.environment == "prod" ? "ENABLED" : "DISABLED"
}

resource "aws_sqs_queue" "eventbridge_rule_dlq" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  name = "${var.app_ident}-eventbridge-rule-dlq"
}

resource "aws_iam_role" "eventbridge_execution_role" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  name = "${var.app_ident}-target-execution-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Principal = { Service = "events.amazonaws.com" }
      Effect    = "Allow"
    }]
  })
}

resource "aws_iam_policy" "eventbridge_execution_role_policy" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  name = "${var.app_ident}-eventbridge-role-policy"

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecs:RunTask", "ecs:StopTask", "iam:PassRole", "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_execution_role_policy_attachment" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  role       = aws_iam_role.eventbridge_execution_role[0].name
  policy_arn = aws_iam_policy.eventbridge_execution_role_policy[0].arn
}

resource "aws_cloudwatch_event_target" "ecs_target" {
  count = var.trigger_type == "ecs_eventbridge" ? 1 : 0

  rule     = aws_cloudwatch_event_rule.ecs_rule[0].name
  arn      = aws_ecs_cluster.ecs.arn
  role_arn = aws_iam_role.eventbridge_execution_role[0].arn

  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_rule_dlq[0].arn
  }

  ecs_target {
    task_definition_arn = local.ecs_eventbridge_target.task_definition_arn
    launch_type         = lookup(local.ecs_eventbridge_target, "launch_type", null)

    dynamic "capacity_provider_strategy" {
      for_each = lookup(local.ecs_eventbridge_target, "capacity_provider_strategy", [])
      content {
        capacity_provider = capacity_provider_strategy.value.capacity_provider
        weight            = capacity_provider_strategy.value.weight
      }
    }

    dynamic "network_configuration" {
      for_each = lookup(local.ecs_eventbridge_target, "network_configuration", null) != null ? [1] : []
      content {
        subnets          = local.ecs_eventbridge_target.network_configuration.subnets
        assign_public_ip = local.ecs_eventbridge_target.network_configuration.assign_public_ip
      }
    }
  }
}

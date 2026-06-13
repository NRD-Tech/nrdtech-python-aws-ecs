######################################################
# EventBridge schedule trigger - active when trigger_type = "ecs_eventbridge"
######################################################

locals {
  ecs_eventbridge_enabled = var.trigger_type == "ecs_eventbridge"
}

resource "aws_cloudwatch_event_rule" "ecs_rule" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  # Must be no longer than 64 characters
  name                = "${var.APP_IDENT}-ecs-rule"
  schedule_expression = "cron(0 * * * ? *)"

  # NOTE: All environments except prod are disabled by default here
  state = var.ENVIRONMENT == "prod" ? "ENABLED" : "DISABLED"
}

locals {
  ecs_target = var.LAUNCH_TYPE == "FARGATE" ? {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = "FARGATE"
    capacity_provider_strategy = []
    network_configuration = {
      subnets          = local.public_subnets_or_all
      assign_public_ip = true
    }
  } : var.LAUNCH_TYPE == "FARGATE_SPOT" ? {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = null
    capacity_provider_strategy = [{
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
    }]
    network_configuration = {
      subnets          = local.public_subnets_or_all
      assign_public_ip = true
    }
  } : {
    task_definition_arn        = aws_ecs_task_definition.task_definition.arn
    launch_type                = "EC2"
    capacity_provider_strategy = []
    network_configuration      = null
  }
}


resource "aws_cloudwatch_event_target" "ecs_target" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  rule     = aws_cloudwatch_event_rule.ecs_rule[0].name
  arn      = aws_ecs_cluster.ecs.arn
  role_arn = aws_iam_role.execution_role[0].arn
  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_rule_dlq[0].arn
  }

  ecs_target {
    task_definition_arn = local.ecs_target.task_definition_arn

    # Handle launch_type or capacity_provider_strategy
    dynamic "capacity_provider_strategy" {
      for_each = lookup(local.ecs_target, "capacity_provider_strategy", [])
      content {
        capacity_provider = capacity_provider_strategy.value.capacity_provider
        weight            = capacity_provider_strategy.value.weight
      }
    }

    # Direct launch_type for FARGATE and EC2
    launch_type = lookup(local.ecs_target, "launch_type", null)

    # Network configuration for FARGATE and FARGATE_SPOT
    dynamic "network_configuration" {
      for_each = lookup(local.ecs_target, "network_configuration", []) != null ? [1] : []
      content {
        subnets          = local.ecs_target.network_configuration.subnets
        assign_public_ip = local.ecs_target.network_configuration.assign_public_ip
      }
    }
  }
}

resource "aws_sqs_queue" "eventbridge_rule_dlq" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  name = "${var.APP_IDENT}-eventbridge-rule-dlq"
}

resource "aws_iam_role" "execution_role" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  name = "${var.APP_IDENT}-target-execution-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Principal = {
          Service = "events.amazonaws.com"
        },
        Effect = "Allow",
      },
    ]
  })
}

resource "aws_iam_policy" "execution_role_policy" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  name        = "${var.APP_IDENT}-role-policy"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        "Effect": "Allow",
        "Action": [
          "ecs:RunTask",
          "ecs:StopTask",
          "iam:PassRole",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cm_execution_role_policy_attachment" {
  count = local.ecs_eventbridge_enabled ? 1 : 0

  role       = aws_iam_role.execution_role[0].name
  policy_arn = aws_iam_policy.execution_role_policy[0].arn
}

# resource "aws_cloudwatch_event_rule" "ecs_rule" {
#   name                = "${var.app_ident}-ecs-rule"
#   schedule_expression = "cron(* * * * ? *)"
# }

# locals {
#   ecs_target = var.launch_type == "FARGATE" ? {
#     task_definition_arn        = aws_ecs_task_definition.task_definition.arn
#     launch_type                = "FARGATE"
#     capacity_provider_strategy = []
#     network_configuration = {
#       subnets          = data.aws_subnets.public.ids
#       assign_public_ip = true
#     }
#   } : var.launch_type == "FARGATE_SPOT" ? {
#     task_definition_arn        = aws_ecs_task_definition.task_definition.arn
#     launch_type                = null
#     capacity_provider_strategy = [{
#       capacity_provider = "FARGATE_SPOT"
#       weight            = 1
#     }]
#     network_configuration = {
#       subnets          = data.aws_subnets.public.ids
#       assign_public_ip = true
#     }
#   } : {
#     task_definition_arn        = aws_ecs_task_definition.task_definition.arn
#     launch_type                = "EC2"
#     capacity_provider_strategy = []
#     network_configuration      = null
#   }
# }


# resource "aws_cloudwatch_event_target" "ecs_target" {
#   rule     = aws_cloudwatch_event_rule.ecs_rule.name
#   arn      = var.ecs_cluster_arn
#   role_arn = aws_iam_role.execution_role.arn
#   dead_letter_config {
#     arn = aws_sqs_queue.eventbridge_rule_dlq.arn
#   }

#   ecs_target {
#     task_definition_arn = local.ecs_target.task_definition_arn

#     # Handle launch_type or capacity_provider_strategy
#     dynamic "capacity_provider_strategy" {
#       for_each = lookup(local.ecs_target, "capacity_provider_strategy", [])
#       content {
#         capacity_provider = capacity_provider_strategy.value.capacity_provider
#         weight            = capacity_provider_strategy.value.weight
#       }
#     }

#     # Direct launch_type for FARGATE and EC2
#     launch_type = lookup(local.ecs_target, "launch_type", null)

#     # Network configuration for FARGATE and FARGATE_SPOT
#     dynamic "network_configuration" {
#       for_each = lookup(local.ecs_target, "network_configuration", []) != null ? [1] : []
#       content {
#         subnets          = local.ecs_target.network_configuration.subnets
#         assign_public_ip = local.ecs_target.network_configuration.assign_public_ip
#       }
#     }
#   }
# }

# resource "aws_sqs_queue" "eventbridge_rule_dlq" {
#   name = "${var.app_ident}-eventbridge-rule-dlq"
# }

# resource "aws_iam_role" "execution_role" {
#   name = "${var.app_ident}-target-execution-role"

#   assume_role_policy = jsonencode({
#     Version   = "2012-10-17",
#     Statement = [
#       {
#         Action    = "sts:AssumeRole",
#         Principal = {
#           Service = "events.amazonaws.com"
#         },
#         Effect = "Allow",
#       },
#     ]
#   })
# }

# resource "aws_iam_policy" "execution_role_policy" {
#   name        = "${var.app_ident}-role-policy"

#   policy = jsonencode({
#     Version   = "2012-10-17",
#     Statement = [
#       {
#         "Effect": "Allow",
#         "Action": [
#           "ecs:RunTask",
#           "ecs:StopTask",
#           "iam:PassRole",
#           "logs:CreateLogGroup",
#           "logs:CreateLogStream",
#           "logs:PutLogEvents"
#         ],
#         "Resource": "*"
#       }
#     ]
#   })
# }

# resource "aws_iam_role_policy_attachment" "cm_execution_role_policy_attachment" {
#   role       = aws_iam_role.execution_role.name
#   policy_arn = aws_iam_policy.execution_role_policy.arn
# }

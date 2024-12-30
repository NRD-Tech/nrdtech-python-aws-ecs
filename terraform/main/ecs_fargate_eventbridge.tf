resource "aws_cloudwatch_event_rule" "ecs_rule" {
  name                = "${var.app_ident}-ecs-rule"
  schedule_expression = "cron(* * * * ? *)"
}

resource "aws_cloudwatch_event_target" "ecs_target" {
  rule     = aws_cloudwatch_event_rule.ecs_rule.name
  arn      = var.ecs_cluster_arn
  role_arn = aws_iam_role.execution_role.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.task_definition.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = data.aws_subnets.public.ids
      assign_public_ip = true
    }
  }
}

resource "aws_iam_role" "execution_role" {
  name = "${var.app_ident}-target-execution-role"

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
  name        = "${var.app_ident}-role-policy"
  description = "A policy that allows a role to put events in EventBridge"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action = [
          "*"
        ],
        Effect   = "Allow",
        Resource = "*",
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cm_execution_role_policy_attachment" {
  role       = aws_iam_role.execution_role.name
  policy_arn = aws_iam_policy.execution_role_policy.arn
}

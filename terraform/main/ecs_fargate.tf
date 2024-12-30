resource "aws_ecs_task_definition" "task_definition" {
  depends_on = [aws_cloudwatch_log_group.log_group]
  family                   = var.app_ident
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.app_cpu
  memory                   = var.app_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = var.app_ident
    image     = "${aws_ecr_repository.ecr_repository.repository_url}:${docker_image.terraform_function_image.triggers.code_hash}"
    cpu       = var.app_cpu
    memory    = var.app_memory
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.log_group.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
    environment = [
        {
          name = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        }
    ]
  }])
}

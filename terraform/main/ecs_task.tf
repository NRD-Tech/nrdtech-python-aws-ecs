resource "aws_ecs_task_definition" "task_definition" {
  depends_on = [aws_cloudwatch_log_group.log_group, null_resource.push_image]
  family                   = var.app_ident
  network_mode             = "awsvpc"
  requires_compatibilities = [var.launch_type == "FARGATE_SPOT" ? "FARGATE" : var.launch_type]
  cpu                      = var.app_cpu
  memory                   = var.app_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  runtime_platform {
    # Options: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html#runtime-platform
    # Typical Options: LINUX, WINDOWS_SERVER_2022_FULL, WINDOWS_SERVER_2022_CORE, WINDOWS_SERVER_2019_FULL, WINDOWS_SERVER_2019_CORE
    operating_system_family = "LINUX"

    # Options: X86_64, ARM64
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([{
    name      = var.app_ident
    image     = "${aws_ecr_repository.ecr_repository.repository_url}:${null_resource.push_image.triggers.code_hash}"
    cpu       = var.app_cpu
    memory    = var.app_memory
    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]
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

# locals {
#   # 1. Define each capacity provider strategy as a list
#   #    so Terraform doesn't see them as "tuple of length 1 vs 2 vs 0"
#   fargate_strategy = tolist([
#     {
#       capacity_provider = "FARGATE"
#       weight            = 1
#     }
#   ])

#   fargate_spot_strategy = tolist([
#     {
#       capacity_provider = "FARGATE"
#       weight            = 3
#     },
#     {
#       capacity_provider = "FARGATE_SPOT"
#       weight            = 7
#     }
#   ])

#   ec2_strategy = tolist([
#     {
#       capacity_provider = "EC2"
#       weight            = 1
#     }
#   ])

#   # 2. Define your local “ecs_target” by picking one of the above
#   ecs_target = {
#     capacity_provider_strategy = (
#       var.launch_type == "FARGATE" ? local.fargate_strategy :
#       var.launch_type == "FARGATE_SPOT" ? local.fargate_spot_strategy :
#       local.ec2_strategy
#     )

#     # network configuration depends on whether it's Fargate or not
#     network_configuration = (
#       var.launch_type == "FARGATE" || var.launch_type == "FARGATE_SPOT"
#         ? {
#             security_groups  = [aws_security_group.ecs_sg.id]
#             subnets          = data.aws_subnets.public.ids
#             assign_public_ip = true
#           }
#         : {
#             security_groups = [aws_security_group.ecs_sg.id]
#             subnets = data.aws_subnets.public.ids
#             assign_public_ip = false
#           }
#     )
#   }
# }

# data "aws_ecs_cluster" "cluster" {
#   cluster = var.ecs_cluster_arn
# }



# # ECS Service
# resource "aws_ecs_service" "ecs_service" {
#   name            = "${var.app_ident}-service"
#   cluster         = var.ecs_cluster_arn
#   task_definition = aws_ecs_task_definition.task_definition.arn
#   desired_count   = var.desired_count

#  dynamic "capacity_provider_strategy" {
#     for_each = local.ecs_target.capacity_provider_strategy
#     content {
#       capacity_provider = capacity_provider_strategy.value.capacity_provider
#       weight            = capacity_provider_strategy.value.weight
#     }
#   }

#   dynamic "network_configuration" {
#     for_each = local.ecs_target.network_configuration != null ? [1] : []
#     content {
#       security_groups  = local.ecs_target.network_configuration.security_groups
#       subnets          = local.ecs_target.network_configuration.subnets
#       assign_public_ip = local.ecs_target.network_configuration.assign_public_ip
#     }
#   }

#   load_balancer {
#     target_group_arn = aws_lb_target_group.ecs_target_group.arn
#     container_name   = var.app_ident
#     container_port   = 8080
#   }

#   deployment_controller {
#     type = "ECS"
#   }

#   lifecycle {
#     create_before_destroy = true
#   }
# }

# # Application Load Balancer
# resource "aws_lb" "ecs_alb" {
#   name               = "${var.app_ident}-alb"
#   internal           = false
#   load_balancer_type = "application"
#   security_groups    = [aws_security_group.alb_sg.id]
#   subnets            = data.aws_subnets.public.ids
# }

# # Target Group
# resource "aws_lb_target_group" "ecs_target_group" {
#   # NOTE: name cannot be longer than 32 characters
#   name        = "${var.app_ident}-tg"
#   port        = 8080
#   protocol    = "HTTP"
#   vpc_id      = data.aws_vpc.selected.id
#   target_type = "ip" # Change this from "instance" to "ip"
#   health_check {
#     path = "/ping"
#   }
# }

# # Listener for ALB
# resource "aws_lb_listener" "http_listener" {
#   load_balancer_arn = aws_lb.ecs_alb.arn
#   port              = 80
#   protocol          = "HTTP"

#   default_action {
#     type             = "forward"
#     target_group_arn = aws_lb_target_group.ecs_target_group.arn
#   }
# }

# resource "aws_lb_listener" "https_listener" {
#   depends_on = [aws_acm_certificate_validation.cert_validation]
#   load_balancer_arn = aws_lb.ecs_alb.arn
#   port              = 443
#   protocol          = "HTTPS"
#   ssl_policy        = "ELBSecurityPolicy-2016-08" # Adjust as needed
#   certificate_arn   = aws_acm_certificate.cert.arn

#   default_action {
#     type             = "forward"
#     target_group_arn = aws_lb_target_group.ecs_target_group.arn
#   }
# }

# # Security Group for ECS and ALB
# resource "aws_security_group" "ecs_sg" {
#   name   = "${var.app_ident}-ecs-sg"
#   vpc_id = data.aws_vpc.selected.id

#   ingress {
#     from_port   = 8080
#     to_port     = 8080
#     protocol    = "tcp"
#     cidr_blocks = ["0.0.0.0/0"]
#   }

#   egress {
#     from_port   = 0
#     to_port     = 0
#     protocol    = "-1"
#     cidr_blocks = ["0.0.0.0/0"]
#   }
# }

# resource "aws_security_group" "alb_sg" {
#   name   = "${var.app_ident}-alb-sg"
#   vpc_id = data.aws_vpc.selected.id

#   ingress {
#     from_port   = 80
#     to_port     = 80
#     protocol    = "tcp"
#     cidr_blocks = ["0.0.0.0/0"]
#   }

#   ingress {
#     from_port   = 443
#     to_port     = 443
#     protocol    = "tcp"
#     cidr_blocks = ["0.0.0.0/0"]
#   }

#   egress {
#     from_port   = 0
#     to_port     = 0
#     protocol    = "-1"
#     cidr_blocks = ["0.0.0.0/0"]
#   }
# }

# ############## route53

# resource "aws_route53_record" "alb_dns_record" {
#   zone_id = data.aws_route53_zone.api_domain.zone_id
#   name    = var.api_domain
#   type    = "A"

#   alias {
#     name                   = aws_lb.ecs_alb.dns_name
#     zone_id                = aws_lb.ecs_alb.zone_id
#     evaluate_target_health = true
#   }
# }

# ############## cert

# resource "aws_acm_certificate" "cert" {
#   domain_name       = var.api_domain
#   validation_method = "DNS"

#   tags = {
#     Environment = "test"
#   }

#   lifecycle {
#     create_before_destroy = true
#   }
# }

# resource "aws_acm_certificate_validation" "cert_validation" {
#   certificate_arn         = aws_acm_certificate.cert.arn
#   validation_record_fqdns = [for record in aws_route53_record.cert_validation_records : record.fqdn]

#   depends_on = [aws_route53_record.cert_validation_records]
# }

# resource "aws_route53_record" "cert_validation_records" {
#   provider = aws.useast1
#   for_each = {
#     for dvo in aws_acm_certificate.cert.domain_validation_options : dvo.domain_name => {
#       name   = dvo.resource_record_name
#       record = dvo.resource_record_value
#       type   = dvo.resource_record_type
#     }
#   }

#   zone_id = data.aws_route53_zone.api_domain.zone_id
#   name    = each.value.name
#   type    = each.value.type
#   records = [each.value.record]
#   ttl     = 60
# }

# data "aws_route53_zone" "api_domain" {
#   name = "${var.api_root_domain}."
# }

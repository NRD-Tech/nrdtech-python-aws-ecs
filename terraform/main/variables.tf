variable "aws_region" {
  type = string
}

variable "app_ident" {
  description = "Identifier of the application"
  type        = string
}

variable "app_ident_without_env" {
    description = "Identifier of the application that doesn't include the environment"
    type = string
}

variable "environment" {
  type        = string
}

variable "code_hash_file" {
  description = "Filename of the code hash file"
  type        = string
}

variable "app_cpu" {
  description = "ECS CPU"
  type        = number
}

variable "app_memory" {
  description = "ECS Memory"
  type        = number
}

variable "ecs_cluster_arn" {
  description = "ECS Cluster ARN"
  type        = string
}

variable "sns_topic_name" {
  type = string
}

variable "alarm_after_n_minutes_without_success" {
  type = string
}

##################################################
# API Gateway variables
##################################################
variable "api_domain" {
  type = string
}

variable "api_root_domain" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "app_ident" {
  description = "Identifier of the application"
  type        = string
}

variable "app_ident_without_env" {
  description = "Identifier of the application that doesn't include the environment"
  type        = string
}

variable "environment" {
  type = string
}

variable "code_hash_file" {
  description = "Filename of the code hash file"
  type        = string
}

variable "launch_type" {
  description = "Launch type for ECS (FARGATE, FARGATE_SPOT, or EC2)"
  default     = "FARGATE"
}

variable "app_cpu" {
  description = "ECS CPU"
  type        = number
}

variable "app_memory" {
  description = "ECS Memory"
  type        = number
}

variable "desired_count" {
  description = "Number of desired instances for a service task"
  type        = number
  default     = 1
}

variable "cpu_architecture" {
  description = "X86_64 or ARM64"
  type        = string
}

##################################################
# Trigger type: ecs_eventbridge or ecs_service
# Set in .env.global / .env.<env>. Use "none" only for two-phase apply when switching triggers.
##################################################
variable "trigger_type" {
  description = "ECS trigger: ecs_eventbridge (scheduled task) or ecs_service (always-on with ALB). Use 'none' only for internal two-phase apply."
  type        = string
  default     = "ecs_eventbridge"
}

##################################################
# API / ALB variables (only when trigger_type = ecs_service and using custom domain)
##################################################
variable "api_domain" {
  type    = string
  default = ""
}

variable "api_root_domain" {
  type    = string
  default = ""
}

##################################################
# Code Artifact
##################################################
variable "codeartifact_token" {
  description = "CodeArtifact token for authentication"
  type        = string
  default     = ""
}

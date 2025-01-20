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

variable desired_count {
  description = "Number of desired instances for a service task"
  type = number
  default = 1
}

variable "ecs_cluster_arn" {
  description = "ECS Cluster ARN"
  type        = string
}

variable "cpu_architecture" {
  description = "X86_64 or ARM64"
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

##################################################
# Code Artifact
##################################################
variable "codeartifact_token" {
  description = "CodeArtifact token for authentication"
  type        = string
  default = ""
}

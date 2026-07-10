variable "AWS_REGION" {
  type = string
}

variable "APP_IDENT" {
  description = "Identifier of the application"
  type        = string
}

variable "APP_IDENT_WITHOUT_ENV" {
  description = "Repository identifier (no environment suffix). Used as the Repository cost tag."
  type        = string
}

variable "PROJECT_NAME" {
  description = "Project identifier for cross-repository cost/resource grouping. Defaults to APP_IDENT_WITHOUT_ENV when empty."
  type        = string
  default     = ""
}

variable "MANAGE_PROJECT_RESOURCE_GROUP" {
  description = "When 'true', create rg-project-{PROJECT_NAME}-{ENVIRONMENT}. When empty, defaults to true only if PROJECT_NAME equals APP_IDENT_WITHOUT_ENV. Set 'false' on secondary repos that share a Project."
  type        = string
  default     = ""
}

variable "ENVIRONMENT" {
  type = string
}

variable "CODE_HASH_FILE" {
  description = "Filename of the code hash file"
  type        = string
}

variable "LAUNCH_TYPE" {
  description = "Launch type for ECS (FARGATE, FARGATE_SPOT, or EC2)"
  default     = "FARGATE"
}

variable "APP_CPU" {
  description = "ECS CPU"
  type        = number
}

variable "APP_MEMORY" {
  description = "ECS Memory"
  type        = number
}

variable "MIN_COUNT" {
  description = "Minimum number of desired instances for a service task"
  type        = number
  default     = 1
}

variable "MAX_COUNT" {
  description = "Maximum number of desired instances for a service task"
  type        = number
  default     = 100
}

variable "CPU_ARCHITECTURE" {
  description = "X86_64 or ARM64"
  type        = string
}

variable "VPC_NAME" {
  description = "Optional: tag Name of VPC to use. Empty string = default VPC. Set in config.global / config.<env>."
  type        = string
  default     = ""
}

##################################################
# Trigger type: ecs_eventbridge, ecs_api_service, ecs_internal_api_service, or ecs_background_service.
# Switching triggers uses a two-phase apply to avoid cycles.
##################################################
variable "trigger_type" {
  description = "ECS trigger: ecs_eventbridge (scheduled), ecs_api_service (public ALB + service), ecs_internal_api_service (internal ALB + service, VPC-only), or ecs_background_service (service, no ALB). Set in config.global / config.<env>. Use 'none' only for internal two-phase apply."
  type        = string
  default     = "ecs_eventbridge"
}

##################################################
# API service variables (only when trigger_type = ecs_api_service / ecs_internal_api_service)
##################################################
variable "API_DOMAIN" {
  type    = string
  default = ""
}

variable "API_ROOT_DOMAIN" {
  type    = string
  default = ""
}

##################################################
# Code Artifact
##################################################
variable "CODEARTIFACT_TOKEN" {
  description = "CodeArtifact token for authentication"
  type        = string
  default = ""
}

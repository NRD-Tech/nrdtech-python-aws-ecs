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

variable "API_ALLOWED_CIDRS" {
  description = <<-EOT
    CIDRs allowed to reach the ALB on 80/443. Set this in config.<env> to restrict a
    public API to corporate/VPN/NAT ranges. Empty = fall back to the trigger default:
    the VPC CIDR for ecs_internal_api_service, the public internet for ecs_api_service
    (an internet-facing API is that trigger's purpose). Tasks are never reachable
    directly - the ALB is the only ingress path in either case.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.API_ALLOWED_CIDRS : can(cidrhost(c, 0))])
    error_message = "API_ALLOWED_CIDRS entries must be valid CIDR blocks, e.g. 203.0.113.0/24."
  }
}

##################################################
# Task egress
##################################################
variable "TASK_EXTRA_EGRESS_RULES" {
  description = <<-EOT
    Extra outbound rules for ECS tasks, on top of the baseline (443 to anywhere for AWS
    endpoints and HTTPS APIs, all protocols to the VPC CIDR). Use this for dependencies
    on non-443 ports outside the VPC, e.g. an external Postgres:
      [{ description = "External Postgres", from_port = 5432, to_port = 5432, protocol = "tcp", cidr_blocks = ["203.0.113.10/32"] }]
  EOT
  type = list(object({
    description = string
    from_port   = number
    to_port     = number
    protocol    = string
    cidr_blocks = list(string)
  }))
  default = []

  validation {
    condition = alltrue([
      for r in var.TASK_EXTRA_EGRESS_RULES : alltrue([for c in r.cidr_blocks : can(cidrhost(c, 0))])
    ])
    error_message = "TASK_EXTRA_EGRESS_RULES cidr_blocks entries must be valid CIDR blocks."
  }
}

##################################################
# Code Artifact
##################################################
variable "CODEARTIFACT_TOKEN" {
  description = "CodeArtifact token for authentication"
  type        = string
  default = ""
}

variable "ALERT_EMAIL" {
  description = "Optional email subscribed to the alerts SNS topic. Empty = no subscription."
  type        = string
  default     = ""
}

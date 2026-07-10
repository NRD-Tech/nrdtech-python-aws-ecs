# Architecture: Python AWS ECS

## Overview

This template runs a **Python 3.14** app on **AWS ECS (Fargate)**. The app is packaged as a Docker image in ECR. One trigger mode is active at a time, selected by **`trigger_type`** in `config.global`:

- **ecs_eventbridge** – EventBridge cron runs the ECS task on a schedule (with SQS DLQ). No ECS Service or ALB.
- **ecs_api_service** (legacy alias `ecs_service`) – ECS Service behind a public Application Load Balancer (optional HTTPS + Route53 when `API_DOMAIN` / `API_ROOT_DOMAIN` are set).
- **ecs_internal_api_service** – Same, but the ALB is internal (VPC-only, private subnets).
- **ecs_background_service** – ECS Service with no ALB (long-running worker).

All Terraform is active; which resources are created is gated by `var.trigger_type` (no commented-out blocks). Switching triggers is done by changing `trigger_type` and re-deploying; a two-phase apply (trigger → `none` → desired trigger) runs automatically if Terraform reports a cycle.

## Technology stack

| Layer           | Technology                    |
|----------------|-------------------------------|
| Runtime        | Python 3.14, Poetry           |
| Container      | Docker (slim base)            |
| Orchestration  | AWS ECS (Fargate / Fargate Spot) |
| Registry       | AWS ECR                       |
| IaC            | Terraform (single main stack) |
| CI/CD          | GitHub Actions                |
| State          | Terraform state in S3         |
| Grouping       | Tags + AWS Resource Groups    |

## Components

- **Always created:** ECS cluster, ECS task definition, ECR repo, image build/push (Terraform `null_resource`), task execution role, task role, CloudWatch log group, Resource Groups (`rg-{repo}-{env}` and optionally `rg-project-{project}-{env}`).
- **Tags on all resources:** `Environment`, `Repository`, `Project` (for Cost Explorer and Resource Groups).
- **ECS services:** `enable_ecs_managed_tags` + `propagate_tags = SERVICE` so running tasks inherit tags.
- **EventBridge RunTask:** `propagate_tags = TASK_DEFINITION` so scheduled tasks inherit tags.
- **When `trigger_type = "ecs_eventbridge"`:** EventBridge rule, EventBridge target, SQS DLQ, IAM role for EventBridge.
- **When `trigger_type = "ecs_api_service"` (legacy `ecs_service`):** Security groups (ECS + ALB), public ALB, target group, HTTP listener, ECS Service. If `API_DOMAIN` and `API_ROOT_DOMAIN` are set: Route53 zone data, ACM certificate, validation records, HTTPS listener, Route53 ALB alias.
- **When `trigger_type = "ecs_internal_api_service"`:** Same as `ecs_api_service`, but the ALB is internal, placed in private subnets (falls back to all VPC subnets on the default VPC), ALB ingress is limited to the VPC CIDR, and the app port only accepts traffic from the ALB security group.
- **When the service trigger is active and `ENVIRONMENT = "prod"`:** Optional CloudWatch alarm and SNS topic (see `cloudwatch_alarm.tf`).

## Deploy flow

1. **GitHub Actions:** Push to `main` → staging deploy. Release → prod deploy. Tags `destroy-staging-*` / `destroy-prod-*` → destroy. Or use **Actions → Run workflow** (`workflow_dispatch`) with environment + deploy/destroy.
2. **CLI:** `ENVIRONMENT=staging ./deploy.sh` or `ENVIRONMENT=staging ./deploy.sh -d`.
3. **Terraform main:** Single stack — ECR, Docker build/push, ECS, Resource Groups, plus EventBridge or ECS Service/ALB depending on `trigger_type`.

## Application modes

- **Basic task** (default): `python app/main.py`. Suited for EventBridge or one-off runs.
- **FastAPI service** (optional): Uncomment in `app/main.py` and Dockerfile; Uvicorn on port 8080 with `/ping`. Use when running as ECS Service behind the ALB.

## Prerequisites

- AWS account with OIDC and S3 backend for Terraform state.
- VPC with subnets tagged with `*public*` / `*private*` when using EventBridge or ECS Service.
- In `.github/workflows/github_flow.yml`, role and region are read from `config.global` (Load configuration step); set `AWS_ROLE_ARN` and `AWS_DEFAULT_REGION` there.

For more detail on local run, deploy, and CI/CD, see **README.md**.

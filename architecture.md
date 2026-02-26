# Architecture: Python AWS ECS

## Overview

This template runs a **Python 3.12** app on **AWS ECS (Fargate)**. The app is packaged as a Docker image in ECR. One of two trigger modes is active at a time, selected by **`TRIGGER_TYPE`** in `.env.global`:

- **ecs_eventbridge** – EventBridge cron runs the ECS task on a schedule (with SQS DLQ). No ECS Service or ALB.
- **ecs_service** – ECS Service behind an Application Load Balancer (optional HTTPS + Route53 when `api_domain` / `api_root_domain` are set). No EventBridge rule.

All Terraform is active; which resources are created is gated by `var.trigger_type` (no commented-out blocks). Switching triggers is done by changing `TRIGGER_TYPE` and re-deploying; a two-phase apply (trigger → `none` → desired trigger) runs automatically if Terraform reports a cycle.

## Technology stack

| Layer           | Technology                    |
|----------------|-------------------------------|
| Runtime        | Python 3.12, Poetry           |
| Container      | Docker (slim base)            |
| Orchestration  | AWS ECS (Fargate / Fargate Spot) |
| Registry       | AWS ECR                       |
| IaC            | Terraform (bootstrap + main)  |
| CI/CD          | GitHub Actions                |
| State          | Terraform state in S3         |

## Components

- **Always created:** ECS cluster, ECS task definition, ECR repo, image build/push (Terraform `null_resource`), task execution role, task role, CloudWatch log group, App Registry (bootstrap).
- **When `trigger_type = "ecs_eventbridge"`:** EventBridge rule, EventBridge target, SQS DLQ, IAM role for EventBridge.
- **When `trigger_type = "ecs_service"`:** Security groups (ECS + ALB), ALB, target group, HTTP listener, ECS Service. If `api_domain` and `api_root_domain` are set: Route53 zone data, ACM certificate, validation records, HTTPS listener, Route53 ALB alias.
- **When `trigger_type = "ecs_service"` and `environment = "prod"`:** Optional CloudWatch alarm and SNS topic (see `cloudwatch_alarm.tf`).

## Deploy flow

1. **GitHub Actions:** On push to `main`: test then `ENVIRONMENT=staging ./deploy.sh`. On tag `v*`: test then `ENVIRONMENT=prod ./deploy.sh`. Destroy via tags `destroy-staging-*` and `destroy-prod-*`.
2. **deploy.sh:** Sources `.env.global`, `.env.<staging|prod>`, `.env.terraform`, then runs Terraform bootstrap, then Terraform main (or destroy with `-d`).
3. **Terraform main:** ECR, Docker build/push, ECS cluster, task definition, IAM, CloudWatch; plus EventBridge or ECS Service/ALB (and optional domain) depending on `trigger_type`.

## Application modes

- **Basic task** (default): `python app/main.py`. Suited for EventBridge or one-off runs.
- **FastAPI service** (optional): Uncomment in `app/main.py` and Dockerfile; Uvicorn on port 8080 with `/ping`. Use when running as ECS Service behind the ALB.

## Prerequisites

- AWS account with OIDC and S3 backend for Terraform state.
- VPC with subnets tagged with `*public*` / `*private*` when using EventBridge or ECS Service.
- In `.github/workflows/github_flow.yml`, role and region are read from `.env.global` (Load configuration step); set `AWS_ROLE_ARN` and `AWS_DEFAULT_REGION` there.

For more detail on local run, deploy, and CI/CD, see **README.md**.

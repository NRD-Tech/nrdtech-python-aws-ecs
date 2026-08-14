terraform {
  required_version = "~> 1.10"
  required_providers {

    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.81.0"
    }
  }
}

provider "aws" {
  region = var.AWS_REGION
  default_tags {
    tags = local.common_tags
  }
}

# Sometimes we specifically need us-east-1 for some resources
provider "aws" {
  alias  = "useast1"
  region = "us-east-1"
  default_tags {
    tags = local.common_tags
  }
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

#############################
# VPC: default when VPC_NAME is empty, else lookup by tag Name
#############################
data "aws_vpc" "selected" {
  count  = var.VPC_NAME != "" ? 1 : 0
  filter {
    name   = "tag:Name"
    values = [var.VPC_NAME]
  }
}

data "aws_vpc" "selected_default" {
  count   = var.VPC_NAME == "" ? 1 : 0
  default = true
}

locals {
  vpc_id   = var.VPC_NAME != "" ? data.aws_vpc.selected[0].id : data.aws_vpc.selected_default[0].id
  vpc_cidr = var.VPC_NAME != "" ? data.aws_vpc.selected[0].cidr_block : data.aws_vpc.selected_default[0].cidr_block

  # Public/private split via map-public-ip-on-launch, with fallback to all subnets when
  # one side is empty (e.g. the default VPC, where every subnet auto-assigns public IPs).
  public_subnets_or_all  = length(data.aws_subnets.public.ids) > 0 ? data.aws_subnets.public.ids : data.aws_subnets.subnets.ids
  private_subnets_or_all = length(data.aws_subnets.private.ids) > 0 ? data.aws_subnets.private.ids : data.aws_subnets.subnets.ids

  # Baseline task egress, shared by the API and background service security groups.
  # Tasks need outbound 443 for ECR pulls, CloudWatch Logs, Secrets Manager and most
  # third-party APIs, plus unrestricted reach to in-VPC dependencies (RDS, Redis, ...).
  # Anything else - an external database port, SMTP, a partner on a custom port - is an
  # explicit opt-in via TASK_EXTRA_EGRESS_RULES rather than a blanket allow-all.
  task_base_egress_rules = [
    {
      description = "HTTPS to AWS service endpoints and external APIs"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
    {
      description = "All protocols to in-VPC dependencies"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
      cidr_blocks = [local.vpc_cidr]
    },
  ]

  task_egress_rules = concat(local.task_base_egress_rules, var.TASK_EXTRA_EGRESS_RULES)

  # Standalone egress rules take a single CIDR each, so flatten to one entry per
  # (rule, cidr). Keys are derived from the rule itself, not a list index, so adding a
  # rule doesn't churn the others. "-1" (all protocols) must leave the ports unset.
  task_egress_rule_map = {
    for r in flatten([
      for rule in local.task_egress_rules : [
        for cidr in rule.cidr_blocks : {
          key         = "${rule.protocol}_${rule.from_port}_${rule.to_port}_${cidr}"
          description = rule.description
          ip_protocol = rule.protocol
          cidr_ipv4   = cidr
          from_port   = rule.protocol == "-1" ? null : rule.from_port
          to_port     = rule.protocol == "-1" ? null : rule.to_port
        }
      ]
    ]) : r.key => r
  }
}

data "aws_subnets" "subnets" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}
data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}
data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
  filter {
    name   = "map-public-ip-on-launch"
    values = ["false"]
  }
}
data "aws_route_tables" "private" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }

  filter {
    name   = "association.subnet-id"
    values = data.aws_subnets.private.ids
  }
}

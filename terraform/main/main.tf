terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.81.0"
    }
  }
}

provider "aws" {
  region  = var.AWS_REGION
  default_tags {
    tags = data.terraform_remote_state.app_bootstrap.outputs.app_tags
  }
}

# Sometimes we specifically need us-east-1 for some resources
provider "aws" {
  alias  = "useast1"
  region = "us-east-1"
  default_tags {
    tags = data.terraform_remote_state.app_bootstrap.outputs.app_tags
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

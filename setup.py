#!/usr/bin/env python3
"""
Setup for AWS ECS (Python) template.
Configures app type (api | background_service | scheduled),
config.global / config.staging / config.prod, and Python source/Dockerfile.
Auto-discovers OIDC role, Terraform state bucket, and Route53 domains.

Run from project root:  python3 setup.py [--app-type ...] [options]
Works on macOS and Windows (Python 3.6+). Safe to re-run.
"""

from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_GLOBAL = os.path.join(SCRIPT_DIR, "config.global")
CONFIG_STAGING = os.path.join(SCRIPT_DIR, "config.staging")
CONFIG_PROD = os.path.join(SCRIPT_DIR, "config.prod")
MAIN_PY_PATH = os.path.join(SCRIPT_DIR, "app", "main.py")
DOCKERFILE_PATH = os.path.join(SCRIPT_DIR, "Dockerfile")

APP_TYPES = ("api", "background_service", "scheduled")

TRIGGER_TYPE_MAP = {
    "api": "ecs_api_service",
    "background_service": "ecs_background_service",
    "scheduled": "ecs_eventbridge",
}
TRIGGER_TYPE_REVERSE = {v: k for k, v in TRIGGER_TYPE_MAP.items()}
# Legacy alias from older template
TRIGGER_TYPE_REVERSE["ecs_service"] = "api"

OIDC_FEDERATION = "token.actions.githubusercontent.com"
TERRAFORM_STATE_BUCKET_PLACEHOLDER = "mycompany-terraform-state"
AWS_ROLE_ARN_PLACEHOLDER_ACCOUNT = "1234567890"

# ---------------------------------------------------------------------------
# main.py templates
# ---------------------------------------------------------------------------
MAIN_PY_API = '''\
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()


@app.get("/ping")
async def ping():
    return JSONResponse(content={"message": "pong"})


@app.get("/healthcheck")
async def healthcheck():
    return JSONResponse(status_code=200, content={"status": "ok"})
'''

MAIN_PY_TASK = '''\
def main():
    print("Hello World")


if __name__ == "__main__":
    main()
'''

# ---------------------------------------------------------------------------
# Dockerfile CMD templates
# ---------------------------------------------------------------------------
DOCKERFILE_CMD_API = (
    '# Expose the port the app will run on\n'
    'EXPOSE 8080\n'
    '# Command to run the application using Uvicorn\n'
    'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", '
    '"--workers", "4", "--loop", "uvloop", "--http", "httptools", "--log-config", "logging_config.json"]\n'
)

DOCKERFILE_CMD_TASK = 'CMD ["python", "app/main.py"]\n'


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------
def _parse_export_file(path):
    """Parse shell ``export KEY=value`` lines into a dict (quotes stripped)."""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("export ") or "=" not in line:
                continue
            rest = line[7:].strip()
            key, _, val = rest.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                out[key] = val
    return out


def read_current_config():
    current = {}
    # Try both config.* (new) and .env.* (legacy) naming
    for global_path in [CONFIG_GLOBAL, os.path.join(SCRIPT_DIR, ".env.global")]:
        g = _parse_export_file(global_path)
        if g:
            current["app_name"] = g.get("APP_IDENT_WITHOUT_ENV", "")
            current["terraform_state_bucket"] = g.get("TERRAFORM_STATE_BUCKET", "")
            current["aws_region"] = g.get("AWS_DEFAULT_REGION", "us-west-2")
            current["aws_role_arn"] = g.get("AWS_ROLE_ARN", "")
            current["app_cpu"] = g.get("APP_CPU", "256")
            current["app_memory"] = g.get("APP_MEMORY", "512")
            current["launch_type"] = g.get("LAUNCH_TYPE", "FARGATE")
            current["cpu_architecture"] = g.get("CPU_ARCHITECTURE", "X86_64")
            raw_tt = g.get("trigger_type", g.get("TRIGGER_TYPE", "ecs_eventbridge"))
            current["app_type"] = TRIGGER_TYPE_REVERSE.get(raw_tt, "scheduled")
            current["desired_count"] = g.get("DESIRED_COUNT", "1")
            current["vpc_name"] = g.get("VPC_NAME", "")
            break
    for staging_path in [CONFIG_STAGING, os.path.join(SCRIPT_DIR, ".env.staging")]:
        s = _parse_export_file(staging_path)
        if s:
            current["api_root_domain"] = s.get("API_ROOT_DOMAIN", "")
            current["api_domain_staging"] = s.get("API_DOMAIN", "")
            break
    for prod_path in [CONFIG_PROD, os.path.join(SCRIPT_DIR, ".env.prod")]:
        p = _parse_export_file(prod_path)
        if p:
            current["api_domain_prod"] = p.get("API_DOMAIN", "")
            break
    return current


# ---------------------------------------------------------------------------
# AWS credentials
# ---------------------------------------------------------------------------
def _has_credentials():
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE"):
        return True
    creds_path = os.path.expanduser(os.path.join("~", ".aws", "credentials"))
    if os.path.isfile(creds_path):
        with open(creds_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == "[default]":
                    return True
    return False


def prompt_for_aws_credentials():
    print("\nAWS credentials (used to discover Terraform bucket, OIDC role, etc.)")
    choice = input("Use (1) AWS profile or (2) access key/secret? [1]: ").strip() or "1"
    if choice == "2":
        key = input("AWS_ACCESS_KEY_ID: ").strip()
        secret = input("AWS_SECRET_ACCESS_KEY: ").strip()
        if key:
            os.environ["AWS_ACCESS_KEY_ID"] = key
        if secret:
            os.environ["AWS_SECRET_ACCESS_KEY"] = secret
        os.environ.pop("AWS_PROFILE", None)
    else:
        profile = input("AWS profile name: ").strip()
        if profile:
            os.environ["AWS_PROFILE"] = profile
        os.environ.pop("AWS_ACCESS_KEY_ID", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)


def ensure_aws_credentials():
    if _has_credentials():
        return
    print("No AWS credentials found (AWS_PROFILE, AWS_ACCESS_KEY_ID/SECRET, or ~/.aws/credentials [default]).", file=sys.stderr)
    print("Run without --non-interactive to be prompted, or export credentials first.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# AWS resource discovery (boto3 preferred, CLI fallback)
# ---------------------------------------------------------------------------
def _try_boto3_discover(region):
    out = {"oidc_roles": [], "terraform_buckets": [], "route53_domains": []}
    try:
        import boto3
    except ImportError:
        return out
    try:
        session = boto3.Session(region_name=region)
        iam = session.client("iam")
        for page in iam.get_paginator("list_roles").paginate():
            for role in page.get("Roles", []):
                name = role.get("RoleName")
                arn = role.get("Arn", "")
                try:
                    doc = iam.get_role(RoleName=name).get("Role", {}).get("AssumeRolePolicyDocument", {})
                    for s in doc.get("Statement", []):
                        fed = (s.get("Principal") or {}).get("Federated") or ""
                        if isinstance(fed, list):
                            fed = " ".join(fed)
                        if OIDC_FEDERATION in str(fed):
                            out["oidc_roles"].append({"arn": arn, "name": name})
                            break
                except Exception:
                    pass
    except Exception:
        pass
    try:
        s3 = session.client("s3")
        for b in s3.list_buckets().get("Buckets", []):
            name = b.get("Name", "")
            if "terraform" in name.lower():
                out["terraform_buckets"].append(name)
    except Exception:
        pass
    try:
        r53 = session.client("route53")
        for zone in r53.list_hosted_zones().get("HostedZones", []):
            name = zone.get("Name", "").rstrip(".")
            if name:
                out["route53_domains"].append(name)
    except Exception:
        pass
    return out


def _run_aws_cli(cmd):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            env={**os.environ, "AWS_DEFAULT_OUTPUT": "json"},
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return {}


def _try_cli_discover(region):
    out = {"oidc_roles": [], "terraform_buckets": [], "route53_domains": []}
    data = _run_aws_cli(["aws", "iam", "list-roles", "--max-items", "100"])
    for role in data.get("Roles", []):
        arn = role.get("Arn", "")
        name = role.get("RoleName", "")
        if not name:
            continue
        detail = _run_aws_cli(["aws", "iam", "get-role", "--role-name", name])
        doc = (detail.get("Role") or {}).get("AssumeRolePolicyDocument") or {}
        for s in doc.get("Statement", []):
            fed = (s.get("Principal") or {}).get("Federated") or ""
            if OIDC_FEDERATION in str(fed):
                out["oidc_roles"].append({"arn": arn, "name": name})
                break
    for b in _run_aws_cli(["aws", "s3api", "list-buckets"]).get("Buckets", []):
        name = b.get("Name", "")
        if name and "terraform" in name.lower():
            out["terraform_buckets"].append(name)
    for z in _run_aws_cli(["aws", "route53", "list-hosted-zones"]).get("HostedZones", []):
        name = (z.get("Name") or "").rstrip(".")
        if name:
            out["route53_domains"].append(name)
    return out


def discover_aws_resources(region):
    discovered = _try_boto3_discover(region)
    if not discovered["oidc_roles"] and not discovered["terraform_buckets"]:
        discovered = _try_cli_discover(region)
    return discovered


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def _choose_from_list(prompt_msg, items, allow_custom=True):
    if not items:
        return input("{}: ".format(prompt_msg)).strip()
    print(prompt_msg)
    for i, x in enumerate(items, 1):
        label = x.get("arn") or x.get("name") or str(x) if isinstance(x, dict) else str(x)
        print("  {}: {}".format(i, label))
    if allow_custom:
        print("  0: Enter value manually")
    choice = input("Choice [1]: ").strip() or "1"
    try:
        idx = int(choice)
        if idx == 0 and allow_custom:
            return input("Value: ").strip()
        if 1 <= idx <= len(items):
            x = items[idx - 1]
            return x.get("arn") if isinstance(x, dict) and "arn" in x else str(x)
    except ValueError:
        pass
    return choice


def _is_placeholder_bucket(name):
    s = (name or "").strip()
    return not s or s == TERRAFORM_STATE_BUCKET_PLACEHOLDER


def _is_placeholder_role(arn):
    a = (arn or "").strip()
    return not a or AWS_ROLE_ARN_PLACEHOLDER_ACCOUNT in a


def _effective(current, key, placeholder_check=None):
    val = current.get(key, "")
    if placeholder_check and placeholder_check(val):
        return ""
    return val or ""


def prompt(msg, default=""):
    if default:
        s = input("{} [{}]: ".format(msg, default)).strip()
        return s if s else default
    while True:
        s = input("{}: ".format(msg)).strip()
        if s:
            return s


# ---------------------------------------------------------------------------
# Config writers
# ---------------------------------------------------------------------------
def write_config_global(args):
    vpc_line = "export VPC_NAME={}\n".format(args.vpc_name) if getattr(args, "vpc_name", "") else "# export VPC_NAME=my-standard-vpc\n"
    trigger = TRIGGER_TYPE_MAP.get(args.app_type, "ecs_eventbridge")
    content = """\
#########################################################
# Configuration
#########################################################
# Used to identify the application in AWS resources | allowed characters: a-zA-Z0-9-_
# NOTE: This must be no longer than 20 characters long
export APP_IDENT_WITHOUT_ENV={app_name}
export APP_IDENT="${{APP_IDENT_WITHOUT_ENV}}-${{ENVIRONMENT}}"
export TERRAFORM_STATE_IDENT=$APP_IDENT

# This is the AWS S3 bucket in which you are storing your terraform state files
# - This must exist before deploying
export TERRAFORM_STATE_BUCKET={terraform_state_bucket}

# This is the AWS region in which the application will be deployed
export AWS_DEFAULT_REGION={aws_region}

# OIDC Deployment role
export AWS_ROLE_ARN={aws_role_arn}
export AWS_WEB_IDENTITY_TOKEN_FILE=$(pwd)/web-identity-token

# ECS Task cpu and memory settings
export APP_CPU={app_cpu}  # cpu
export APP_MEMORY={app_memory}  # memory in MB

# This is either EC2, FARGATE, or FARGATE_SPOT
export LAUNCH_TYPE={launch_type}

# Must be one of these: X86_64, ARM64
# NOTE: If deploying to EC2 you must choose the same architecture as your instances
# NOTE2: Only GitHub supports ARM64 builds - Bitbucket doesn't
export CPU_ARCHITECTURE={cpu_architecture}

# ECS trigger type: ecs_api_service | ecs_background_service | ecs_eventbridge
export trigger_type={trigger_type}

# Number of desired tasks in an ECS Service
export DESIRED_COUNT={desired_count}

# Optional: set VPC_NAME to a tag:Name value to use a custom VPC; leave unset for default VPC
{vpc_line}
#########################################################
# Create code hash
#########################################################
export CODE_HASH_FILE=code_hash.txt
docker run --rm -v $(pwd):/workdir -w /workdir alpine sh -c \\
  "apk add --no-cache findutils coreutils && \\
   find . -type f -path './.git*' -prune -o -path './.github*' -prune -o \\( -name '*.py' -o -name '*.sh' -o -name 'Dockerfile' -o -name 'pyproject.toml' -o -name 'poetry.lock' -o -name 'config.*' \\) \\
   -exec md5sum {{}} + | sort | md5sum | cut -d ' ' -f1 > terraform/main/${{CODE_HASH_FILE}}"
"""
    with open(CONFIG_GLOBAL, "w", encoding="utf-8") as f:
        f.write(content.format(
            app_name=args.app_name,
            terraform_state_bucket=args.terraform_state_bucket,
            aws_region=args.aws_region,
            aws_role_arn=args.aws_role_arn,
            app_cpu=args.app_cpu,
            app_memory=args.app_memory,
            launch_type=args.launch_type,
            cpu_architecture=args.cpu_architecture,
            trigger_type=trigger,
            desired_count=getattr(args, "desired_count", "1"),
            vpc_line=vpc_line,
        ))
    print("Wrote config.global")


def write_config_staging(args):
    api_root = getattr(args, "api_root_domain", "") or "example.com"
    api_staging = getattr(args, "api_domain_staging", "") or "api-staging.example.com"
    content = """\
# NOTE: Variables set in here will activate only in a staging environment
# export EXAMPLE_VAR="Hello from staging"

####################################################################################################
# API Service Configuration (only needed for app type 'api')
# * The root domain MUST already exist in Route53 in your AWS account
####################################################################################################
export API_ROOT_DOMAIN={api_root_domain}
export API_DOMAIN={api_domain_staging}
"""
    with open(CONFIG_STAGING, "w", encoding="utf-8") as f:
        f.write(content.format(
            api_root_domain=api_root,
            api_domain_staging=api_staging,
        ))
    print("Wrote config.staging")


def write_config_prod(args):
    api_root = getattr(args, "api_root_domain", "") or "example.com"
    api_prod = getattr(args, "api_domain_prod", "") or "api.example.com"
    content = """\
# NOTE: Variables set in here will activate only in a production environment
# export EXAMPLE_VAR="Hello from production"

####################################################################################################
# API Service Configuration (only needed for app type 'api')
# * The root domain MUST already exist in Route53 in your AWS account
####################################################################################################
export API_ROOT_DOMAIN={api_root_domain}
export API_DOMAIN={api_domain_prod}
"""
    with open(CONFIG_PROD, "w", encoding="utf-8") as f:
        f.write(content.format(
            api_root_domain=api_root,
            api_domain_prod=api_prod,
        ))
    print("Wrote config.prod")


# ---------------------------------------------------------------------------
# Project-specific: main.py and Dockerfile
# ---------------------------------------------------------------------------
def apply_main_py(app_type):
    content = MAIN_PY_API if app_type == "api" else MAIN_PY_TASK
    with open(MAIN_PY_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    if app_type == "api":
        print("Enabled FastAPI in app/main.py (/ping, /healthcheck)")
    else:
        print("Enabled task main in app/main.py")


def apply_dockerfile(app_type):
    if not os.path.isfile(DOCKERFILE_PATH):
        return
    with open(DOCKERFILE_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find and replace everything after "COPY app ./app/" line
    cut_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("COPY app"):
            cut_idx = i + 1
            break
    if cut_idx is None:
        return

    new_tail = "\n" + (DOCKERFILE_CMD_API if app_type == "api" else DOCKERFILE_CMD_TASK)
    with open(DOCKERFILE_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines[:cut_idx])
        f.write(new_tail)
    print("Updated Dockerfile CMD for '{}'".format(app_type))


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------
def _prompt_common(args, current, discovered):
    eff_role = _effective(current, "aws_role_arn", _is_placeholder_role)
    eff_bucket = _effective(current, "terraform_state_bucket", _is_placeholder_bucket)

    if not args.aws_role_arn:
        if eff_role:
            args.aws_role_arn = eff_role
        elif discovered["oidc_roles"]:
            args.aws_role_arn = _choose_from_list("OIDC role (GitHub Actions):", discovered["oidc_roles"])
        else:
            args.aws_role_arn = prompt("OIDC role ARN", eff_role)

    if not args.terraform_state_bucket:
        if eff_bucket:
            args.terraform_state_bucket = eff_bucket
        elif discovered["terraform_buckets"]:
            args.terraform_state_bucket = _choose_from_list("Terraform state bucket:", discovered["terraform_buckets"])
        else:
            args.terraform_state_bucket = prompt("Terraform state bucket", eff_bucket)

    if not args.app_name:
        args.app_name = prompt("App name (APP_IDENT_WITHOUT_ENV, max 20 chars)", current.get("app_name", ""))
    if not args.app_type:
        default_type = current.get("app_type", "scheduled")
        args.app_type = prompt("App type ({})".format(" | ".join(APP_TYPES)), default_type)
        if args.app_type not in APP_TYPES:
            print("Invalid app type '{}'. Defaulting to 'scheduled'.".format(args.app_type), file=sys.stderr)
            args.app_type = "scheduled"

    for attr, default in [
        ("app_cpu", current.get("app_cpu", "256")),
        ("app_memory", current.get("app_memory", "512")),
        ("launch_type", current.get("launch_type", "FARGATE")),
        ("cpu_architecture", current.get("cpu_architecture", "X86_64")),
        ("aws_region", current.get("aws_region", "us-west-2")),
    ]:
        if not getattr(args, attr):
            setattr(args, attr, default)

    if args.app_type == "api":
        if not args.api_root_domain and discovered["route53_domains"]:
            args.api_root_domain = _choose_from_list("API root domain (Route53):", discovered["route53_domains"])
        if not args.api_root_domain:
            args.api_root_domain = prompt("API root domain (must exist in Route53)", current.get("api_root_domain", "example.com"))
        if not args.api_domain_staging:
            args.api_domain_staging = prompt("API domain for staging", current.get("api_domain_staging", "api-staging." + args.api_root_domain))
        if not args.api_domain_prod:
            args.api_domain_prod = prompt("API domain for prod", current.get("api_domain_prod", "api." + args.api_root_domain))

    if not getattr(args, "desired_count", ""):
        args.desired_count = current.get("desired_count", "1")
    if not getattr(args, "vpc_name", ""):
        args.vpc_name = current.get("vpc_name", "")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Configure this AWS ECS (Python) project.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--app-type", choices=APP_TYPES, help="api | background_service | scheduled")
    parser.add_argument("--app-name", default="", help="APP_IDENT_WITHOUT_ENV (max 20 chars)")
    parser.add_argument("--terraform-state-bucket", default="", help="S3 bucket for Terraform state")
    parser.add_argument("--aws-region", default="us-west-2", help="AWS region")
    parser.add_argument("--aws-role-arn", default="", help="OIDC deployment role ARN")
    parser.add_argument("--app-cpu", default="256", help="ECS task CPU units")
    parser.add_argument("--app-memory", default="512", help="ECS task memory MB")
    parser.add_argument("--launch-type", default="FARGATE", choices=("FARGATE", "FARGATE_SPOT", "EC2"))
    parser.add_argument("--cpu-architecture", default="X86_64", choices=("X86_64", "ARM64"))
    parser.add_argument("--vpc-name", default="", help="Optional VPC tag:Name")
    parser.add_argument("--api-root-domain", default="", help="Root domain for API (api type only)")
    parser.add_argument("--api-domain-staging", default="", help="API domain for staging")
    parser.add_argument("--api-domain-prod", default="", help="API domain for prod")
    parser.add_argument("--desired-count", default="1", help="DESIRED_COUNT for ECS service")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if required args missing")
    args = parser.parse_args()

    current = read_current_config()

    if not args.non_interactive:
        prompt_for_aws_credentials()
    ensure_aws_credentials()

    region = args.aws_region or current.get("aws_region", "us-west-2")
    discovered = discover_aws_resources(region)
    if discovered["oidc_roles"] or discovered["terraform_buckets"] or discovered["route53_domains"]:
        print("Discovered AWS resources (you can select by number or enter manually).")

    if args.non_interactive:
        for attr, desc in [("app_name", "App name"), ("terraform_state_bucket", "Terraform state bucket"), ("aws_role_arn", "OIDC role ARN")]:
            if not getattr(args, attr):
                print("Error: {} required. Set --{} or run without --non-interactive.".format(desc, attr.replace("_", "-")), file=sys.stderr)
                return 1
        if not args.app_type:
            args.app_type = current.get("app_type", "scheduled")
        if args.app_type not in APP_TYPES:
            args.app_type = "scheduled"
        defaults = {"app_cpu": "256", "app_memory": "512", "launch_type": "FARGATE", "cpu_architecture": "X86_64"}
        for attr, default in defaults.items():
            if not getattr(args, attr):
                setattr(args, attr, current.get(attr, default))
        if args.app_type == "api":
            args.api_root_domain = args.api_root_domain or current.get("api_root_domain", "example.com")
            args.api_domain_staging = args.api_domain_staging or current.get("api_domain_staging", "api-staging.example.com")
            args.api_domain_prod = args.api_domain_prod or current.get("api_domain_prod", "api.example.com")
        if not getattr(args, "desired_count", ""):
            args.desired_count = current.get("desired_count", "1")
        if not getattr(args, "vpc_name", ""):
            args.vpc_name = ""
    else:
        _prompt_common(args, current, discovered)

    write_config_global(args)
    write_config_staging(args)
    write_config_prod(args)
    apply_main_py(args.app_type)
    apply_dockerfile(args.app_type)
    print("Setup complete. Edit config.global (and config.staging/config.prod) if needed, then deploy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

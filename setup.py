#!/usr/bin/env python3
"""
Setup for AWS ECS (Python) template.
Configures app type (api | internal_api | background_service | scheduled),
config.global / config.staging / config.prod, and Python source/Dockerfile.
Auto-discovers OIDC role, Terraform state bucket, and Route53 domains.

Run from project root:  python3 setup.py [--app-type ...] [options]
Works on macOS and Windows (Python 3.6+). Safe to re-run.
"""

from __future__ import print_function

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_GLOBAL = os.path.join(SCRIPT_DIR, "config.global")
CONFIG_STAGING = os.path.join(SCRIPT_DIR, "config.staging")
CONFIG_PROD = os.path.join(SCRIPT_DIR, "config.prod")
MAIN_PY_PATH = os.path.join(SCRIPT_DIR, "app", "main.py")
DOCKERFILE_PATH = os.path.join(SCRIPT_DIR, "Dockerfile")
GITHUB_WORKFLOWS = os.path.join(SCRIPT_DIR, ".github", "workflows")
WORKFLOW_DISABLED = os.path.join(GITHUB_WORKFLOWS, "github_flow.yml.disabled")
WORKFLOW_ENABLED = os.path.join(GITHUB_WORKFLOWS, "github_flow.yml")

APPROVAL_MODES = ("dispatch", "environment")
DEFAULT_APPROVAL_MODE = "dispatch"

APP_TYPES = ("api", "internal_api", "background_service", "scheduled")

TRIGGER_TYPE_MAP = {
    "api": "ecs_api_service",
    "internal_api": "ecs_internal_api_service",
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
    g = _parse_export_file(CONFIG_GLOBAL)
    if g:
        current["app_name"] = g.get("APP_IDENT_WITHOUT_ENV", "")
        current["project_name"] = g.get("PROJECT_NAME", "") or g.get("APP_IDENT_WITHOUT_ENV", "")
        current["manage_project_resource_group"] = g.get("MANAGE_PROJECT_RESOURCE_GROUP", "")
        current["terraform_state_bucket"] = g.get("TERRAFORM_STATE_BUCKET", "")
        current["aws_region"] = g.get("AWS_DEFAULT_REGION", "us-west-2")
        current["aws_role_arn"] = g.get("AWS_ROLE_ARN", "")
        current["app_cpu"] = g.get("APP_CPU", "256")
        current["app_memory"] = g.get("APP_MEMORY", "512")
        current["launch_type"] = g.get("LAUNCH_TYPE", "FARGATE")
        current["cpu_architecture"] = g.get("CPU_ARCHITECTURE", "X86_64")
        raw_tt = g.get("trigger_type", "ecs_eventbridge")
        current["app_type"] = TRIGGER_TYPE_REVERSE.get(raw_tt, "scheduled")
        current["vpc_name"] = g.get("VPC_NAME", "")
        current["github_approval_mode"] = g.get("GITHUB_APPROVAL_MODE", DEFAULT_APPROVAL_MODE)
        current["github_org"] = g.get("GITHUB_ORG", "")
    s = _parse_export_file(CONFIG_STAGING)
    if s:
        current["api_root_domain"] = s.get("API_ROOT_DOMAIN", "")
        current["api_domain_staging"] = s.get("API_DOMAIN", "")
        current["min_count"] = s.get("MIN_COUNT", "1")
        current["max_count_staging"] = s.get("MAX_COUNT", "2")
    p = _parse_export_file(CONFIG_PROD)
    if p:
        current["api_domain_prod"] = p.get("API_DOMAIN", "")
        current["max_count_prod"] = p.get("MAX_COUNT", "2")
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


def detect_probable_aws_region():
    """Best-effort region from env, boto3 session, AWS CLI, or ~/.aws/config for the active profile."""
    for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val

    try:
        import boto3

        region = boto3.Session().region_name
        if region:
            return region
    except Exception:
        pass

    profile = (os.environ.get("AWS_PROFILE") or "").strip()
    cmd = ["aws", "configure", "get", "region"]
    if profile:
        cmd.extend(["--profile", profile])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        region = (result.stdout or "").strip()
        if result.returncode == 0 and region:
            return region
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    config_path = os.path.expanduser(os.path.join("~", ".aws", "config"))
    if os.path.isfile(config_path):
        section = "profile {}".format(profile) if profile else "default"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                in_section = False
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        in_section = stripped[1:-1].strip() == section
                        continue
                    if in_section and stripped.startswith("region"):
                        _, _, val = stripped.partition("=")
                        val = val.strip().strip('"').strip("'")
                        if val:
                            return val
        except OSError:
            pass

    return ""


def resolve_aws_region(cli_region, current):
    """Prefer explicit CLI, then an already-configured project region, then profile detection."""
    if (cli_region or "").strip():
        return cli_region.strip()

    cfg = (current.get("aws_region") or "").strip()
    bucket = (current.get("terraform_state_bucket") or "").strip()
    if cfg and bucket and bucket != TERRAFORM_STATE_BUCKET_PLACEHOLDER:
        return cfg

    detected = detect_probable_aws_region()
    if detected:
        return detected
    return cfg or "us-west-2"


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


def prompt_yes_no(msg, default_no=True):
    suffix = " [y/N]: " if default_no else " [Y/n]: "
    s = input(msg + suffix).strip().lower()
    if not s:
        return not default_no
    return s in ("y", "yes")


# ---------------------------------------------------------------------------
# GitHub CLI / approval mode (Team vs Enterprise)
# ---------------------------------------------------------------------------
def find_gh_executable():
    """Locate gh on macOS/Linux/Windows without assuming PATH is perfect."""
    found = shutil.which("gh")
    if found:
        return found
    candidates = []
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.extend([
            os.path.join(pf, "GitHub CLI", "gh.exe"),
            os.path.join(pf86, "GitHub CLI", "gh.exe"),
            os.path.join(local, "Programs", "GitHub CLI", "gh.exe"),
        ])
    else:
        candidates.extend([
            "/opt/homebrew/bin/gh",
            "/usr/local/bin/gh",
            os.path.expanduser("~/.local/bin/gh"),
        ])
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def run_gh(gh, args, timeout=60):
    """Run gh; return (ok, stdout, stderr). Never raises for missing auth."""
    cmd = [gh] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, (result.stdout or "").strip(), (result.stderr or "").strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, "", str(exc)


def parse_gh_auth_accounts(status_text):
    """Parse `gh auth status` into [{'login': ..., 'active': bool}, ...]."""
    accounts = []
    current = None
    for line in (status_text or "").splitlines():
        m = re.search(r"Logged in to github\.com account (\S+)", line)
        if m:
            current = {"login": m.group(1).strip(), "active": False}
            accounts.append(current)
            continue
        if current and "Active account: true" in line:
            current["active"] = True
    return accounts


def git_remote_github_owner_repo():
    """Best-effort owner/repo from git remote origin (https or ssh)."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return "", ""
    url = (result.stdout or "").strip()
    if not url:
        return "", ""
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", url)
    if not m:
        return "", ""
    return m.group("owner"), m.group("repo")


def detect_github_org_plan(gh, org):
    """Return 'enterprise', 'team', or '' if unknown / inaccessible."""
    if not gh or not org:
        return ""
    ok, out, _ = run_gh(gh, ["api", "orgs/{}".format(org), "--jq", ".plan.name"])
    if not ok or not out:
        return ""
    name = out.strip().lower()
    if name in ("enterprise", "business"):
        return "enterprise"
    if name in ("team", "pro", "free"):
        return "team"
    return ""


def approval_mode_for_plan(plan_name):
    if plan_name == "enterprise":
        return "environment"
    return DEFAULT_APPROVAL_MODE


def ensure_gh_ready_for_org(gh, org, non_interactive):
    """
    Ensure gh works and the active account can see org.
    Handles missing gh, wrong account, and prints switch instructions (incl. Windows).
    Returns (ok, active_login, messages).
    """
    messages = []
    if not gh:
        messages.append(
            "GitHub CLI (gh) not found. Install from https://cli.github.com/ "
            "(macOS: brew install gh | Windows: winget install GitHub.cli), then re-run setup."
        )
        return False, "", messages

    ok, out, err = run_gh(gh, ["auth", "status"])
    status_text = "\n".join(x for x in (out, err) if x)
    accounts = parse_gh_auth_accounts(status_text)
    if not accounts:
        messages.append(
            "gh is installed but not logged in. Run: gh auth login\n"
            "Then re-run setup (or set --github-approval-mode manually)."
        )
        return False, "", messages

    active = next((a["login"] for a in accounts if a.get("active")), accounts[0]["login"])
    if not org:
        return True, active, messages

    ok, _, err = run_gh(gh, ["api", "orgs/{}/memberships/{}".format(org, active)])
    if ok:
        return True, active, messages

    # Wrong account or no access — try other logged-in accounts
    for acct in accounts:
        login = acct["login"]
        if login == active:
            continue
        ok_sw, _, err_sw = run_gh(gh, ["auth", "switch", "--user", login])
        if not ok_sw:
            messages.append("Could not switch gh user to {}: {}".format(login, err_sw))
            continue
        ok_m, _, _ = run_gh(gh, ["api", "orgs/{}/memberships/{}".format(org, login)])
        if ok_m:
            messages.append("Switched gh active account to {} for org {}.".format(login, org))
            return True, login, messages
        # switch back
        run_gh(gh, ["auth", "switch", "--user", active])

    other = [a["login"] for a in accounts if a["login"] != active]
    hint = (
        "Active gh user '{}' cannot access org '{}'.\n"
        "Fix with: gh auth switch --user <login>   (logged in: {})\n"
        "Or: gh auth login   then re-run setup.\n"
        "On Windows use the same commands in PowerShell or Git Bash."
    ).format(active, org, ", ".join(other) if other else "none other")
    messages.append(hint)
    if non_interactive:
        return False, active, messages
    if prompt_yes_no("Continue without GitHub API setup (manual instructions only)?", default_no=False):
        return False, active, messages
    return False, active, messages


def resolve_github_approval_settings(args, current, non_interactive):
    """
    Resolve github_org + github_approval_mode.
    Prefer CLI flags, then config, then gh org plan detection (enterprise→environment, else dispatch).
    """
    owner, _repo = git_remote_github_owner_repo()
    org = (getattr(args, "github_org", "") or current.get("github_org", "") or owner or "").strip()
    mode = (getattr(args, "github_approval_mode", "") or current.get("github_approval_mode", "") or "").strip()

    gh = find_gh_executable()
    plan = ""
    if org:
        ok, _login, msgs = ensure_gh_ready_for_org(gh, org, non_interactive)
        for m in msgs:
            print(m, file=sys.stderr)
        if ok:
            plan = detect_github_org_plan(gh, org)
            if plan:
                print("Detected GitHub org '{}' plan: {}".format(org, plan))

    if not mode:
        mode = approval_mode_for_plan(plan) if plan else DEFAULT_APPROVAL_MODE

    if not non_interactive:
        org = prompt("GitHub org (for approval-mode detection / protections)", org)
        if org and org != (getattr(args, "github_org", "") or current.get("github_org", "") or owner or "").strip():
            ok, _login, msgs = ensure_gh_ready_for_org(gh, org, non_interactive)
            for m in msgs:
                print(m, file=sys.stderr)
            if ok:
                plan = detect_github_org_plan(gh, org)
                if plan and not getattr(args, "github_approval_mode", ""):
                    mode = approval_mode_for_plan(plan)
                    print("Detected GitHub org '{}' plan: {} → approval mode {}".format(org, plan, mode))
        default_mode = mode if mode in APPROVAL_MODES else DEFAULT_APPROVAL_MODE
        mode = prompt(
            "GitHub approval mode (dispatch=Team-safe plan then manual apply; environment=Enterprise Environment reviewers)",
            default_mode,
        )

    if mode not in APPROVAL_MODES:
        print("Unknown approval mode '{}'; using {}".format(mode, DEFAULT_APPROVAL_MODE), file=sys.stderr)
        mode = DEFAULT_APPROVAL_MODE

    args.github_org = org
    args.github_approval_mode = mode
    args._gh_path = gh
    args._gh_plan = plan
    return gh, org, mode, plan


def enable_github_workflow():
    if os.path.isfile(WORKFLOW_ENABLED):
        print("GitHub workflow already enabled at {}".format(WORKFLOW_ENABLED))
        return True
    if not os.path.isfile(WORKFLOW_DISABLED):
        print("Warning: {} not found".format(WORKFLOW_DISABLED), file=sys.stderr)
        return False
    os.rename(WORKFLOW_DISABLED, WORKFLOW_ENABLED)
    print("Enabled GitHub workflow: {}".format(WORKFLOW_ENABLED))
    return True


def configure_github_protections(gh, org, mode, non_interactive):
    """Create Environments + main branch ruleset when API allows; always print manual steps."""
    owner, repo = git_remote_github_owner_repo()
    if org:
        owner = org
    if not owner or not repo:
        print(
            "\nGitHub protections (manual):\n"
            "  1. Settings → Branches/Rules: require PR + 1 review before merge to main\n"
            "  2. Settings → Environments: create 'staging' and 'production'\n"
            "  3. On Enterprise: add required reviewers on those environments "
            "(staging=developers, production=team leads; prevent self-review on production)\n"
            "  4. Team (private): use GITHUB_APPROVAL_MODE=dispatch — merge plans on push; "
            "apply via Actions → Run workflow\n"
        )
        return

    print("\nConfiguring GitHub protections for {}/{} (mode={})...".format(owner, repo, mode))
    if not gh:
        print("  Skipped API calls (gh not available). Use the manual steps below.")
    else:
        for env_name in ("staging", "production"):
            # Empty body — Team private repos reject wait_timer / required reviewers.
            try:
                result = subprocess.run(
                    [gh, "api", "-X", "PUT",
                     "repos/{}/{}/environments/{}".format(owner, repo, env_name),
                     "--input", "-"],
                    input="{}",
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    print("  Ensured environment '{}'".format(env_name))
                else:
                    err = (result.stderr or result.stdout or "").strip()
                    print("  Could not create environment '{}': {}".format(env_name, err or "unknown error"))
            except (subprocess.TimeoutExpired, OSError) as exc:
                print("  Could not create environment '{}': {}".format(env_name, exc))

        if mode == "environment":
            print(
                "  Enterprise mode: in Settings → Environments, add required reviewers "
                "on 'staging' and 'production' (prevent self-review on production)."
            )

        # Branch ruleset: require PR + reviews on main (best-effort)
        ruleset = {
            "name": "main-protection",
            "target": "branch",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "rules": [
                {"type": "pull_request", "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                }},
            ],
        }
        try:
            result = subprocess.run(
                [gh, "api", "-X", "POST", "repos/{}/{}/rulesets".format(owner, repo), "--input", "-"],
                input=json.dumps(ruleset),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                print("  Created/ensured ruleset 'main-protection' (PR + 1 review)")
            else:
                err_text = (result.stderr or result.stdout or "").strip()
                if "already exists" in err_text.lower() or "Name must be unique" in err_text:
                    print("  Ruleset 'main-protection' already exists")
                else:
                    print("  Could not create ruleset (need admin): {}".format(err_text[:300]))
        except (subprocess.TimeoutExpired, OSError) as exc:
            print("  Could not create ruleset: {}".format(exc))

    print(
        "\nManual checklist:\n"
        "  • Require PR reviews before merge to main (rulesets / branch protection)\n"
        "  • Review terraform plan in Actions (job summary) before apply\n"
        "  • dispatch mode: Actions → Run workflow → deploy after reviewing plan\n"
        "  • environment mode: approve the Environment gate on the apply job\n"
        "  • production: team-lead reviewers only\n"
    )


# ---------------------------------------------------------------------------
# Config writers
# ---------------------------------------------------------------------------
def write_config_global(args):
    vpc_line = "export VPC_NAME={}\n".format(args.vpc_name) if getattr(args, "vpc_name", "") else "# export VPC_NAME=my-standard-vpc\n"
    trigger = TRIGGER_TYPE_MAP.get(args.app_type, "ecs_eventbridge")
    project_name = getattr(args, "project_name", "") or args.app_name
    manage_project_rg = getattr(args, "manage_project_resource_group", "")
    if not manage_project_rg:
        manage_project_rg = "true" if project_name == args.app_name else "false"
    github_org = getattr(args, "github_org", "") or ""
    approval_mode = getattr(args, "github_approval_mode", "") or DEFAULT_APPROVAL_MODE
    content = """\
#########################################################
# Configuration
#########################################################
# Used to identify this repository in AWS resources | allowed characters: a-zA-Z0-9-_
# NOTE: This must be no longer than 20 characters long
# Also used as the Repository cost-allocation tag
export APP_IDENT_WITHOUT_ENV={app_name}
export APP_IDENT="${{APP_IDENT_WITHOUT_ENV}}-${{ENVIRONMENT}}"
export TERRAFORM_STATE_IDENT=$APP_IDENT

# Project name for cross-repository cost/resource grouping (Cost Explorer tag: Project).
# Use the same PROJECT_NAME on related repos (e.g. backend + frontend).
export PROJECT_NAME={project_name}

# When true, this stack creates rg-project-{{PROJECT_NAME}}-{{ENVIRONMENT}}.
# Set true on exactly one repo per Project+Environment (usually the "primary" repo).
export MANAGE_PROJECT_RESOURCE_GROUP={manage_project_resource_group}

# This is the AWS S3 bucket in which you are storing your terraform state files
# - This must exist before deploying
export TERRAFORM_STATE_BUCKET={terraform_state_bucket}

# This is the AWS region in which the application will be deployed
export AWS_DEFAULT_REGION={aws_region}
export AWS_REGION=${{AWS_DEFAULT_REGION}}

# OIDC Deployment role
export AWS_ROLE_ARN={aws_role_arn}
export AWS_WEB_IDENTITY_TOKEN_FILE=$(pwd)/web-identity-token

# GitHub Actions deploy gating (see .github/workflows/github_flow.yml)
#   dispatch    — Team-safe default: plan on push/release; apply via workflow_dispatch
#   environment — Enterprise: apply jobs wait on Environment required reviewers
export GITHUB_ORG={github_org}
export GITHUB_APPROVAL_MODE={github_approval_mode}

# ECS Task cpu and memory settings
export APP_CPU={app_cpu}  # cpu
export APP_MEMORY={app_memory}  # memory in MB

# This is either EC2, FARGATE, or FARGATE_SPOT
export LAUNCH_TYPE={launch_type}

# Must be one of these: X86_64, ARM64
# NOTE: If deploying to EC2 you must choose the same architecture as your instances
# NOTE2: Only GitHub supports ARM64 builds - Bitbucket doesn't
export CPU_ARCHITECTURE={cpu_architecture}

# ECS trigger type: ecs_api_service | ecs_internal_api_service | ecs_background_service | ecs_eventbridge
export trigger_type={trigger_type}

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
            project_name=project_name,
            manage_project_resource_group=manage_project_rg,
            terraform_state_bucket=args.terraform_state_bucket,
            aws_region=args.aws_region,
            aws_role_arn=args.aws_role_arn,
            github_org=github_org,
            github_approval_mode=approval_mode,
            app_cpu=args.app_cpu,
            app_memory=args.app_memory,
            launch_type=args.launch_type,
            cpu_architecture=args.cpu_architecture,
            trigger_type=trigger,
            vpc_line=vpc_line,
        ))
    print("Wrote config.global")


def write_config_staging(args):
    api_root = getattr(args, "api_root_domain", "") or "example.com"
    api_staging = getattr(args, "api_domain_staging", "") or "api-staging.example.com"
    content = """\
# NOTE: Variables set in here will activate only in a staging environment
# export EXAMPLE_VAR="Hello from staging"

# Optional: per-environment VPC override (tag:Name); most clients use default VPC or config.global
# export VPC_NAME=Dev

####################################################################################################
# API Service Configuration (only needed for app type 'api')
# * The root domain MUST already exist in Route53 in your AWS account
####################################################################################################
export API_ROOT_DOMAIN={api_root_domain}
export API_DOMAIN={api_domain_staging}

# Number of tasks in an ECS Service
export MIN_COUNT={min_count}
export MAX_COUNT={max_count}
"""
    with open(CONFIG_STAGING, "w", encoding="utf-8") as f:
        f.write(content.format(
            api_root_domain=api_root,
            api_domain_staging=api_staging,
            min_count=getattr(args, "min_count", "1"),
            max_count=getattr(args, "max_count_staging", "2"),
        ))
    print("Wrote config.staging")


def write_config_prod(args):
    api_root = getattr(args, "api_root_domain", "") or "example.com"
    api_prod = getattr(args, "api_domain_prod", "") or "api.example.com"
    content = """\
# NOTE: Variables set in here will activate only in a production environment
# export EXAMPLE_VAR="Hello from production"

# Optional: per-environment VPC override (tag:Name); most clients use default VPC or config.global
# export VPC_NAME=Prod

####################################################################################################
# API Service Configuration (only needed for app type 'api')
# * The root domain MUST already exist in Route53 in your AWS account
####################################################################################################
export API_ROOT_DOMAIN={api_root_domain}
export API_DOMAIN={api_domain_prod}

# Number of tasks in an ECS Service
export MIN_COUNT={min_count}
export MAX_COUNT={max_count}
"""
    with open(CONFIG_PROD, "w", encoding="utf-8") as f:
        f.write(content.format(
            api_root_domain=api_root,
            api_domain_prod=api_prod,
            min_count=getattr(args, "min_count", "1"),
            max_count=getattr(args, "max_count_prod", "2"),
        ))
    print("Wrote config.prod")


# ---------------------------------------------------------------------------
# Project-specific: main.py and Dockerfile
# ---------------------------------------------------------------------------
def apply_main_py(app_type):
    content = MAIN_PY_API if app_type in ("api", "internal_api") else MAIN_PY_TASK
    with open(MAIN_PY_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    if app_type in ("api", "internal_api"):
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

    new_tail = "\n" + (DOCKERFILE_CMD_API if app_type in ("api", "internal_api") else DOCKERFILE_CMD_TASK)
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
    if not getattr(args, "project_name", ""):
        args.project_name = prompt(
            "Project name (shared across related repos for cost grouping)",
            current.get("project_name", "") or args.app_name,
        )
    if not getattr(args, "manage_project_resource_group", ""):
        default_mgr = current.get("manage_project_resource_group", "")
        if not default_mgr:
            default_mgr = "true" if args.project_name == args.app_name else "false"
        args.manage_project_resource_group = prompt(
            "Manage project Resource Group? (true/false — true on one repo per project)",
            default_mgr,
        )
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
    ]:
        if not getattr(args, attr):
            setattr(args, attr, default)

    if args.app_type in ("api", "internal_api"):
        if not args.api_root_domain and discovered["route53_domains"]:
            args.api_root_domain = _choose_from_list("API root domain (Route53):", discovered["route53_domains"])
        if not args.api_root_domain:
            args.api_root_domain = prompt("API root domain (must exist in Route53)", current.get("api_root_domain", "example.com"))
        if not args.api_domain_staging:
            args.api_domain_staging = prompt("API domain for staging", current.get("api_domain_staging", "api-staging." + args.api_root_domain))
        if not args.api_domain_prod:
            args.api_domain_prod = prompt("API domain for prod", current.get("api_domain_prod", "api." + args.api_root_domain))

    for attr, fallback in [("min_count", "1"), ("max_count_staging", "2"), ("max_count_prod", "2"), ("vpc_name", "")]:
        if not getattr(args, attr, ""):
            setattr(args, attr, current.get(attr, fallback))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Configure this AWS ECS (Python) project.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--app-type", choices=APP_TYPES, help="api | internal_api | background_service | scheduled")
    parser.add_argument("--app-name", default="", help="APP_IDENT_WITHOUT_ENV (max 20 chars)")
    parser.add_argument("--project-name", default="", help="Project name for cross-repo cost grouping (defaults to app-name)")
    parser.add_argument(
        "--manage-project-resource-group",
        default="",
        choices=("", "true", "false"),
        help="Create rg-project-* Resource Group (true on one repo per project)",
    )
    parser.add_argument("--terraform-state-bucket", default="", help="S3 bucket for Terraform state")
    parser.add_argument("--aws-region", default="", help="AWS region (defaults to profile/env detection)")
    parser.add_argument("--aws-role-arn", default="", help="OIDC deployment role ARN")
    parser.add_argument("--app-cpu", default="256", help="ECS task CPU units")
    parser.add_argument("--app-memory", default="512", help="ECS task memory MB")
    parser.add_argument("--launch-type", default="FARGATE", choices=("FARGATE", "FARGATE_SPOT", "EC2"))
    parser.add_argument("--cpu-architecture", default="X86_64", choices=("X86_64", "ARM64"))
    parser.add_argument("--vpc-name", default="", help="Optional VPC tag:Name")
    parser.add_argument("--api-root-domain", default="", help="Root domain for API (api type only)")
    parser.add_argument("--api-domain-staging", default="", help="API domain for staging")
    parser.add_argument("--api-domain-prod", default="", help="API domain for prod")
    parser.add_argument("--min-count", default="1", help="MIN_COUNT for ECS service")
    parser.add_argument("--max-count-staging", default="2", help="MAX_COUNT staging")
    parser.add_argument("--max-count-prod", default="2", help="MAX_COUNT prod")
    parser.add_argument("--github-org", default="", help="GitHub org for plan detection / protections")
    parser.add_argument(
        "--github-approval-mode",
        default="",
        choices=("",) + APPROVAL_MODES,
        help="dispatch (Team default) or environment (Enterprise Environment reviewers)",
    )
    parser.add_argument("--enable-github-workflow", action="store_true", help="Enable github_flow.yml")
    parser.add_argument("--configure-github-protections", action="store_true", help="Create Environments + main ruleset via gh")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if required args missing")
    args = parser.parse_args()

    current = read_current_config()

    if not args.non_interactive:
        prompt_for_aws_credentials()
    ensure_aws_credentials()

    args.aws_region = resolve_aws_region(args.aws_region, current)
    if not args.non_interactive:
        args.aws_region = prompt("AWS region", args.aws_region)

    discovered = discover_aws_resources(args.aws_region)
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
        if not getattr(args, "project_name", ""):
            args.project_name = current.get("project_name", "") or args.app_name
        if not getattr(args, "manage_project_resource_group", ""):
            args.manage_project_resource_group = current.get("manage_project_resource_group", "") or (
                "true" if args.project_name == args.app_name else "false"
            )
        defaults = {"app_cpu": "256", "app_memory": "512", "launch_type": "FARGATE", "cpu_architecture": "X86_64"}
        for attr, default in defaults.items():
            if not getattr(args, attr):
                setattr(args, attr, current.get(attr, default))
        if args.app_type in ("api", "internal_api"):
            args.api_root_domain = args.api_root_domain or current.get("api_root_domain", "example.com")
            args.api_domain_staging = args.api_domain_staging or current.get("api_domain_staging", "api-staging.example.com")
            args.api_domain_prod = args.api_domain_prod or current.get("api_domain_prod", "api.example.com")
        for attr, fallback in [("min_count", "1"), ("max_count_staging", "2"), ("max_count_prod", "2"), ("vpc_name", "")]:
            if not getattr(args, attr, ""):
                setattr(args, attr, current.get(attr, fallback))
    else:
        _prompt_common(args, current, discovered)

    gh, org, mode, plan = resolve_github_approval_settings(args, current, args.non_interactive)
    print("Using GITHUB_APPROVAL_MODE={}{}".format(mode, " (org plan={})".format(plan) if plan else ""))

    write_config_global(args)
    write_config_staging(args)
    write_config_prod(args)
    apply_main_py(args.app_type)
    apply_dockerfile(args.app_type)

    if not args.non_interactive and not args.enable_github_workflow and not os.path.isfile(WORKFLOW_ENABLED):
        if prompt_yes_no("Enable GitHub workflow?", default_no=True):
            args.enable_github_workflow = True
    if args.enable_github_workflow:
        enable_github_workflow()

    if args.configure_github_protections or (
        not args.non_interactive and prompt_yes_no("Configure GitHub Environments + main PR ruleset via gh?", default_no=True)
    ):
        configure_github_protections(gh, org, mode, args.non_interactive)

    print("Setup complete. Edit config.global (and config.staging/config.prod) if needed, then deploy.")
    print("CI: plan runs automatically; apply is gated (dispatch Run workflow, or Environment approval).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

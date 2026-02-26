# Python AWS ECS App

Template for a **Python 3.12** app running on **AWS ECS (Fargate)**. The app is packaged as a Docker image (ECR) and can run in one of two modes, selected by `TRIGGER_TYPE`:

- **ecs_eventbridge** – Scheduled task: EventBridge cron runs the ECS task (with optional SQS DLQ).
- **ecs_service** – Always-on service: ECS Service behind an Application Load Balancer (optional HTTPS + Route53 when `api_domain` / `api_root_domain` are set).

## Technology stack

- Python 3.12, Poetry
- Docker
- Terraform (bootstrap + main; state in S3)
- GitHub Actions (test, deploy staging/prod, destroy via tags)

## Local development

### Prerequisites

- Python 3.12 and Poetry

```bash
# macOS
brew install python@3.12 poetry
poetry config virtualenvs.in-project true
```

### One-time setup

```bash
poetry env use python3.12
poetry install
```

Create `.env` in the project root with at least:

```
PYTHONPATH=app
```

### Run app locally

Default (basic task):

```bash
poetry run python app/main.py
```

If using the FastAPI option (uncomment in `app/main.py` and Dockerfile):

```bash
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Run tests

```bash
poetry run pytest tests/unit
```

---

## AWS deployment

### Prerequisites

- AWS account with OIDC role and S3 bucket for Terraform state (e.g. [NRD-Tech Terraform Bootstrap](https://github.com/NRD-Tech/nrdtech-terraform-aws-account-bootstrap)).
- VPC with subnets whose names contain `public` or `private` (used when EventBridge or ECS Service are enabled).
- Docker running (for local deploys; image is built and pushed by Terraform).

### Configure

Edit **`.env.global`**. At minimum set:

- `APP_IDENT_WITHOUT_ENV` – Short app name (e.g. `my-app`).
- `TERRAFORM_STATE_BUCKET` – S3 bucket for Terraform state.
- `AWS_DEFAULT_REGION` – e.g. `us-west-2`.
- `AWS_ROLE_ARN` – OIDC role ARN for the pipeline.
- `LAUNCH_TYPE` – `FARGATE` or `FARGATE_SPOT`.
- `TRIGGER_TYPE` – `ecs_eventbridge` (scheduled task) or `ecs_service` (always-on with ALB).
- `APP_CPU` / `APP_MEMORY` – Task size (e.g. `256` / `512`).
- `CPU_ARCHITECTURE` – `X86_64` or `ARM64`.
- `DESIRED_COUNT` – Number of tasks when using `ecs_service`.

Optionally set **`.env.staging`** and **`.env.prod`** (e.g. `API_DOMAIN`, `API_ROOT_DOMAIN` when using `ecs_service` with custom domain).

Trigger type is controlled only by `TRIGGER_TYPE`; no need to comment or uncomment Terraform files.

### Deploy from your machine

- **Staging:** `ENVIRONMENT=staging ./deploy.sh`
- **Production:** `ENVIRONMENT=prod ./deploy.sh`
- **Destroy:** `ENVIRONMENT=staging ./deploy.sh -d` or `ENVIRONMENT=prod ./deploy.sh -d`

### Deploy via GitHub Actions

- **Staging:** Push to `main` → workflow runs tests then deploys staging.
- **Production:** Push a tag `v*` (e.g. `git tag v1.0.0 && git push origin v1.0.0`) → deploys production.
- **Destroy staging:** Push tag `destroy-staging-*` (e.g. `destroy-staging-1`).
- **Destroy production:** Push tag `destroy-prod-*` (e.g. `destroy-prod-1`).

In **`.github/workflows/github_flow.yml`** the workflow loads `role-to-assume` and `aws-region` from `.env.global` (via the "Load configuration" step). Ensure those are set in `.env.global`; no hardcoded role in the workflow file.

---

## Run Docker image locally (ECS-style)

Build and run the same image that ECS uses (replace with your ECR URL and region):

```bash
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.us-west-2.amazonaws.com

docker run --rm -p 8080:8080 <account>.dkr.ecr.us-west-2.amazonaws.com/<app_ident>_repository:latest
```

For the default task image: container runs and exits. For FastAPI: `curl http://localhost:8080/ping`.

## Inspect Docker image

```bash
docker inspect <account>.dkr.ecr.<region>.amazonaws.com/<app_ident>_repository:latest
```

---

## Poetry cheat sheet

| Action                | Command |
|-----------------------|--------|
| Install dependencies  | `poetry install` |
| Run script            | `poetry run python app/main.py` |
| Run tests             | `poetry run pytest tests/unit` |
| Add dependency        | `poetry add <package>` |
| Add dev dependency    | `poetry add --group dev <package>` |
| Export requirements   | `poetry export -f requirements.txt --output requirements.txt` |

---

## Misc

### Proprietary use

This project is under the MIT License. You may use it as a base for proprietary work; replace the LICENSE file and optionally add a NOTICE file as needed.

### CodeArtifact (private Python packages)

One-time: add the CodeArtifact source to `pyproject.toml` (see [Poetry docs](https://python-poetry.org/docs/repositories/)).

Daily: obtain token and configure auth:

```bash
export CODEARTIFACT_TOKEN=$(aws codeartifact get-authorization-token --domain <domain> --domain-owner <account> --query authorizationToken --output text)
poetry config http-basic.<domain> aws $CODEARTIFACT_TOKEN
```

Uncomment the CodeArtifact block in `.env.global` and the Dockerfile if the image build needs private packages.

### Architecture

See **`architecture.md`** in the repo root for diagrams and a short architecture description.

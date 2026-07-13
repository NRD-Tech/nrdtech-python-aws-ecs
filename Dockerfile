# Multi-stage build: install deps in builder, run as non-root in runtime.
FROM python:3.14-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only main --no-interaction --no-ansi --no-root

FROM python:3.14-slim AS runtime

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && useradd --system --gid app --home /app --shell /usr/sbin/nologin app

COPY --from=builder /build/.venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY logging_config.json ./
COPY app ./app/

USER app

##############################################################################################################
# UN-COMMENT ONE OF THE SECTIONS BELOW (setup.py will rewrite the CMD block)
##############################################################################################################

##############################################################################################################
# Basic Task
##############################################################################################################
CMD ["python", "app/main.py"]

##############################################################################################################
# FastAPI App Service
##############################################################################################################
# EXPOSE 8080
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "--loop", "uvloop", "--http", "httptools", "--log-config", "logging_config.json"]

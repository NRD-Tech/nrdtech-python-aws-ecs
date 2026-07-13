"""Apply project-specific source/Dockerfile/handler templates."""

import os

from setup_lib import constants

MAIN_PY_API = """\
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.logging_setup import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

app = FastAPI()


@app.get("/ping")
async def ping():
    return JSONResponse(content={"message": "pong"})


@app.get("/healthcheck")
async def healthcheck():
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/live")
async def live():
    return JSONResponse(status_code=200, content={"status": "live"})


@app.get("/ready")
async def ready():
    return JSONResponse(status_code=200, content={"status": "ready"})
"""

MAIN_PY_TASK = """\
from app.logging_setup import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


def main():
    log.info("hello_world")
    print("Hello World")


if __name__ == "__main__":
    main()
"""

DOCKERFILE_CMD_API = (
    "# Expose the port the app will run on\n"
    "EXPOSE 8080\n"
    "# Command to run the application using Uvicorn\n"
    'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", '
    '"--workers", "4", "--loop", "uvloop", "--http", "httptools", "--log-config", "logging_config.json"]\n'
)


DOCKERFILE_CMD_TASK = 'CMD ["python", "app/main.py"]\n'


def apply_main_py(app_type):
    content = MAIN_PY_API if app_type in ("api", "internal_api") else MAIN_PY_TASK
    with open(constants.MAIN_PY_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    if app_type in ("api", "internal_api"):
        print("Enabled FastAPI in app/main.py (/ping, /healthcheck, /live, /ready)")
    else:
        print("Enabled task main in app/main.py")


def apply_dockerfile(app_type):
    if not os.path.isfile(constants.DOCKERFILE_PATH):
        return
    with open(constants.DOCKERFILE_PATH, encoding="utf-8") as f:
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
    with open(constants.DOCKERFILE_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines[:cut_idx])
        f.write(new_tail)
    print(f"Updated Dockerfile CMD for '{app_type}'")

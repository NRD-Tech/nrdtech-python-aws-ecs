"""Unit tests for setup.py (project setup script)."""
import importlib.util
import os
import sys
import tempfile

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SPEC = importlib.util.spec_from_file_location(
    "setup_project",
    os.path.join(_PROJECT_ROOT, "setup.py"),
)
setup_project = importlib.util.module_from_spec(_SPEC)
sys.modules["setup_project"] = setup_project
_SPEC.loader.exec_module(setup_project)


# ---------------------------------------------------------------------------
# _parse_export_file
# ---------------------------------------------------------------------------
def test_parse_export_file_missing_returns_empty():
    assert setup_project._parse_export_file("/nonexistent/path") == {}


def test_parse_export_file_parses_export_lines():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write('export FOO=bar\n')
        f.write('export BAR="baz"\n')
        f.write("export QUX='quux'\n")
        f.write("# export SKIP=no\n")
        f.write("not export BAD=line\n")
        path = f.name
    try:
        out = setup_project._parse_export_file(path)
        assert out["FOO"] == "bar"
        assert out["BAR"] == "baz"
        assert out["QUX"] == "quux"
        assert "SKIP" not in out
        assert "BAD" not in out
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Constants consistency
# ---------------------------------------------------------------------------
def test_app_types_and_trigger_map_consistent():
    assert set(setup_project.APP_TYPES) == set(setup_project.TRIGGER_TYPE_MAP.keys())


def test_ecs_app_types():
    assert setup_project.APP_TYPES == ("api", "background_service", "scheduled")


def test_legacy_trigger_type_reverse():
    assert setup_project.TRIGGER_TYPE_REVERSE.get("ecs_service") == "api"


# ---------------------------------------------------------------------------
# Placeholder checks
# ---------------------------------------------------------------------------
def test_is_placeholder_bucket():
    assert setup_project._is_placeholder_bucket("mycompany-terraform-state") is True
    assert setup_project._is_placeholder_bucket("") is True
    assert setup_project._is_placeholder_bucket("real-bucket") is False


def test_is_placeholder_role():
    assert setup_project._is_placeholder_role("arn:aws:iam::1234567890:role/test") is True
    assert setup_project._is_placeholder_role("") is True
    assert setup_project._is_placeholder_role("arn:aws:iam::999999999999:role/real") is False


# ---------------------------------------------------------------------------
# CLI --help
# ---------------------------------------------------------------------------
def test_main_help_exits_zero():
    orig = sys.argv
    try:
        sys.argv = ["setup.py", "--help"]
        with pytest.raises(SystemExit) as exc_info:
            setup_project.main()
        assert exc_info.value.code == 0
    finally:
        sys.argv = orig


# ---------------------------------------------------------------------------
# --non-interactive without required args
# ---------------------------------------------------------------------------
def test_main_non_interactive_missing_required(capsys, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    orig = sys.argv
    try:
        sys.argv = ["setup.py", "--non-interactive"]
        result = setup_project.main()
        assert result == 1
        err = capsys.readouterr().err.lower()
        assert "required" in err or "app" in err
    finally:
        sys.argv = orig


# ---------------------------------------------------------------------------
# Full non-interactive run writes config files
# ---------------------------------------------------------------------------
def test_non_interactive_full_run_writes_configs(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    # Create minimal app/main.py and Dockerfile
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("print('hello')\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12-slim\nCOPY app ./app/\nCMD [\"python\", \"app/main.py\"]\n")

    monkeypatch.setattr(setup_project, "SCRIPT_DIR", str(tmp_path))
    monkeypatch.setattr(setup_project, "CONFIG_GLOBAL", str(tmp_path / "config.global"))
    monkeypatch.setattr(setup_project, "CONFIG_STAGING", str(tmp_path / "config.staging"))
    monkeypatch.setattr(setup_project, "CONFIG_PROD", str(tmp_path / "config.prod"))
    monkeypatch.setattr(setup_project, "MAIN_PY_PATH", str(app_dir / "main.py"))
    monkeypatch.setattr(setup_project, "DOCKERFILE_PATH", str(dockerfile))

    orig = sys.argv
    try:
        sys.argv = [
            "setup.py", "--non-interactive",
            "--app-type", "api",
            "--app-name", "test-app",
            "--terraform-state-bucket", "my-bucket",
            "--aws-role-arn", "arn:aws:iam::999:role/test",
        ]
        result = setup_project.main()
        assert result == 0
    finally:
        sys.argv = orig

    assert (tmp_path / "config.global").exists()
    assert (tmp_path / "config.staging").exists()
    assert (tmp_path / "config.prod").exists()

    global_text = (tmp_path / "config.global").read_text()
    assert "test-app" in global_text
    assert "my-bucket" in global_text
    assert "ecs_api_service" in global_text

    # Verify main.py has FastAPI content
    main_py = (app_dir / "main.py").read_text()
    assert "FastAPI" in main_py

    # Verify Dockerfile has uvicorn CMD
    df = dockerfile.read_text()
    assert "uvicorn" in df


def test_non_interactive_scheduled_type(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("print('hello')\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12-slim\nCOPY app ./app/\nCMD [\"python\", \"app/main.py\"]\n")

    monkeypatch.setattr(setup_project, "SCRIPT_DIR", str(tmp_path))
    monkeypatch.setattr(setup_project, "CONFIG_GLOBAL", str(tmp_path / "config.global"))
    monkeypatch.setattr(setup_project, "CONFIG_STAGING", str(tmp_path / "config.staging"))
    monkeypatch.setattr(setup_project, "CONFIG_PROD", str(tmp_path / "config.prod"))
    monkeypatch.setattr(setup_project, "MAIN_PY_PATH", str(app_dir / "main.py"))
    monkeypatch.setattr(setup_project, "DOCKERFILE_PATH", str(dockerfile))

    orig = sys.argv
    try:
        sys.argv = [
            "setup.py", "--non-interactive",
            "--app-type", "scheduled",
            "--app-name", "cron-job",
            "--terraform-state-bucket", "my-bucket",
            "--aws-role-arn", "arn:aws:iam::999:role/test",
        ]
        result = setup_project.main()
        assert result == 0
    finally:
        sys.argv = orig

    global_text = (tmp_path / "config.global").read_text()
    assert "ecs_eventbridge" in global_text

    main_py = (app_dir / "main.py").read_text()
    assert "Hello World" in main_py

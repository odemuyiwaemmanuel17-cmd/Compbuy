"""Deployment contract: the Vercel entrypoint and the platform-inferred environment.

These guard the two things that broke or silently misbehaved on a real deploy:
a pyproject.toml that uv can resolve, and a session secret that must not be
ephemeral once the app runs on shared, short-lived containers.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent


def _env(monkeypatch, **values: str | None) -> None:
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


# --------------------------------------------------------------- pyproject.toml


def test_pyproject_declares_a_resolvable_project() -> None:
    """uv fails the build outright with 'No project table found'."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "project" in data, "pyproject.toml needs a [project] table for uv"
    assert data["project"]["name"] == "compbuy"
    assert data["project"]["version"]
    assert data["project"]["requires-python"].startswith(">=3.1")


def test_pyproject_runtime_dependencies_are_pinned() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["dependencies"]
    names = {entry.split("[")[0].split("==")[0] for entry in runtime}
    assert {"fastapi", "uvicorn", "jinja2", "supabase", "itsdangerous"} <= names
    assert all("==" in entry for entry in runtime), "unpinned runtime deps drift between builds"


def test_test_only_tools_stay_out_of_the_runtime_set() -> None:
    """The deployed function should not carry pytest/httpx."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = " ".join(data["project"]["dependencies"])
    dev = " ".join(data["project"]["optional-dependencies"]["dev"])
    for tool in ("pytest", "httpx"):
        assert tool not in runtime, tool
        assert tool in dev, tool


def test_requirements_txt_defers_to_pyproject() -> None:
    """One source of truth: requirements.txt must not restate version pins."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "." in text
    assert "==" not in text, "pins belong in pyproject.toml only"


def test_python_version_pin_satisfies_requires_python() -> None:
    pin = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = data["project"]["requires-python"].removeprefix(">=").strip()
    assert tuple(int(part) for part in pin.split(".")) >= tuple(int(part) for part in floor.split("."))


# ------------------------------------------------------------------- entrypoint


def test_vercel_finds_an_asgi_app_at_the_supported_entrypoint() -> None:
    """Vercel looks for a FastAPI instance named `app` in app/main.py."""
    from app.main import app

    assert isinstance(app, FastAPI)
    assert (ROOT / "app" / "main.py").is_file()


def test_templates_and_static_files_resolve_relative_to_the_package(monkeypatch, tmp_path) -> None:
    """Serverless containers run from an unpredictable cwd, so paths must not be cwd-based."""
    from app.main import STATIC_DIR
    from app.templating import TEMPLATES_DIR

    monkeypatch.chdir(tmp_path)
    assert TEMPLATES_DIR.is_dir()
    assert (TEMPLATES_DIR / "listings" / "detail.html").is_file()
    assert STATIC_DIR.is_dir()


# ------------------------------------------------------- environment inference


def test_deployed_vercel_environment_is_treated_as_production(monkeypatch) -> None:
    from app.config import settings_from_env

    for vercel_env in ("production", "preview"):
        _env(monkeypatch, APP_ENV=None, VERCEL_ENV=vercel_env, COOKIE_SECURE=None)
        settings = settings_from_env()
        assert settings.is_production, vercel_env
        assert settings.cookie_secure, vercel_env


def test_vercel_local_dev_stays_development(monkeypatch) -> None:
    from app.config import settings_from_env

    _env(monkeypatch, APP_ENV=None, VERCEL_ENV="development", COOKIE_SECURE=None)
    assert not settings_from_env().is_production


def test_explicit_app_env_overrides_the_platform_guess(monkeypatch) -> None:
    from app.config import settings_from_env

    _env(monkeypatch, APP_ENV="staging", VERCEL_ENV="development")
    assert settings_from_env().is_production

    _env(monkeypatch, APP_ENV="development", VERCEL_ENV="production")
    assert not settings_from_env().is_production


def test_missing_secret_fails_fast_when_deployed(monkeypatch) -> None:
    """Better a loud boot failure than cookies that die on the next cold start."""
    from app.config import settings_from_env
    from app.main import _session_secret

    _env(monkeypatch, APP_ENV=None, VERCEL_ENV="production", SESSION_SECRET=None)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _session_secret(settings_from_env())


def test_secret_is_reused_across_restarts_when_configured(monkeypatch) -> None:
    from app.config import settings_from_env
    from app.main import _session_secret

    _env(monkeypatch, APP_ENV=None, VERCEL_ENV="production", SESSION_SECRET="a-fixed-deploy-secret")
    settings = settings_from_env()
    assert _session_secret(settings) == _session_secret(settings) == "a-fixed-deploy-secret"

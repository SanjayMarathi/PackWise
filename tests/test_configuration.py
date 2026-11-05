"""Settings helpers, production fail-fast behaviour and the demo seed command."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from config.settings import base
from inventory.models import Product, ShippingBox

ROOT = Path(__file__).resolve().parent.parent
STRONG_KEY = "x" * 60


# ---------------------------------------------------------------- env helpers


def test_env_bool(monkeypatch):
    for raw, expected in [("true", True), ("1", True), ("off", False), ("NO", False)]:
        monkeypatch.setenv("PW_FLAG", raw)
        assert base.env_bool("PW_FLAG") is expected
    monkeypatch.delenv("PW_FLAG")
    assert base.env_bool("PW_FLAG", default=True) is True
    monkeypatch.setenv("PW_FLAG", "maybe")
    with pytest.raises(ImproperlyConfigured):
        base.env_bool("PW_FLAG")


def test_env_int_and_list(monkeypatch):
    monkeypatch.setenv("PW_INT", "42")
    assert base.env_int("PW_INT", 1) == 42
    monkeypatch.setenv("PW_INT", "forty")
    with pytest.raises(ImproperlyConfigured):
        base.env_int("PW_INT", 1)
    monkeypatch.setenv("PW_LIST", " a.com, ,b.com ")
    assert base.env_list("PW_LIST") == ["a.com", "b.com"]


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("PW_EMPTY", "")
    assert base.env("PW_EMPTY", "fallback") == "fallback"


def test_required_env_and_database_url(monkeypatch):
    monkeypatch.delenv("PW_MISSING", raising=False)
    with pytest.raises(ImproperlyConfigured, match="PW_MISSING"):
        base.env_required("PW_MISSING")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        base.database_config()
    config = base.database_config("postgres://u:p@db.example:5433/name")
    assert (config["HOST"], config["PORT"], config["NAME"]) == ("db.example", 5433, "name")


# ---------------------------------------------------------------- production settings (separate process)


def load_production_settings(**env):
    """Import config.settings.production in a clean interpreter with ``env``."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "DATABASE_URL", "RENDER_"))}
    clean.update(env)
    code = "import config.settings.production as s; print(s.DEBUG, s.ALLOWED_HOSTS, s.SECURE_SSL_REDIRECT)"
    return subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], cwd=ROOT, env=clean, capture_output=True, text=True, timeout=60, check=False
    )


def test_production_requires_a_secret_key():
    result = load_production_settings(DATABASE_URL="postgres://u:p@h/db", DJANGO_ALLOWED_HOSTS="api.example.com")
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY environment variable is required" in result.stderr


def test_production_rejects_a_weak_secret_key():
    result = load_production_settings(
        DJANGO_SECRET_KEY="short",  # noqa: S106 - deliberately weak test value
        DATABASE_URL="postgres://u:p@h/db",
        DJANGO_ALLOWED_HOSTS="api.example.com",
    )
    assert result.returncode != 0
    assert "strong, random value" in result.stderr


def test_production_accepts_a_render_generated_secret():
    """Render's generateValue yields base64(256 random bits) = 44 characters."""
    import base64
    import secrets

    key = base64.b64encode(secrets.token_bytes(32)).decode()
    assert len(key) == 44
    result = load_production_settings(
        DJANGO_SECRET_KEY=key, DATABASE_URL="postgres://u:p@h/db", DJANGO_ALLOWED_HOSTS="api.example.com"
    )
    assert result.returncode == 0, result.stderr


def test_production_requires_allowed_hosts():
    result = load_production_settings(DJANGO_SECRET_KEY=STRONG_KEY, DATABASE_URL="postgres://u:p@h/db")
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_production_settings_are_hardened():
    result = load_production_settings(
        DJANGO_SECRET_KEY=STRONG_KEY,
        DATABASE_URL="postgres://u:p@h/db",
        RENDER_EXTERNAL_HOSTNAME="packwise.onrender.com",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False ['packwise.onrender.com'] True"


# ---------------------------------------------------------------- seed command


@pytest.mark.django_db
def test_seed_demo_data_is_idempotent():
    call_command("seed_demo_data")
    call_command("seed_demo_data")
    assert ShippingBox.objects.count() == 6
    assert Product.objects.count() == 8
    assert ShippingBox.objects.get(box_code="BX-M").cost == 35

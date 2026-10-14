"""Round 8 (GH-38) phase 9.1: the Firebase Auth emulator (unsigned tokens) can never be live in production."""
import base64
import json
import time

import pytest

from app import auth
from app.config import Settings, check_auth_emulator_config, check_production_config, resolve_env


def make(**kw):
    return Settings(connector_secret_key="x" * 40, **kw)


def test_production_with_emulator_refuses_to_start():
    s = make(loam_env="production", auth_emulator_host="127.0.0.1:9099", host="127.0.0.1")
    with pytest.raises(RuntimeError, match="APP_ENV=production"):
        check_auth_emulator_config(s)
    with pytest.raises(RuntimeError):
        check_production_config(s)


def test_emulator_on_a_public_bind_refuses_to_start():
    with pytest.raises(RuntimeError, match="loopback"):
        check_auth_emulator_config(make(loam_env="development", auth_emulator_host="127.0.0.1:9099", host="0.0.0.0"))


def test_emulator_allowed_locally_and_absent_is_fine():
    check_auth_emulator_config(make(loam_env="development", auth_emulator_host="127.0.0.1:9099", host="127.0.0.1"))
    check_auth_emulator_config(make(loam_env="production", auth_emulator_host="", host="0.0.0.0"))


def test_app_env_and_loam_env_are_one_setting(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOAM_ENV", "development")
    assert resolve_env() == "production"
    monkeypatch.setenv("APP_ENV", "")
    monkeypatch.setenv("LOAM_ENV", "production")
    assert resolve_env() == "production"
    monkeypatch.setenv("LOAM_ENV", "test")
    assert resolve_env() == "test"


def _token(alg="none", project="demo-loam", exp=None):
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    claims = {"aud": project, "iss": f"https://securetoken.google.com/{project}", "sub": "u1",
              "exp": exp or time.time() + 600, "email": "rider@example.com", "email_verified": True}
    return f"{b({'alg': alg, 'typ': 'JWT'})}.{b(claims)}.sig"


def test_unsigned_tokens_are_rejected_without_the_emulator(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_emulator_host", "")
    with pytest.raises(auth.AuthError):
        auth.verify_firebase_token(_token())


def test_emulator_tokens_checked_when_enabled(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_emulator_host", "127.0.0.1:9099")
    monkeypatch.setattr(auth.settings, "firebase_project_id", "demo-loam")
    assert auth.verify_firebase_token(_token())["sub"] == "u1"
    for bad in (_token(alg="RS256"), _token(project="thepfisters"), _token(exp=time.time() - 5)):
        with pytest.raises(auth.AuthError):
            auth.verify_firebase_token(bad)

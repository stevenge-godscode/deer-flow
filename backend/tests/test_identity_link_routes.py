from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity, OIDCMetadata
from app.gateway.auth.oidc_state import OIDCStatePayload, _sign_state_payload, _verify_state_signed, get_state_cookie
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import auth
from deerflow.config.auth_config import OIDCProviderConfig


@pytest.fixture
def setup(monkeypatch):
    user = User(email="legacy@example.com", password_hash="hash")
    local = AsyncMock()
    local.get_user.return_value = user
    local.link_oauth_identity.return_value = user.model_copy(update={"oauth_provider": "genesis-dev", "oauth_id": "sub", "token_version": 1})
    provider = OIDCProviderConfig(display_name="Genesis", issuer="https://issuer.example.com", client_id="client", redirect_uri="https://agents.example.com/api/v1/auth/callback/genesis-dev")
    cfg = SimpleNamespace(auth=SimpleNamespace(oidc=SimpleNamespace(enabled=True, providers={"genesis-dev": provider}, frontend_base_url="https://agents.example.com")))
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: cfg)
    monkeypatch.setattr(auth, "get_local_provider", lambda: local)
    monkeypatch.setattr(auth, "get_current_user_from_request", AsyncMock(return_value=user))
    monkeypatch.setattr(auth, "_check_rate_limit", AsyncMock())
    monkeypatch.setattr(auth, "_record_login_failure", AsyncMock())
    monkeypatch.setattr("app.gateway.auth.password.verify_password_async", AsyncMock(return_value=True))
    service = AsyncMock()
    service.discover.return_value = OIDCMetadata(issuer=provider.issuer, authorization_endpoint=provider.issuer + "/authorize", token_endpoint=provider.issuer + "/token", userinfo_endpoint=None, jwks_uri=provider.issuer + "/jwks")
    service.build_authorization_url = lambda **kw: provider.issuer + "/authorize?state=" + kw["state"]
    service.authenticate_callback.return_value = OIDCIdentity(provider="genesis-dev", subject="sub", email="central@example.com", email_verified=True, name=None, claims={})
    monkeypatch.setattr(auth, "_get_oidc_service", lambda: service)
    app = FastAPI()
    app.include_router(auth.router)
    app.add_middleware(CSRFMiddleware)
    client = TestClient(app, base_url="https://agents.example.com")
    client.cookies.set("access_token", "test-session", domain="agents.example.com", path="/")
    client.cookies.set("csrf_token", "test-csrf", domain="agents.example.com", path="/")
    return client, user, local, service


def headers():
    return {"origin": "https://agents.example.com", "X-CSRF-Token": "test-csrf"}


def test_link_start_requires_both_csrf_and_origin(setup):
    c, u, local, service = setup
    assert c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret"}).status_code == 403
    assert c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret"}, headers={**headers(), "origin": "https://evil.example.com"}).status_code == 403
    service.discover.assert_not_called()
    local.link_oauth_identity.assert_not_called()


def test_link_start_returns_signed_target_and_full_callback(setup):
    c, u, local, service = setup
    r = c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret", "next": "/workspace"}, headers=headers())
    assert r.status_code == 200, r.text
    state = _verify_state_signed(c.cookies.get("df_oidc_state_genesis-dev"))
    assert state.link_user_id == str(u.id) and state.link_token_version == 0 and state.code_verifier and state.nonce
    r = c.get("/api/v1/auth/callback/genesis-dev", params={"code": "verified-code", "state": state.state}, follow_redirects=False)
    assert r.status_code == 302 and "/auth/callback?next=" in r.headers["location"]
    local.link_oauth_identity.assert_awaited_once_with(str(u.id), "genesis-dev", "sub", "https://issuer.example.com", 0)
    local.create_oauth_user.assert_not_called()
    local.get_user_by_email.assert_not_called()
    assert "df_oidc_state_genesis-dev" not in c.cookies


@pytest.mark.parametrize("case", ["wrong_password", "admin", "bound", "no_cookie", "bearer", "unknown_provider", "forged_target"])
def test_bad_start_cannot_create_intent(setup, monkeypatch, case):
    c, u, local, service = setup
    body = {"password": "secret"}
    provider = "genesis-dev"
    h = headers()
    if case == "wrong_password":
        monkeypatch.setattr("app.gateway.auth.password.verify_password_async", AsyncMock(return_value=False))
    if case == "admin":
        u.system_role = "admin"
    if case == "bound":
        u.oauth_provider = "other"
        u.oauth_id = "existing"
    if case == "no_cookie":
        c.cookies.delete("access_token")
    if case == "bearer":
        h["authorization"] = "Bearer test"
    if case == "unknown_provider":
        provider = "unknown"
    if case == "forged_target":
        body["user_id"] = "another"
    assert c.post(f"/api/v1/auth/oauth/{provider}/link", json=body, headers=h).status_code in (400, 401, 403, 409, 422)
    service.discover.assert_not_called()
    local.link_oauth_identity.assert_not_called()


def test_callback_stale_session_does_not_link_or_jit(setup):
    c, u, local, service = setup
    c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret"}, headers=headers())
    state = _verify_state_signed(c.cookies.get("df_oidc_state_genesis-dev"))
    u.token_version = 1
    r = c.get("/api/v1/auth/callback/genesis-dev", params={"code": "code", "state": state.state}, follow_redirects=False)
    assert "error=sso_not_allowed" in r.headers["location"]
    local.link_oauth_identity.assert_not_called()
    local.create_oauth_user.assert_not_called()


def test_signed_provider_mismatch_is_rejected():
    from starlette.requests import Request

    state = OIDCStatePayload(provider="other", state="nonce")
    req = Request({"type": "http", "headers": [(b"cookie", ("df_oidc_state_genesis-dev=" + _sign_state_payload(state)).encode())]})
    assert get_state_cookie(req, "genesis-dev") is None


def test_native_cookie_version_is_checked_before_password_proof(setup, monkeypatch):
    from app.gateway.auth import create_access_token
    from app.gateway.deps import get_current_user_from_request

    c, u, local, service = setup
    monkeypatch.setattr(auth, "get_current_user_from_request", get_current_user_from_request)
    monkeypatch.setattr("app.gateway.deps.get_local_provider", lambda: local)
    c.cookies.set("access_token", create_access_token(str(u.id), token_version=1), domain="agents.example.com", path="/")
    assert c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret"}, headers=headers()).status_code == 401
    service.discover.assert_not_called()
    local.link_oauth_identity.assert_not_called()
    c.cookies.set("access_token", create_access_token(str(u.id), token_version=0), domain="agents.example.com", path="/")
    assert c.post("/api/v1/auth/oauth/genesis-dev/link", json={"password": "secret"}, headers=headers()).status_code == 200


def test_unlink_revokes_binding_and_clears_session(setup):
    c, u, local, service = setup
    u.oauth_provider = "genesis-dev"
    u.oauth_id = "sub"
    u.token_version = 4
    r = c.post("/api/v1/auth/oauth/genesis-dev/unlink", json={"password": "secret"}, headers=headers())
    assert r.status_code == 204, r.text
    local.unlink_oauth_identity.assert_awaited_once_with(str(u.id), "genesis-dev", "sub", "https://issuer.example.com", 4)
    assert "access_token" not in c.cookies


@pytest.mark.parametrize("case", ["passwordless", "wrong_binding", "wrong_password", "no_csrf"])
def test_unlink_requires_reauthentication_and_alternative_login(setup, monkeypatch, case):
    c, u, local, service = setup
    u.oauth_provider = "genesis-dev"
    u.oauth_id = "sub"
    h = headers()
    if case == "passwordless":
        u.password_hash = None
    if case == "wrong_binding":
        u.oauth_provider = "other"
    if case == "wrong_password":
        monkeypatch.setattr("app.gateway.auth.password.verify_password_async", AsyncMock(return_value=False))
    if case == "no_csrf":
        h.pop("X-CSRF-Token")
    assert c.post("/api/v1/auth/oauth/genesis-dev/unlink", json={"password": "secret"}, headers=h).status_code in (401, 403, 409)
    local.unlink_oauth_identity.assert_not_called()


def test_incomplete_or_expired_link_state_is_rejected():
    import time

    import jwt

    from app.gateway.auth.config import get_auth_config

    malformed = {"provider": "genesis-dev", "state": "nonce", "link_user_id": "local", "issued_at": time.time()}
    assert _verify_state_signed(jwt.encode(malformed, get_auth_config().jwt_secret, algorithm="HS256")) is None
    expired = OIDCStatePayload(provider="genesis-dev", state="nonce", issued_at=time.time() - 301)
    assert _verify_state_signed(_sign_state_payload(expired)) is None

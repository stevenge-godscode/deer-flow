from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.auth.identity_linking import link_verified_oidc_identity
from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.oidc_state import OIDCStatePayload
from deerflow.config.auth_config import OIDCProviderConfig


def inputs():
    user = User(email="legacy@example.com", password_hash="hash")
    state = OIDCStatePayload(provider="genesis-dev", state="nonce", link_user_id=str(user.id), link_token_version=0)
    cfg = OIDCProviderConfig(display_name="Genesis", issuer="https://issuer.example.com", client_id="client")
    identity = OIDCIdentity(provider="genesis-dev", subject="verified-sub", email="different@example.com", email_verified=True, name=None, claims={})
    return user, state, cfg, identity


@pytest.mark.asyncio
async def test_two_proofs_keep_local_id_even_when_emails_differ():
    user, state, cfg, identity = inputs()
    local = AsyncMock()
    local.link_oauth_identity.return_value = user
    assert await link_verified_oidc_identity("genesis-dev", cfg, identity, local, state, user) == user
    local.link_oauth_identity.assert_awaited_once_with(str(user.id), "genesis-dev", "verified-sub", cfg.issuer, 0)
    local.get_user_by_email.assert_not_called()
    local.create_oauth_user.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["wrong_user", "stale", "admin", "passwordless", "bound", "unverified", "domain", "provider"])
async def test_invalid_link_proof_has_no_write(case):
    user, state, cfg, identity = inputs()
    if case == "wrong_user":
        state.link_user_id = "another-user"
    if case == "stale":
        user.token_version = 1
    if case == "admin":
        user.system_role = "admin"
    if case == "passwordless":
        user.password_hash = None
    if case == "bound":
        user.oauth_provider = "other"
        user.oauth_id = "bound"
    if case == "unverified":
        identity = OIDCIdentity(**{**identity.__dict__, "email_verified": False})
    if case == "domain":
        cfg.allowed_email_domains = ["corporate.example.com"]
    if case == "provider":
        identity = OIDCIdentity(**{**identity.__dict__, "provider": "other"})
    local = AsyncMock()
    with pytest.raises(HTTPException):
        await link_verified_oidc_identity("genesis-dev", cfg, identity, local, state, user)
    local.link_oauth_identity.assert_not_called()


@pytest.mark.asyncio
async def test_unique_conflict_is_safe_409():
    user, state, cfg, identity = inputs()
    local = AsyncMock()
    local.link_oauth_identity.side_effect = ValueError("conflict")
    with pytest.raises(HTTPException) as e:
        await link_verified_oidc_identity("genesis-dev", cfg, identity, local, state, user)
    assert e.value.status_code == 409

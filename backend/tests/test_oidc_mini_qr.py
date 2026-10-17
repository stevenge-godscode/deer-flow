"""A signed, allowlisted native login proof can enroll an ordinary email-less user."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.gateway.auth.models import User, UserResponse
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from deerflow.config.auth_config import OIDCProviderConfig


def config(**changes):
    return OIDCProviderConfig(
        display_name="Genesis",
        issuer="https://identity.dev.godscode.com.cn",
        client_id="deerflow-sso-dev",
        trusted_non_email_providers=["genesis-miniapp-dev"],
        **changes,
    )


def identity(*, proof="genesis-miniapp-dev", email="", verified=False, claims=None):
    return OIDCIdentity(
        provider="genesis-dev",
        subject="wmp_verified_owner",
        email=email,
        email_verified=verified,
        name="WeChat",
        claims=claims or {},
        authenticated_provider=proof,
    )


@pytest.mark.asyncio
async def test_verified_mini_source_enrolls_without_fake_email_or_admin():
    local = AsyncMock()
    local.get_user_by_oauth.return_value = None
    created = User(email=None, oauth_provider="genesis-dev", oauth_id="wmp_verified_owner")
    local.create_oauth_user.return_value = created
    result = await get_or_provision_oidc_user("genesis-dev", config(), identity(), local)
    assert result["user"] is created
    local.get_user_by_email.assert_not_awaited()
    local.create_oauth_user.assert_awaited_once_with(
        email=None,
        oauth_provider="genesis-dev",
        oauth_id="wmp_verified_owner",
        system_role="user",
    )
    assert UserResponse(id=str(created.id), email=created.email, system_role="user").email is None


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, "other-provider", "genesis-miniapp-prod"])
async def test_unapproved_or_userinfo_only_provider_cannot_enroll(proof):
    local = AsyncMock()
    local.get_user_by_oauth.return_value = None
    with pytest.raises(HTTPException) as e:
        await get_or_provision_oidc_user(
            "genesis-dev",
            config(),
            identity(proof=proof, claims={"provider": "genesis-miniapp-dev"}),
            local,
        )
    assert e.value.status_code == 403
    local.create_oauth_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_mini_proof_does_not_bypass_email_domain_policy():
    local = AsyncMock()
    local.get_user_by_oauth.return_value = None
    with pytest.raises(HTTPException) as e:
        await get_or_provision_oidc_user(
            "genesis-dev",
            config(allowed_email_domains=["company.test"]),
            identity(),
            local,
        )
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_unverified_claimed_email_is_not_persisted_or_granted_admin():
    local = AsyncMock()
    local.get_user_by_oauth.return_value = None
    local.create_oauth_user.return_value = User(email=None, oauth_provider="genesis-dev", oauth_id="wmp_verified_owner")
    await get_or_provision_oidc_user(
        "genesis-dev",
        config(admin_emails=["admin@example.com"]),
        identity(email="admin@example.com"),
        local,
    )
    assert local.create_oauth_user.await_args.kwargs["email"] is None
    assert local.create_oauth_user.await_args.kwargs["system_role"] == "user"


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"oauth_provider": "genesis-dev"},
        {
            "oauth_provider": "genesis-dev",
            "oauth_id": "sub",
            "password_hash": "local-hash",
        },
        {"oauth_provider": "genesis-dev", "oauth_id": "sub", "system_role": "admin"},
    ],
)
def test_email_less_local_or_admin_account_is_not_a_valid_model(extra):
    with pytest.raises(ValidationError):
        User(email=None, **extra)


@pytest.mark.asyncio
async def test_real_sqlite_repository_preserves_two_email_less_owners(tmp_path):
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.persistence.engine import (
        close_engine,
        get_session_factory,
        init_engine,
    )

    await init_engine(
        "sqlite",
        url="sqlite+aiosqlite:///" + str(tmp_path / "qr.sqlite"),
        sqlite_dir=str(tmp_path),
    )
    try:
        repo = SQLiteUserRepository(get_session_factory())
        a = await repo.create_user(User(email=None, oauth_provider="genesis-dev", oauth_id="wx-a"))
        b = await repo.create_user(User(email=None, oauth_provider="genesis-dev", oauth_id="wx-b"))
        assert a.id != b.id
        assert (await repo.get_user_by_oauth("genesis-dev", "wx-a")).id == a.id
        assert (await repo.get_user_by_oauth("genesis-dev", "wx-b")).id == b.id
        assert (await repo.get_user_by_id(str(a.id))).email is None
    finally:
        await close_engine()

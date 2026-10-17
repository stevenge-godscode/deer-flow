"""Only explicit trust in a signed verified-phone claim permits email-less JIT."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from deerflow.config.auth_config import OIDCProviderConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,phone,allowed", [(True, "+8613800138000", True), (False, "+8613800138000", False), (True, None, False)])
async def test_verified_phone_jit_is_configured_and_never_admin(enabled, phone, allowed):
    config = OIDCProviderConfig(display_name="Genesis", issuer="https://identity.dev.godscode.com.cn", client_id="deerflow-sso-dev", allow_verified_phone=enabled, admin_emails=["admin@example.com"])
    identity = OIDCIdentity(provider="genesis-dev", subject="native-phone-sub", email="admin@example.com", email_verified=False, name="Phone", claims={"phone_number": "+8613800138000", "phone_number_verified": True}, verified_phone=phone)
    local = AsyncMock()
    local.get_user_by_oauth.return_value = None
    local.create_oauth_user.return_value = User(email=None, oauth_provider="genesis-dev", oauth_id=identity.subject)
    if not allowed:
        with pytest.raises(HTTPException):
            await get_or_provision_oidc_user("genesis-dev", config, identity, local)
        local.create_oauth_user.assert_not_awaited()
        return
    result = await get_or_provision_oidc_user("genesis-dev", config, identity, local)
    assert result["user"].email is None
    assert local.create_oauth_user.await_args.kwargs["system_role"] == "user"
    local.get_user_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_phone_login_preserves_exact_existing_subject():
    config = OIDCProviderConfig(display_name="Genesis", issuer="https://identity.dev.godscode.com.cn", client_id="deerflow-sso-dev", allow_verified_phone=True)
    identity = OIDCIdentity(provider="genesis-dev", subject="existing", email="", email_verified=False, name="Phone", claims={}, verified_phone="+8613800138000")
    existing = User(email="existing@example.com", oauth_provider="genesis-dev", oauth_id="existing")
    local = AsyncMock()
    local.get_user_by_oauth.return_value = existing
    result = await get_or_provision_oidc_user("genesis-dev", config, identity, local)
    assert result["user"] is existing and result["created"] is False
    local.create_oauth_user.assert_not_awaited()


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_phone_proof_rejects_nonboolean_verified(value):
    from app.gateway.auth.oidc import _verified_phone_claim

    assert _verified_phone_claim({"phone_number": "+8613800138000", "phone_number_verified": value}) is None


@pytest.mark.parametrize("phone", ["13800138000", "+0", True, None])
def test_phone_proof_requires_canonical_number(phone):
    from app.gateway.auth.oidc import _verified_phone_claim

    assert _verified_phone_claim({"phone_number": phone, "phone_number_verified": True}) is None

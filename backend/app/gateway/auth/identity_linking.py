"""Explicit local-password plus verified OIDC association; no email matching."""

from fastapi import HTTPException

from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.oidc import OIDCIdentity
from app.gateway.auth.oidc_state import OIDCStatePayload
from deerflow.config.auth_config import OIDCProviderConfig


async def link_verified_oidc_identity(provider: str, config: OIDCProviderConfig, identity: OIDCIdentity, local: LocalAuthProvider, state: OIDCStatePayload, user: User) -> User:
    if state.provider != provider or identity.provider != provider or state.link_user_id != str(user.id) or state.link_token_version != user.token_version:
        raise HTTPException(status_code=403, detail="Account ownership proof expired or changed")
    if user.system_role != "user" or not user.password_hash or user.oauth_provider or user.oauth_id:
        raise HTTPException(status_code=409, detail="This account cannot be linked")
    # An explicit association always requires verified identity, even when normal
    # SSO login for this provider has a weaker configurable email policy.
    if not identity.email_verified or not identity.email or not identity.subject:
        raise HTTPException(status_code=403, detail="Verified identity is required")
    if config.allowed_email_domains:
        domain = identity.email.lower().rsplit("@", 1)[-1]
        if domain not in {d.lower().lstrip("@") for d in config.allowed_email_domains}:
            raise HTTPException(status_code=403, detail="Identity domain is not allowed")
    try:
        return await local.link_oauth_identity(str(user.id), provider, identity.subject, config.issuer, user.token_version)
    except ValueError:
        raise HTTPException(status_code=409, detail="Account or identity binding changed; sign in again") from None

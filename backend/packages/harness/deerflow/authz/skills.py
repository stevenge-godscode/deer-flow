"""Live skill permission checks shared by activation and tool-policy gates."""

from __future__ import annotations

from deerflow.authz.provider import AuthorizationProvider, AuthzRequest, Principal


def is_skill_authorized(name: str, provider: AuthorizationProvider | None, principal: Principal | None) -> bool:
    if getattr(provider, "requires_skill_authorization", False) is not True:
        return True
    if provider is None or principal is None:
        return False
    try:
        return provider.authorize(AuthzRequest(principal, "skill", "activate", name)).allow
    except Exception:
        return False

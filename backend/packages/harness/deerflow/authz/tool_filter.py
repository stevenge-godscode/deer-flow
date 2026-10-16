"""Convenience wrapper for Layer 1 tool authorization filtering.

Combines provider resolution, Principal construction, and tool filtering into
a single call so the three assembly paths (lead agent, subagent, embedded
client) stay one-liners.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.tools import BaseTool

from deerflow.authz.enforcement import filter_tools_by_authorization
from deerflow.authz.principal import build_principal_from_context
from deerflow.authz.provider import AuthorizationProvider
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.app_config import AppConfig


def apply_tool_authorization(
    tools: list[BaseTool],
    *,
    context: Mapping[str, Any],
    app_config: AppConfig,
    authorization_provider: AuthorizationProvider | None = None,
) -> tuple[list[BaseTool], AuthorizationProvider | None]:
    """Apply Layer 1 tool authorization filtering.

    Resolves the provider (or reuses a caller-provided one so Layer 1 and
    Layer 2 share a single instance), builds a Principal from *context*, and
    filters *tools* in place by the provider's policy.

    When ``authorization.enabled`` is false, this is a no-op: returns the
    original tools and ``None``.

    Args:
        tools: Candidate tools (already skill-filtered etc.).
        context: Runtime context mapping (the merged ``cfg`` dict or an
            equivalent dict assembled from ``self.*`` fields).
        app_config: The resolved AppConfig (used for authorization settings).
        authorization_provider: An already-resolved provider, or ``None`` to
            resolve from ``app_config.authorization`` here.

    Returns:
        ``(filtered_tools, provider)`` — the filtered tool list and the
        provider instance (for passing to Layer 2 middleware wiring, or
        ``None`` when authorization is disabled).
    """
    authz_config = app_config.authorization
    # Guard against Mock objects in tests: MagicMock attribute access returns
    # a truthy child mock for ``enabled``, which would trigger provider
    # resolution on a non-string ``provider.use``. Real AuthorizationConfig
    # has ``enabled: bool``; if it's not actually ``True``, skip.
    if authz_config.enabled is not True:
        return tools, None

    if authorization_provider is None:
        authorization_provider = resolve_authorization_provider(authz_config)

    if authorization_provider is None:
        return tools, None

    principal = build_principal_from_context(context, default_role=authz_config.default_role)
    filtered = filter_tools_by_authorization(
        tools,
        provider=authorization_provider,
        principal=principal,
        fail_closed=authz_config.fail_closed,
    )
    return filtered, authorization_provider


def resolve_skill_authorization(names: list[str], *, context: Mapping[str, Any], app_config: AppConfig) -> tuple[list[str], bool]:
    """Return admitted names and whether a physical projection is mandatory."""
    authz_config = app_config.authorization
    if authz_config.enabled is not True:
        return names, False
    provider = resolve_authorization_provider(authz_config)
    if getattr(provider, "requires_skill_authorization", False) is not True:
        return names, False
    try:
        principal = build_principal_from_context(context, default_role=authz_config.default_role)
        allowed = provider.filter_resources(principal, "skill", names)
        if not isinstance(allowed, list) or any(not isinstance(name, str) for name in allowed):
            return [], True
        permitted = set(allowed)
        return [name for name in names if name in permitted], True
    except Exception:
        return [], True


def filter_skill_names(names: list[str], *, context: Mapping[str, Any], app_config: AppConfig) -> list[str]:
    """Compatibility wrapper for callers that only need admitted names."""
    return resolve_skill_authorization(names, context=context, app_config=app_config)[0]

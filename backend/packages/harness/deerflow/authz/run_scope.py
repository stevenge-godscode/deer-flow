"""Server-only authorization attributes after native project admission."""

from __future__ import annotations

import asyncio
import json

from deerflow.authz.principal import normalize_authz_attributes
from deerflow.authz.runtime import construct_authorization_provider, resolve_authorization_provider_spec
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY


async def bind_run_authorization_attributes(config: dict, authorization_config=None, *, provider=None, project_context=None) -> None:
    # Apply to both client-writable carriers, including authenticated internal
    # launches. A producer never receives or preserves caller-supplied proof.
    for section in ("context", "configurable"):
        config.setdefault(section, {}).pop("authz_attributes", None)
        config[section].pop(PROJECT_CONTEXT_KEY, None)
    if project_context is not None:
        config["context"][PROJECT_CONTEXT_KEY] = project_context
    if provider is None:
        if authorization_config is None or authorization_config.enabled is not True:
            return
        spec = await asyncio.to_thread(resolve_authorization_provider_spec, authorization_config)
        provider = construct_authorization_provider(spec, authorization_config)
    producer = getattr(provider, "prepare_run_attributes", None)
    if not callable(producer):
        return
    admitted_context = dict(config["context"])
    # Match lead_agent._get_runtime_config: an explicit context value wins;
    # only Agent selection/mode may fall back to legacy configurable. Identity
    # and project proof never fall back to that client-writable carrier.
    for key in ("agent_name", "is_bootstrap"):
        if key not in admitted_context and key in config["configurable"]:
            admitted_context[key] = config["configurable"][key]
            config["context"][key] = admitted_context[key]
    attributes = normalize_authz_attributes(await asyncio.to_thread(producer, admitted_context))
    # Runtime persistence must contain portable data, never executable objects.
    attributes = json.loads(json.dumps(attributes, allow_nan=False))
    config["context"]["authz_attributes"] = attributes
    config["configurable"]["authz_attributes"] = json.loads(json.dumps(attributes))


def _background_authorization_config():
    from deerflow.config import get_app_config

    return get_app_config().authorization


async def require_background_capability_admission() -> None:
    """Do not run durable raw calls with an unproven lead-only scope.

    Background status/cancel and alternate drivers do not carry an admitted
    project/Agent execution subject. Their admission needs a durable contract;
    a user's server credential and copied parent attributes are insufficient.
    """
    config = await asyncio.to_thread(_background_authorization_config)
    if config.enabled is not True:
        return
    spec = await asyncio.to_thread(resolve_authorization_provider_spec, config)
    provider = construct_authorization_provider(spec, config)
    if getattr(provider, "requires_run_scope", False) is True:
        raise PermissionError("Durable capability execution requires separate scope admission")

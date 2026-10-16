"""Published Agent definition references, using the existing AgentStore."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from deerflow.config.agents_config import validate_agent_name
from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY, AGENT_DEFINITION_DIGEST_METADATA_KEY, AGENT_DEFINITION_METADATA_KEY

if TYPE_CHECKING:
    from deerflow.config.agents_config import AgentConfig
    from deerflow.persistence.agents.base import AgentDefinitionSnapshot


_REFERENCE_SCHEMA = "deerflow.agent-definition-ref/v1"


def validate_agent_definition_reference(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"schema", "name", "digest"}:
        raise ValueError("Invalid published Agent definition reference")
    if value["schema"] != _REFERENCE_SCHEMA or not isinstance(value["name"], str) or not value["name"] or not isinstance(value["digest"], str):
        raise ValueError("Invalid published Agent definition reference")
    if validate_agent_name(value["name"]) != value["name"] or len(value["digest"]) != 64 or any(c not in "0123456789abcdef" for c in value["digest"]):
        raise ValueError("Invalid published Agent definition identity")
    return dict(value)


async def bind_agent_definition_reference(config: dict, metadata: dict, *, user_id: str | None, store=None, expected_reference=None) -> None:
    """Overwrite both input carriers and public metadata with server proof."""
    for section in ("context", "configurable"):
        config.setdefault(section, {}).pop(AGENT_DEFINITION_CONTEXT_KEY, None)
    metadata.pop(AGENT_DEFINITION_METADATA_KEY, None)
    metadata.pop(AGENT_DEFINITION_DIGEST_METADATA_KEY, None)
    # Match the native factory's selector/mode precedence only. Identity is the
    # explicit authenticated owner supplied by admission, never configurable.
    selector = {**config["configurable"], **config["context"]}
    name = selector.get("agent_name")
    expected = validate_agent_definition_reference(expected_reference) if expected_reference is not None else None
    if expected is not None and (selector.get("is_bootstrap") or name != expected["name"]):
        raise ValueError("Published Agent definition identity mismatch")
    if not name:
        return
    name = validate_agent_name(name)

    def resolve():
        from deerflow.persistence.agents import get_agent_store

        selected_store = store if store is not None else get_agent_store()
        if not selected_store.exists(name, user_id=user_id):
            return None
        snapshot = selected_store.get_definition_snapshot(name, user_id=user_id)
        if not snapshot.config.immutable_definition:
            return None
        return {"schema": _REFERENCE_SCHEMA, "name": snapshot.config.name, "digest": snapshot.digest}

    reference = await asyncio.to_thread(resolve)
    if reference is not None and selector.get("is_bootstrap"):
        raise ValueError("Published Agent definitions cannot execute in bootstrap mode")
    if expected is not None and reference != expected:
        raise ValueError("Published Agent definition identity mismatch")
    if reference is None:
        return
    metadata[AGENT_DEFINITION_METADATA_KEY] = dict(reference)
    config["context"][AGENT_DEFINITION_CONTEXT_KEY] = dict(reference)
    config["configurable"][AGENT_DEFINITION_CONTEXT_KEY] = dict(reference)


def resolve_agent_definition_snapshot(name: str | None, config: AgentConfig | None, *, user_id: str | None, reference=None, store=None) -> AgentDefinitionSnapshot | None:
    """Read one immutable body and reject missing/replaced recovery versions."""
    if reference is None and getattr(config, "immutable_definition", False) is not True:
        return None
    expected = validate_agent_definition_reference(reference) if reference is not None else None
    if not name or (expected is not None and expected["name"] != name):
        raise ValueError("Published Agent definition identity mismatch")
    from deerflow.persistence.agents import get_agent_store

    selected_store = store if store is not None else get_agent_store()
    try:
        snapshot = selected_store.get_definition_snapshot(name, user_id=user_id)
    except (OSError, ValueError) as exc:
        raise ValueError("Published Agent definition identity is unavailable") from exc
    if not snapshot.config.immutable_definition or (expected is not None and snapshot.digest != expected["digest"]):
        raise ValueError("Published Agent definition identity mismatch")
    return snapshot

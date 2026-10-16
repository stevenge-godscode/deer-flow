"""Private runtime context keys shared across DeerFlow runtime components."""

from collections.abc import Mapping
from typing import Final

CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: Final[str] = "__deerflow_pre_run_message_ids"

# Server-authored checkpoint metadata that binds materialized state to the
# agent policy which produced it. The sentinel is intentionally not a valid
# custom-agent name, so a missing/invalid legacy value cannot be confused with
# the default agent and accidentally authorize a memory write.
CHECKPOINT_AGENT_NAME_METADATA_KEY: Final[str] = "deerflow_agent_name"
DEFAULT_AGENT_NAME_METADATA_VALUE: Final[str] = "__default__"

# Server-owned pinned project snapshot for a run, resolved once at admission
# (spec §7.1). Holds ``{project_id, name, instructions, shelf, shelf_hash}``.
# Clients can never supply it: it is popped from both run-config sections at
# Gateway admission and refused by the run worker's runtime-context merge.
PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"

# Only a small server-authored immutable definition reference travels with a
# durable run. The definition body remains in the owner-scoped AgentStore.
AGENT_DEFINITION_CONTEXT_KEY: Final[str] = "__deerflow_agent_definition_ref"
AGENT_DEFINITION_METADATA_KEY: Final[str] = "deerflow_agent_definition_ref"
AGENT_DEFINITION_DIGEST_METADATA_KEY: Final[str] = "deerflow_agent_definition_digest"


def checkpoint_agent_binding_metadata(metadata: object) -> dict[str, str]:
    """Copy a checkpoint's server-authored agent binding for a state rewrite.

    Callers must pass persisted checkpoint metadata, never request metadata.
    Missing or malformed values remain unbound so memory writes fail closed.
    """
    if not isinstance(metadata, Mapping):
        return {}
    value = metadata.get(CHECKPOINT_AGENT_NAME_METADATA_KEY)
    if not isinstance(value, str) or not value:
        return {}
    result = {CHECKPOINT_AGENT_NAME_METADATA_KEY: value}
    digest = metadata.get(AGENT_DEFINITION_DIGEST_METADATA_KEY)
    if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
        result[AGENT_DEFINITION_DIGEST_METADATA_KEY] = digest
    return result

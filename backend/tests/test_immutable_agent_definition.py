"""Synthetic definition publication: no model or network calls."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import create_engine

from deerflow.config.agents_config import AgentConfig
from deerflow.config.paths import Paths
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base


@pytest.fixture(params=["file", "db"])
def definition_store(request, tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.persistence.agents.sql.get_paths", lambda: paths)
    if request.param == "file":
        return FileAgentStore(), paths
    url = f"sqlite:///{tmp_path}/agents.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=[AgentRow.__table__])
    engine.dispose()
    return SqlAgentStore(url), paths


def definition():
    return {"name": "method-v1", "model": "synthetic-flash", "skills": ["method-v1"], "skill_body_sha256": {"method-v1": hashlib.sha256(b"synthetic skill").hexdigest()}, "immutable_definition": True, "memory_enabled": False}


def test_published_definition_is_one_config_soul_snapshot(definition_store):
    store, _ = definition_store
    store.create("method-v1", definition(), "Version one soul", user_id="owner-a")
    snapshot = store.get_definition_snapshot("method-v1", user_id="owner-a")
    assert snapshot.config.immutable_definition is True
    assert snapshot.config.memory_enabled is False
    assert snapshot.soul == "Version one soul"
    assert len(snapshot.digest) == 64
    assert store.get("method-v1", user_id="owner-a") == snapshot.config
    assert store.get_soul("method-v1", user_id="owner-a") == snapshot.soul


def test_all_store_mutations_cannot_overwrite_or_remove_published_definition(definition_store):
    store, _ = definition_store
    from deerflow.persistence.agents.base import ImmutableAgentDefinitionError

    store.create("method-v1", definition(), "Version one soul", user_id="owner-a")
    original = store.get_definition_snapshot("method-v1", user_id="owner-a")
    for config, soul in [(None, "new soul"), ({"name": "method-v1", "immutable_definition": False}, None), ({"name": "method-v1"}, "new")]:
        with pytest.raises(ImmutableAgentDefinitionError):
            store.update("method-v1", config, soul, user_id="owner-a")
    with pytest.raises(ImmutableAgentDefinitionError):
        store.delete("method-v1", user_id="owner-a")
    assert store.get_definition_snapshot("method-v1", user_id="owner-a").digest == original.digest


def test_legacy_mutable_definition_keeps_existing_edit_behavior(definition_store):
    store, _ = definition_store
    store.create("legacy", {"name": "legacy"}, "first", user_id="owner-a")
    store.update("legacy", {"name": "legacy", "description": "updated"}, "second", user_id="owner-a")
    assert store.get("legacy", user_id="owner-a").description == "updated"
    assert store.get_soul("legacy", user_id="owner-a") == "second"


@pytest.mark.parametrize("change", [{"skills": None}, {"skill_body_sha256": {}}, {"skill_body_sha256": {"method-v1": "not-sha"}}, {"skill_body_sha256": {"other": "a" * 64}}])
def test_published_skill_body_map_must_exactly_cover_selected_skills(change):
    with pytest.raises(ValueError):
        AgentConfig(**{**definition(), **change})


def test_file_publication_canonical_missing_or_corrupt_never_falls_back(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)
    store = FileAgentStore()
    store.create("method-v1", definition(), "original soul", user_id="owner-a")
    canonical = paths.user_agent_dir("owner-a", "method-v1") / "definition.json"
    assert canonical.is_file()
    original = canonical.read_bytes()
    canonical.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        store.get_definition_snapshot("method-v1", user_id="owner-a")
    canonical.unlink()
    with pytest.raises(ValueError):
        store.get_definition_snapshot("method-v1", user_id="owner-a")
    canonical.write_bytes(original)
    assert store.get_soul("method-v1", user_id="owner-a") == "original soul"


def test_published_file_uses_canonical_definition_not_compatibility_mirrors(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr("deerflow.config.agents_config.get_paths", lambda: paths)
    store = FileAgentStore()
    store.create("method-v1", definition(), "original soul", user_id="owner-a")
    agent_dir = paths.user_agent_dir("owner-a", "method-v1")
    (agent_dir / "SOUL.md").write_text("stale compatibility mirror", encoding="utf-8")
    assert store.get_definition_snapshot("method-v1", user_id="owner-a").soul == "original soul"
    assert store.get_soul("method-v1", user_id="owner-a") == "original soul"


@pytest.mark.asyncio
async def test_native_api_creates_and_reports_one_immutable_definition(definition_store, monkeypatch):
    from types import SimpleNamespace

    import app.gateway.routers.agents as api

    store, _ = definition_store
    monkeypatch.setattr(api, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(api, "get_effective_user_id", lambda: "owner-a")
    monkeypatch.setattr(api, "get_agent_store", lambda: store)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: store)
    monkeypatch.setattr(api, "_validate_model_exists", lambda model: None)
    response = await api.create_agent_endpoint(api.AgentCreateRequest(**definition(), soul="published soul"))
    assert response.immutable_definition is True
    assert response.skill_body_sha256 == definition()["skill_body_sha256"]
    assert response.definition_digest == store.get_definition_snapshot("method-v1", user_id="owner-a").digest
    assert response.soul == "published soul"


@pytest.mark.asyncio
async def test_native_api_cannot_change_delete_or_cancel_memory_for_published_definition(definition_store, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi import HTTPException

    import app.gateway.routers.agents as api

    store, _ = definition_store
    store.create("method-v1", definition(), "published soul", user_id="owner-a")
    monkeypatch.setattr(api, "get_agents_api_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(api, "get_effective_user_id", lambda: "owner-a")
    monkeypatch.setattr(api, "get_agent_store", lambda: store)
    monkeypatch.setattr("deerflow.persistence.agents.get_agent_store", lambda: store)
    cancel = Mock()
    monkeypatch.setattr(api, "_cancel_pending_memory_for_agent", cancel)
    for change in [{"description": "changed"}, {"soul": "changed"}]:
        with pytest.raises(HTTPException) as error:
            await api.update_agent("method-v1", api.AgentUpdateRequest(**change))
        assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        await api.delete_agent("method-v1")
    assert error.value.status_code == 409
    cancel.assert_not_called()


@pytest.mark.asyncio
async def test_definition_reference_is_server_authored_and_contains_no_body(definition_store):
    from deerflow.config.definition_snapshot import bind_agent_definition_reference
    from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY, AGENT_DEFINITION_METADATA_KEY

    store, _ = definition_store
    store.create("method-v1", definition(), "private synthetic soul", user_id="owner-a")
    config = {"context": {"agent_name": "method-v1", AGENT_DEFINITION_CONTEXT_KEY: {"digest": "forged"}}, "configurable": {AGENT_DEFINITION_CONTEXT_KEY: {"digest": "forged"}}}
    metadata = {AGENT_DEFINITION_METADATA_KEY: {"digest": "forged"}}
    await bind_agent_definition_reference(config, metadata, user_id="owner-a", store=store)
    ref = metadata[AGENT_DEFINITION_METADATA_KEY]
    assert set(ref) == {"schema", "name", "digest"}
    assert ref["digest"] == store.get_definition_snapshot("method-v1", user_id="owner-a").digest
    assert ref == config["context"][AGENT_DEFINITION_CONTEXT_KEY]
    assert "private synthetic soul" not in json.dumps(metadata)


@pytest.mark.asyncio
async def test_unpublished_and_default_agents_never_preserve_forged_reference(definition_store):
    from deerflow.config.definition_snapshot import bind_agent_definition_reference
    from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY, AGENT_DEFINITION_METADATA_KEY

    store, _ = definition_store
    store.create("legacy", {"name": "legacy"}, "legacy soul", user_id="owner-a")
    for name in [None, "legacy"]:
        config = {"context": {"agent_name": name, AGENT_DEFINITION_CONTEXT_KEY: {"digest": "forged"}}, "configurable": {AGENT_DEFINITION_CONTEXT_KEY: {"digest": "forged"}}}
        metadata = {AGENT_DEFINITION_METADATA_KEY: {"digest": "forged"}}
        await bind_agent_definition_reference(config, metadata, user_id="owner-a", store=store)
        assert AGENT_DEFINITION_CONTEXT_KEY not in config["context"]
        assert AGENT_DEFINITION_CONTEXT_KEY not in config["configurable"]
        assert AGENT_DEFINITION_METADATA_KEY not in metadata


def test_resumed_definition_uses_expected_digest_and_never_reselects(definition_store):
    from deerflow.config.definition_snapshot import resolve_agent_definition_snapshot

    store, _ = definition_store
    store.create("method-v1", definition(), "published soul", user_id="owner-a")
    snapshot = store.get_definition_snapshot("method-v1", user_id="owner-a")
    ref = {"schema": "deerflow.agent-definition-ref/v1", "name": "method-v1", "digest": snapshot.digest}
    actual = resolve_agent_definition_snapshot("method-v1", snapshot.config, user_id="owner-a", reference=ref, store=store)
    assert actual.digest == snapshot.digest
    with pytest.raises(ValueError, match="identity"):
        resolve_agent_definition_snapshot("method-v1", snapshot.config, user_id="owner-a", reference={**ref, "digest": "a" * 64}, store=store)
    with pytest.raises(ValueError):
        resolve_agent_definition_snapshot("method-v1", snapshot.config, user_id="owner-b", reference=ref, store=store)


def test_worker_restores_only_the_persisted_server_definition_reference():
    from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY, AGENT_DEFINITION_DIGEST_METADATA_KEY, AGENT_DEFINITION_METADATA_KEY
    from deerflow.runtime.runs.worker import _pin_admission_agent_definition

    reference = {"schema": "deerflow.agent-definition-ref/v1", "name": "method-v1", "digest": "a" * 64}
    context = {"agent_name": "forged-name"}
    config = {"metadata": {AGENT_DEFINITION_DIGEST_METADATA_KEY: "forged-digest"}}
    _pin_admission_agent_definition({AGENT_DEFINITION_METADATA_KEY: reference}, context, config)
    assert context["agent_name"] == "method-v1"
    assert context[AGENT_DEFINITION_CONTEXT_KEY] == reference
    assert config["metadata"][AGENT_DEFINITION_DIGEST_METADATA_KEY] == "a" * 64
    assert "soul" not in context[AGENT_DEFINITION_CONTEXT_KEY]


def test_worker_legacy_run_drops_forged_definition_digest():
    from deerflow.runtime.context_keys import AGENT_DEFINITION_DIGEST_METADATA_KEY
    from deerflow.runtime.runs.worker import _pin_admission_agent_definition

    config = {"metadata": {AGENT_DEFINITION_DIGEST_METADATA_KEY: "forged-digest"}}
    _pin_admission_agent_definition({}, {}, config)
    assert AGENT_DEFINITION_DIGEST_METADATA_KEY not in config["metadata"]


def test_sql_delete_does_not_delete_concurrent_new_definition(definition_store, monkeypatch):
    store, _ = definition_store
    if not isinstance(store, SqlAgentStore):
        return
    original_row = store._row
    inserted = False

    def race(session, name, user_id):
        nonlocal inserted
        row = original_row(session, name, user_id)
        if not inserted:
            inserted = True
            store.create("method-v1", definition(), "new published soul", user_id="owner-a")
        return row

    monkeypatch.setattr(store, "_row", race)
    assert store.delete("method-v1", user_id="owner-a") == "missing"
    assert store.get_definition_snapshot("method-v1", user_id="owner-a").soul == "new published soul"


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [True, False])
async def test_checkpoint_resume_uses_trusted_definition_and_pins_checkpoint(explicit):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.gateway.services import apply_checkpoint_to_run_config
    from deerflow.runtime.context_keys import AGENT_DEFINITION_DIGEST_METADATA_KEY, CHECKPOINT_AGENT_NAME_METADATA_KEY

    metadata = {CHECKPOINT_AGENT_NAME_METADATA_KEY: "method-v1", AGENT_DEFINITION_DIGEST_METADATA_KEY: "a" * 64}
    saved = SimpleNamespace(config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "saved-1"}}, metadata=metadata)
    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=saved))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer)))
    body = SimpleNamespace(checkpoint=None, checkpoint_id="saved-1" if explicit else None, command={"resume": "continue"})
    config = {"configurable": {"thread_id": "thread-1"}, "metadata": {AGENT_DEFINITION_DIGEST_METADATA_KEY: "forged"}}
    expected = await apply_checkpoint_to_run_config(config, body=body, thread_id="thread-1", request=request)
    assert expected == {"schema": "deerflow.agent-definition-ref/v1", "name": "method-v1", "digest": "a" * 64}
    assert config["configurable"]["checkpoint_id"] == "saved-1"


@pytest.mark.asyncio
async def test_normal_new_turn_does_not_bind_previous_definition():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.gateway.services import apply_checkpoint_to_run_config

    checkpointer = SimpleNamespace(aget_tuple=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer)))
    result = await apply_checkpoint_to_run_config({}, body=SimpleNamespace(checkpoint=None, checkpoint_id=None, command=None), thread_id="thread-1", request=request)
    assert result is None
    checkpointer.aget_tuple.assert_not_called()


@pytest.mark.asyncio
async def test_admission_resume_digest_mismatch_and_bootstrap_never_reselect(definition_store):
    from deerflow.config.definition_snapshot import bind_agent_definition_reference

    store, _ = definition_store
    store.create("method-v1", definition(), "published soul", user_id="owner-a")
    expected = {"schema": "deerflow.agent-definition-ref/v1", "name": "method-v1", "digest": "a" * 64}
    for mode in [{}, {"is_bootstrap": True}]:
        with pytest.raises(ValueError):
            await bind_agent_definition_reference({"context": {"agent_name": "method-v1", **mode}}, {}, user_id="owner-a", store=store, expected_reference=expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["nested", "flat", "map"])
async def test_all_consumed_checkpoint_carriers_are_bound(carrier):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.gateway.services import apply_checkpoint_to_run_config
    from deerflow.runtime.context_keys import AGENT_DEFINITION_DIGEST_METADATA_KEY, CHECKPOINT_AGENT_NAME_METADATA_KEY

    metadata = {CHECKPOINT_AGENT_NAME_METADATA_KEY: "method-v1", AGENT_DEFINITION_DIGEST_METADATA_KEY: "a" * 64}
    cp = SimpleNamespace(config={"configurable": {"checkpoint_id": "old-1", "checkpoint_ns": ""}}, metadata=metadata)
    reader = SimpleNamespace(aget_tuple=AsyncMock(return_value=cp))
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=reader)))
    selector = {"checkpoint_map": {"": "old-1"}} if carrier == "map" else {"checkpoint_id": "old-1"}
    config = {"configurable": selector} if carrier != "flat" else dict(selector)
    ref = await apply_checkpoint_to_run_config(config, body=SimpleNamespace(checkpoint=None, checkpoint_id=None, command=None), thread_id="t", request=req)
    assert ref["digest"] == "a" * 64
    assert config["configurable"]["checkpoint_id"] == "old-1"
    assert "checkpoint_id" not in config
    assert reader.aget_tuple.await_count == 1


@pytest.mark.asyncio
async def test_conflicting_checkpoint_carriers_reject_before_read():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.gateway.services import apply_checkpoint_to_run_config

    reader = SimpleNamespace(aget_tuple=AsyncMock())
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=reader)))
    with pytest.raises(HTTPException) as error:
        await apply_checkpoint_to_run_config({"checkpoint_id": "forged", "configurable": {"checkpoint_id": "old"}}, body=SimpleNamespace(checkpoint=None, checkpoint_id=None, command=None), thread_id="t", request=req)
    assert error.value.status_code == 400
    reader.aget_tuple.assert_not_called()


@pytest.mark.asyncio
async def test_flat_foreign_thread_cannot_override_authorized_checkpoint_thread():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.gateway.services import apply_checkpoint_to_run_config

    reader = SimpleNamespace(aget_tuple=AsyncMock())
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(checkpointer=reader)))
    with pytest.raises(HTTPException) as error:
        await apply_checkpoint_to_run_config(
            {"thread_id": "other-thread", "checkpoint_id": "foreign-checkpoint", "configurable": {"thread_id": "authorized-thread"}},
            body=SimpleNamespace(checkpoint=None, checkpoint_id=None, command=None),
            thread_id="authorized-thread",
            request=req,
        )
    assert error.value.status_code == 400
    reader.aget_tuple.assert_not_called()


def test_embedded_client_rejects_published_definitions_before_model(monkeypatch):
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    client = object.__new__(DeerFlowClient)
    client._agent_name = "method-v1"
    monkeypatch.setattr(client_module, "load_agent_config", lambda *args, **kwargs: AgentConfig(**definition()))
    with pytest.raises(ValueError, match="embedded execution is unsupported"):
        client._ensure_agent({"configurable": {"user_id": "owner-a"}})


def test_embedded_client_never_swallows_corrupt_definition(monkeypatch):
    import deerflow.client as client_module
    from deerflow.client import DeerFlowClient

    client = object.__new__(DeerFlowClient)
    client._agent_name = "method-v1"

    def corrupt(*args, **kwargs):
        raise ValueError("Published Agent definition digest mismatch")

    monkeypatch.setattr(client_module, "load_agent_config", corrupt)
    with pytest.raises(ValueError, match="digest mismatch"):
        client._ensure_agent({"configurable": {"user_id": "owner-a"}})


@pytest.mark.asyncio
async def test_published_name_cannot_bypass_definition_using_bootstrap(definition_store):
    from deerflow.config.definition_snapshot import bind_agent_definition_reference

    store, _ = definition_store
    store.create("method-v1", definition(), "published soul", user_id="owner-a")
    with pytest.raises(ValueError, match="bootstrap mode"):
        await bind_agent_definition_reference({"context": {"agent_name": "method-v1", "is_bootstrap": True}}, {}, user_id="owner-a", store=store)
    # Existing setup behavior for a fresh name is preserved.
    await bind_agent_definition_reference({"context": {"agent_name": "fresh-name", "is_bootstrap": True}}, {}, user_id="owner-a", store=store)

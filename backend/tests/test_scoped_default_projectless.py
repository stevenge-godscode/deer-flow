"""Synthetic default/projectless subjects require trusted native admission."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langgraph.store.memory import InMemoryStore

from deerflow.authz.provider import AuthorizationAdmissionDenied, AuthzDecision, AuthzRequest, Principal
from deerflow.authz.run_scope import bind_run_authorization_attributes
from deerflow.authz.scoped import ScopedAuthorizationProvider
from deerflow.persistence.thread_meta import THREAD_PROJECT_METADATA_KEY
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.projects.context import resolve_project_context

DEFAULT = "deerflow:default-agent"
PROJECTLESS = "deerflow:projectless"
MARKER = "_deerflow_admitted_projectless"


class Central:
    name = "synthetic-central"

    def authorize(self, request):
        return AuthzDecision(allow=True)

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal, resource_type, candidates):
        return list(candidates)


@pytest.fixture
def provider(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "revision": "r1",
                "grants": [
                    {
                        "id": "default",
                        "owner_id": "owner",
                        "project_id": PROJECTLESS,
                        "agent_name": DEFAULT,
                        "capabilities": [{"resource": "tool", "action": "call", "target": "read_file"}, {"resource": "sandbox", "action": "execute", "target": "default"}],
                    }
                ],
            }
        )
    )
    return ScopedAuthorizationProvider(policy_path=str(path), delegate=Central())


@pytest.mark.asyncio
async def test_true_default_projectless_is_usable_without_changing_public_agent(provider):
    config = {"context": {"user_id": "owner", "agent_name": None}, "configurable": {}}
    await bind_run_authorization_attributes(config, provider=provider, admitted_projectless=True)
    principal = Principal(user_id="owner", agent_name=None, attributes=config["context"]["authz_attributes"])
    assert provider.authorize(AuthzRequest(principal, "tool", "call", "read_file")).allow
    assert provider.authorize(AuthzRequest(principal, "sandbox", "execute", "default")).allow
    assert config["context"]["agent_name"] is None
    assert all(MARKER not in config[s] for s in ("context", "configurable"))
    assert not provider.authorize(AuthzRequest(replace(principal, agent_name=DEFAULT), "tool", "call", "read_file")).allow
    assert not provider.authorize(AuthzRequest(replace(principal, user_id="other"), "tool", "call", "read_file")).allow


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", False, 0, DEFAULT])
async def test_invalid_or_reserved_agent_never_becomes_default(provider, value):
    config = {"context": {"user_id": "owner", "agent_name": value}, "configurable": {}}
    await bind_run_authorization_attributes(config, provider=provider, admitted_projectless=True)
    p = Principal(user_id="owner", agent_name=value, attributes=config["context"]["authz_attributes"])
    assert not provider.authorize(AuthzRequest(p, "tool", "call", "read_file")).allow


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, 1, "true", None])
async def test_caller_marker_never_admits_projectless(provider, value):
    config = {"context": {"user_id": "owner", MARKER: True}, "configurable": {MARKER: True}}
    if value is not False:
        with pytest.raises(AuthorizationAdmissionDenied):
            await bind_run_authorization_attributes(config, provider=provider, admitted_projectless=value)
    else:
        await bind_run_authorization_attributes(config, provider=provider)
        p = Principal(user_id="owner", attributes=config["context"]["authz_attributes"])
        assert not provider.authorize(AuthzRequest(p, "tool", "call", "read_file")).allow
    assert all(MARKER not in config[s] for s in ("context", "configurable"))


@pytest.mark.asyncio
async def test_marker_scrubbed_even_when_disabled_and_conflicting_project_rejected(provider):
    config = {"context": {MARKER: True}, "configurable": {MARKER: True}}
    await bind_run_authorization_attributes(config)
    assert all(MARKER not in config[s] for s in ("context", "configurable"))
    with pytest.raises(AuthorizationAdmissionDenied):
        await bind_run_authorization_attributes(config, provider=provider, project_context={"project_id": "project"}, admitted_projectless=True)


@pytest.mark.asyncio
async def test_strict_resolver_distinguishes_unassigned_from_failed_lookup():
    from deerflow.projects.context import ProjectContextResolutionError

    store = MemoryThreadMetaStore(InMemoryStore())
    repo = SimpleNamespace(get=AsyncMock(return_value=None))
    await store.create("thread", user_id="owner")
    assert await resolve_project_context(store, repo, "thread", strict=True, owner_id="owner") is None
    for owner, thread in [("other", "thread"), ("owner", "missing"), (None, "thread")]:
        with pytest.raises(ProjectContextResolutionError):
            await resolve_project_context(store, repo, thread, strict=True, owner_id=owner)
    store.get = AsyncMock(side_effect=RuntimeError("synthetic DB failure"))
    with pytest.raises(ProjectContextResolutionError):
        await resolve_project_context(store, repo, "thread", strict=True, owner_id="owner")
    assert await resolve_project_context(store, repo, "thread") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, [], {THREAD_PROJECT_METADATA_KEY: ""}, {THREAD_PROJECT_METADATA_KEY: False}, {THREAD_PROJECT_METADATA_KEY: 0}, {THREAD_PROJECT_METADATA_KEY: PROJECTLESS}])
async def test_malformed_membership_never_becomes_projectless(metadata):
    from deerflow.projects.context import ProjectContextResolutionError

    store = SimpleNamespace(get=AsyncMock(return_value={"user_id": "owner", "metadata": metadata}))
    with pytest.raises(ProjectContextResolutionError):
        await resolve_project_context(store, SimpleNamespace(get=AsyncMock()), "thread", strict=True, owner_id="owner")


@pytest.mark.asyncio
async def test_owned_project_is_pinned_and_missing_or_wrong_row_denied():
    from deerflow.projects.context import ProjectContextResolutionError

    store = SimpleNamespace(get=AsyncMock(return_value={"user_id": "owner", "metadata": {THREAD_PROJECT_METADATA_KEY: "project"}}))
    repo = SimpleNamespace(get=AsyncMock(return_value={"id": "project", "status": "active", "name": "p", "instructions": "i"}))
    assert (await resolve_project_context(store, repo, "thread", strict=True, owner_id="owner"))["project_id"] == "project"
    for row in [None, {"id": "other", "status": "active"}, {"id": "project", "status": "deleted"}]:
        repo.get.return_value = row
        with pytest.raises(ProjectContextResolutionError):
            await resolve_project_context(store, repo, "thread", strict=True, owner_id="owner")


@pytest.mark.asyncio
async def test_temporary_thread_admission_is_owner_scoped_idempotent_and_not_notification_recreation():
    from app.gateway.services import _ensure_scope_thread

    store = MemoryThreadMetaStore(InMemoryStore())
    await asyncio.gather(*[_ensure_scope_thread(store, "temp", owner_id="owner", assistant_id="lead_agent", require_existing=False, freshness_check=AsyncMock()) for _ in range(8)])
    record = await store.get("temp", user_id="owner")
    assert record["user_id"] == "owner"
    await store.update_metadata("temp", {"retained": True}, user_id="owner")
    await _ensure_scope_thread(store, "temp", owner_id="owner", assistant_id="lead_agent", require_existing=False, freshness_check=AsyncMock())
    assert (await store.get("temp", user_id="owner"))["metadata"] == {"retained": True}
    for thread, owner, required in [("temp", "other", False), ("missing", "owner", True)]:
        with pytest.raises(HTTPException) as exc:
            await _ensure_scope_thread(store, thread, owner_id=owner, assistant_id="lead_agent", require_existing=required, freshness_check=AsyncMock())
        assert exc.value.status_code == 404
    assert await store.get("missing", user_id=None) is None
    assert (await store.get("temp", user_id=None))["user_id"] == "owner"


@pytest.mark.asyncio
async def test_memory_if_absent_never_erases_concurrent_membership():
    store = MemoryThreadMetaStore(InMemoryStore())
    first = await store.create("temp", user_id="owner", metadata={"retained": True})
    result = await store.create("temp", user_id="owner", if_absent=True)
    assert result["metadata"] == {"retained": True}
    assert result["incarnation"] == first["incarnation"]


@pytest.mark.asyncio
async def test_actual_memory_mode_without_project_backend_can_admit_unassigned():
    store = MemoryThreadMetaStore(InMemoryStore())
    await store.create("thread", user_id="owner")
    assert await resolve_project_context(store, None, "thread", strict=True, owner_id="owner") is None


@pytest.mark.asyncio
async def test_two_stage_scoped_thread_preserves_initial_metadata():
    from app.gateway.services import _ensure_scope_thread, _ensure_thread_metadata

    store = MemoryThreadMetaStore(InMemoryStore())
    admitted = await _ensure_scope_thread(store, "thread", owner_id="owner", assistant_id="lead_agent", require_existing=False, freshness_check=AsyncMock(), metadata={"label": "retained", "deerflow_project_id": "forged"})
    record = SimpleNamespace(thread_id="thread", assistant_id="lead_agent", metadata={"label": "retained"})
    await _ensure_thread_metadata(SimpleNamespace(thread_store=store), record, owner_user_id="owner", require_existing_thread=True, scope_thread=admitted)
    assert (await store.get("thread", user_id="owner"))["metadata"] == {"label": "retained"}


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_owner", ["other", "owner", None])
async def test_two_stage_scoped_thread_never_claims_recreated_or_unowned_rows(replacement_owner):
    from app.gateway.services import _ensure_scope_thread, _ensure_thread_metadata

    store = MemoryThreadMetaStore(InMemoryStore())
    admitted = await _ensure_scope_thread(store, "thread", owner_id="owner", assistant_id="lead_agent", require_existing=False, freshness_check=AsyncMock())
    await store.delete("thread", user_id="owner")
    replacement = await store.create("thread", user_id=replacement_owner, metadata={"replacement": True})
    record = SimpleNamespace(thread_id="thread", assistant_id="lead_agent", metadata={})
    with pytest.raises(LookupError):
        await _ensure_thread_metadata(SimpleNamespace(thread_store=store), record, owner_user_id="owner", require_existing_thread=True, scope_thread=admitted)
    after = await store.get("thread", user_id=None)
    assert after["user_id"] == replacement_owner
    assert after["incarnation"] == replacement["incarnation"]
    assert after["metadata"] == {"replacement": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_legacy_owned_null_incarnation_backfills_once_without_changing_history(tmp_path, backend):
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.services import _ensure_scope_thread
    from deerflow.persistence.thread_meta.memory import THREADS_NS
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

    engine = None
    if backend == "memory":
        store = MemoryThreadMetaStore(InMemoryStore())
    else:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "legacy.sqlite"))
        async with engine.begin() as connection:
            await connection.run_sync(ThreadMetaRow.__table__.create)
        store = ThreadMetaRepository(async_sessionmaker(engine, expire_on_commit=False))
    try:
        await store.create("legacy", user_id="owner", metadata={"retained": True})
        if backend == "memory":
            row = await store.get("legacy", user_id="owner")
            row["incarnation"] = None
            await store._store.aput(THREADS_NS, "legacy", row)
        else:
            async with store._sf() as session:
                await session.execute(update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "legacy").values(incarnation=None, updated_at=ThreadMetaRow.updated_at))
                await session.commit()
        before = await store.get("legacy", user_id="owner")
        pins = await asyncio.gather(*[_ensure_scope_thread(store, "legacy", owner_id="owner", assistant_id="lead_agent", require_existing=True) for _ in range(6)])
        assert len({pin["incarnation"] for pin in pins}) == 1
        after = await store.get("legacy", user_id="owner")
        assert {k: v for k, v in before.items() if k != "incarnation"} == {k: v for k, v in after.items() if k != "incarnation"}
        assert len(after["incarnation"]) == 32
        assert await store.ensure_incarnation("legacy", user_id="other") is None
        assert (await store.get("legacy", user_id=None)) == after
        with pytest.raises(ValueError):
            await store.ensure_incarnation("legacy", user_id=None)
    finally:
        if engine is not None:
            await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("verification_cancelled", [False, True])
async def test_actual_start_run_default_projectless_and_cancelled_metadata_gate(provider, verification_cancelled):
    from unittest.mock import patch

    from test_gateway_services import _make_start_run_request, _run_create_request

    from app.gateway.services import start_run
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.runtime import RunManager, RunStatus
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    manager = RunManager(store=MemoryRunStore())
    request = _make_start_run_request(manager)
    request.state.user = SimpleNamespace(id="owner", system_role="user")
    token = set_current_user(request.state.user)
    captured = {}

    async def observed_worker(*args, **kwargs):
        captured["config"] = kwargs["config"]
        captured["status"] = args[2].status

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    try:
        from contextlib import ExitStack

        with ExitStack() as stack:
            resolve = stack.enter_context(patch("app.gateway.services.prepare_run_authorization_provider", new=AsyncMock(return_value=provider)))
            stack.enter_context(patch("app.gateway.services.resolve_agent_factory", return_value=object()))
            stack.enter_context(patch("app.gateway.services.run_agent", side_effect=observed_worker))
            if verification_cancelled:
                stack.enter_context(patch("app.gateway.services._ensure_thread_metadata", new=AsyncMock(side_effect=asyncio.CancelledError())))
            record = await start_run(_run_create_request(metadata={"label": "retained"}), "fresh", request)
            await record.task
            assert resolve.await_count == 1
        if verification_cancelled:
            assert captured["status"] == RunStatus.error
        else:
            attributes = captured["config"]["context"]["authz_attributes"]
            principal = Principal(user_id="owner", attributes=attributes)
            assert provider.authorize(AuthzRequest(principal, "tool", "call", "read_file")).allow
            assert (await request.app.state.thread_store.get("fresh", user_id="owner"))["metadata"] == {"label": "retained"}
    finally:
        reset_current_user(token)
        reset_app_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["checkpoint", "journal", "nested-checkpoint", "nested-checkpoint-selector"])
async def test_actual_start_run_never_claims_checkpoint_only_legacy_history(provider, history):
    from unittest.mock import patch

    from test_gateway_services import _make_start_run_request, _run_create_request

    from app.gateway.services import start_run
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    manager = RunManager(store=MemoryRunStore())
    request = _make_start_run_request(manager)
    request.state.user = SimpleNamespace(id="owner", system_role="user")
    body = _run_create_request()
    if history != "journal":
        from langgraph.checkpoint.base import empty_checkpoint

        namespace = "child" if history.startswith("nested") else ""
        saved = await request.app.state.checkpointer.aput({"configurable": {"thread_id": "legacy", "checkpoint_ns": namespace}}, empty_checkpoint(), {}, {})
        if history.endswith("selector"):
            body = _run_create_request(checkpoint={"checkpoint_ns": namespace, "checkpoint_id": saved["configurable"]["checkpoint_id"]})
    else:
        request.app.state.run_event_store.list_messages = AsyncMock(return_value=[{"id": "legacy"}])
    token = set_current_user(request.state.user)
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    try:
        with (
            patch("app.gateway.services.prepare_run_authorization_provider", new=AsyncMock(return_value=provider)),
            patch("app.gateway.services.resolve_agent_factory", return_value=object()),
            patch("app.gateway.services.run_agent", new_callable=AsyncMock) as worker,
        ):
            with pytest.raises(HTTPException) as exc:
                await start_run(body, "legacy", request)
            assert exc.value.status_code == 409
            worker.assert_not_awaited()
            assert await request.app.state.thread_store.get("legacy", user_id=None) is None
    finally:
        reset_current_user(token)
        reset_app_config()

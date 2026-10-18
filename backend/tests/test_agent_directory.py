"""Published directory grants never turn personal ownership into public access."""

from types import SimpleNamespace

import pytest

from deerflow.agent_directory import AgentDirectory, DirectoryAgentStore, DirectoryConflict
from deerflow.persistence.agents.base import ImmutableAgentDefinitionError
from deerflow.persistence.agents.file import FileAgentStore


class Identity:
    def __init__(self):
        self.members = set()
        self.active = True
        self.fail = False

    def roles(self, subject):
        if self.fail:
            raise RuntimeError("identity offline")
        return {"realm/agent-directory-cmdb"} if self.active and subject in self.members else set()

    def membership(self, role, subject, enabled):
        if enabled:
            self.members.add(subject)
        else:
            self.members.discard(subject)

    def members(self, role):
        return sorted(self.members)


@pytest.fixture
def directory(tmp_path, monkeypatch):
    from deerflow.config import agents_config
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr(agents_config, "get_paths", lambda: paths)
    private = FileAgentStore()
    private.create("private", {"name": "private", "immutable_definition": True, "skills": [], "allowed_subagents": []}, "private instructions", user_id="owner")
    identity = Identity()
    users = {"alice": SimpleNamespace(id="alice", oauth_provider="realm", oauth_id="alice-sub"), "bob": SimpleNamespace(id="bob", oauth_provider="realm", oauth_id="bob-sub")}
    config = {
        "enabled": True,
        "root": str(tmp_path / "catalog"),
        "provider": "realm",
        "realm": "realm",
        "origin": "https://identity.example.test",
        "credential_file": "/not-used",
        "profiles": {"cmdb": {"label": "CMDB read only", "role": "agent-directory-cmdb", "permission_ids": ["cmdb-read"]}},
    }
    return AgentDirectory(config, private, identity=identity, user_lookup=users.get), identity, private


def publish(d):
    return d.publish("shared-v1", "owner", "private", "cmdb", actor="admin", expected_revision=0)


def test_unassigned_denied_and_private_stays_private(directory):
    d, identity, private = directory
    publish(d)
    wrapped = DirectoryAgentStore(private, d)
    assert wrapped.list(user_id="alice") == []
    assert not wrapped.exists("shared-v1", user_id="alice")
    with pytest.raises(FileNotFoundError):
        wrapped.get("shared-v1", user_id="alice")
    assert not wrapped.exists("private", user_id="alice")
    assert private.get("private", user_id="owner").name == "private"


def test_role_grant_lists_and_resolves_one_canonical_version(directory):
    d, identity, private = directory
    publish(d)
    d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    wrapped = DirectoryAgentStore(private, d)
    assert [a.name for a in wrapped.list(user_id="alice")] == ["shared-v1"]
    snap = wrapped.get_definition_snapshot("shared-v1", user_id="alice")
    assert snap.soul == "private instructions"
    assert snap.digest == d.state()["agents"]["shared-v1"]["definition"]["digest"]
    assert wrapped.list(user_id="bob") == []
    assert not private.exists("shared-v1", user_id="alice")
    with pytest.raises(ImmutableAgentDefinitionError):
        wrapped.update("shared-v1", {}, None, user_id="alice")


def test_revocation_disable_and_identity_failure_are_live(directory):
    d, identity, private = directory
    publish(d)
    d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    assert d.allowed("shared-v1", "alice")
    d.set_membership("cmdb", "alice", False, actor="admin", expected_revision=3)
    assert not d.allowed("shared-v1", "alice")
    identity.members.add("alice-sub")
    assert d.allowed("shared-v1", "alice")
    identity.active = False
    assert not d.allowed("shared-v1", "alice")
    identity.active = True
    d.set_enabled("shared-v1", False, actor="admin", expected_revision=5)
    assert not d.allowed("shared-v1", "alice")
    d.set_enabled("shared-v1", True, actor="admin", expected_revision=6)
    identity.fail = True
    assert not d.allowed("shared-v1", "alice")
    assert d.allowed("private", "alice")  # unrelated private reads need no directory authority


def test_conflicting_admin_write_cannot_lose_grant_or_republish(directory):
    d, identity, private = directory
    publish(d)
    with pytest.raises(DirectoryConflict):
        d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=0)
    assert not identity.members
    with pytest.raises(DirectoryConflict):
        d.publish("shared-v1", "owner", "private", "cmdb", actor="admin", expected_revision=1)
    assert d.state()["revision"] == 1
    assert len(d.state()["audit"]) == 1
    assert d.state()["audit"][0]["actor"] == "admin"


def test_cross_realm_and_unknown_users_cannot_be_granted(directory):
    d, identity, private = directory
    publish(d)
    with pytest.raises(ValueError):
        d.set_membership("cmdb", "unknown", True, actor="admin", expected_revision=1)
    d.user_lookup = lambda _: SimpleNamespace(id="alice", oauth_provider="other-realm", oauth_id="alice-sub")
    with pytest.raises(ValueError):
        d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    assert not identity.members


def test_mutable_source_and_private_alias_collision_rejected(directory):
    d, identity, private = directory
    private.create("draft", {"name": "draft"}, "", user_id="owner")
    with pytest.raises(ValueError):
        d.publish("shared-v1", "owner", "draft", "cmdb", actor="admin", expected_revision=0)
    with pytest.raises(DirectoryConflict):
        d.publish("private", "owner", "private", "cmdb", actor="admin", expected_revision=0)


@pytest.mark.asyncio
async def test_admission_rejects_unassigned_directory_version(directory):
    from deerflow.config.definition_snapshot import AgentDefinitionUnavailable, bind_agent_definition_reference

    d, identity, private = directory
    publish(d)
    wrapped = DirectoryAgentStore(private, d)
    with pytest.raises(AgentDefinitionUnavailable):
        await bind_agent_definition_reference({"context": {"agent_name": "shared-v1"}}, {}, user_id="alice", store=wrapped)
    d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    config = {"context": {"agent_name": "shared-v1"}}
    metadata = {}
    await bind_agent_definition_reference(config, metadata, user_id="alice", store=wrapped)
    from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY

    assert config["context"][AGENT_DEFINITION_CONTEXT_KEY]["digest"] == wrapped.get_definition_snapshot("shared-v1", user_id="alice").digest


@pytest.mark.asyncio
async def test_tool_revocation_fences_even_infrastructure_allow(directory, monkeypatch):
    import deerflow.agent_directory as module
    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.guardrails.provider import GuardrailRequest

    d, identity, private = directory
    publish(d)
    d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    monkeypatch.setattr(module, "get_directory", lambda: d)
    adapter = GuardrailAuthorizationAdapter(SimpleNamespace(), infrastructure_tool_names=["tool_search"])
    request = GuardrailRequest(tool_name="tool_search", user_id="alice", agent_name="shared-v1", tool_input={})
    assert adapter.evaluate(request).allow
    identity.members.clear()
    assert not adapter.evaluate(request).allow
    assert not (await adapter.aevaluate(request)).allow


@pytest.mark.asyncio
@pytest.mark.parametrize("source,role", [("pat", "admin"), ("internal", "admin"), ("session", "user")])
async def test_administrator_routes_require_real_admin_browser_session(source, role, monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.gateway.routers import agent_directory as routes

    user = SimpleNamespace(id="admin", system_role=role)

    async def current(request):
        return user

    async def admin(request, detail):
        if role != "admin":
            raise HTTPException(403, detail)

    monkeypatch.setattr(routes, "get_current_user_from_request", current)
    monkeypatch.setattr(routes, "require_admin_user", admin)
    request = Request({"type": "http"})
    request.state.auth_source = source
    with pytest.raises(HTTPException) as error:
        await routes._admin(request, "admin")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_stale_account_cannot_write(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.gateway.routers import agent_directory as routes

    async def current(request):
        return SimpleNamespace(id="new-admin", system_role="admin")

    async def admin(request, detail):
        pass

    monkeypatch.setattr(routes, "get_current_user_from_request", current)
    monkeypatch.setattr(routes, "require_admin_user", admin)
    request = Request({"type": "http"})
    request.state.auth_source = "session"
    with pytest.raises(HTTPException) as error:
        await routes._admin(request, "old-admin")
    assert error.value.status_code == 409


@pytest.mark.parametrize("user_enabled,global_enabled", [(False, True), (True, False), (True, True)])
def test_directory_skills_preserve_user_and_global_disable(monkeypatch, user_enabled, global_enabled):
    from pathlib import Path

    import deerflow.agent_directory as module
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
    from deerflow.skills.types import Skill, SkillCategory

    skill = Skill("managed", "read only", None, Path("/canonical/managed"), Path("/canonical/managed/SKILL.md"), Path("agent-directory/managed"), SkillCategory.INTEGRATION, enabled=True)
    storage = object.__new__(UserScopedSkillStorage)
    storage._user_id = "alice"
    monkeypatch.setattr(LocalSkillStorage, "load_skills", lambda self, enabled_only: [])
    monkeypatch.setattr(UserScopedSkillStorage, "get_skill_enabled_state", lambda self, name: user_enabled)
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda: SimpleNamespace(is_skill_enabled=lambda *args: global_enabled))
    monkeypatch.setattr(module, "get_directory", lambda: SimpleNamespace(skills=lambda user: [skill]))
    result = storage.load_skills(enabled_only=False)
    assert result[0].enabled is (user_enabled and global_enabled)
    assert bool(storage.load_skills(enabled_only=True)) is (user_enabled and global_enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disable", "revoke", "offline"])
@pytest.mark.parametrize("infrastructure", [False, True])
async def test_running_child_uses_original_directory_identity(directory, monkeypatch, failure, infrastructure):
    import deerflow.agent_directory as module
    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.authz.provider import AuthzDecision
    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.runtime.context_keys import AGENT_DEFINITION_CONTEXT_KEY

    d, identity, private = directory
    publish(d)
    d.set_membership("cmdb", "alice", True, actor="admin", expected_revision=1)
    monkeypatch.setattr(module, "get_directory", lambda: d)

    async def allow_async(request):
        return AuthzDecision(allow=True)

    provider = SimpleNamespace(authorize=lambda request: AuthzDecision(allow=True), aauthorize=allow_async)
    adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tool_names=["read_file"] if infrastructure else [])
    reference = {"schema": "deerflow.agent-definition-ref/v1", "name": "shared-v1", "digest": d.snapshot("shared-v1", "alice").digest}
    context = {"user_id": "alice", "is_subagent": True, "agent_name": "general-purpose", AGENT_DEFINITION_CONTEXT_KEY: reference}
    tool_request = SimpleNamespace(tool_call={"name": "read_file", "args": {}, "id": "child-call"}, tool=None)
    request = GuardrailMiddleware(adapter)._build_request(tool_request, context)
    assert adapter.evaluate(request).allow
    if failure == "disable":
        d.set_enabled("shared-v1", False, actor="admin", expected_revision=3)
    elif failure == "revoke":
        identity.members.clear()
    else:
        identity.fail = True
    assert not adapter.evaluate(request).allow
    assert not (await adapter.aevaluate(request)).allow


def test_conflicting_skill_publish_and_enable_are_atomic(directory, monkeypatch, tmp_path):
    import hashlib

    import deerflow.skills.storage as storage
    from deerflow.skills.parser import parse_skill_file
    from deerflow.skills.types import SkillCategory

    d, identity, private = directory

    def source(version):
        body = "---\nname: managed\ndescription: Read only\n---\n" + version
        file = tmp_path / version / "SKILL.md"
        file.parent.mkdir()
        file.write_text(body, encoding="utf-8")
        skill = parse_skill_file(file, SkillCategory.CUSTOM, file.parent)
        monkeypatch.setattr(storage, "get_or_new_user_skill_storage", lambda _: SimpleNamespace(load_skills=lambda **kw: [skill]))
        private.create(version, {"name": version, "immutable_definition": True, "skills": ["managed"], "skill_body_sha256": {"managed": hashlib.sha256(body.encode()).hexdigest()}}, "instructions", user_id="owner")

    source("v1")
    d.publish("shared-v1", "owner", "v1", "cmdb", actor="admin", expected_revision=0)
    source("v2")
    with pytest.raises(DirectoryConflict, match="skill"):
        d.publish("shared-v2", "owner", "v2", "cmdb", actor="admin", expected_revision=1)
    assert d.state()["revision"] == 1
    assert set(d.state()["agents"]) == {"shared-v1"}
    d.set_enabled("shared-v1", False, actor="admin", expected_revision=1)
    d.publish("shared-v2", "owner", "v2", "cmdb", actor="admin", expected_revision=2)
    with pytest.raises(DirectoryConflict, match="skill"):
        d.set_enabled("shared-v1", True, actor="admin", expected_revision=3)
    assert d.state()["revision"] == 3
    assert d.state()["agents"]["shared-v1"]["enabled"] is False
    identity.members.add("alice-sub")
    assert [s.name for s in d.skills("alice")] == ["managed"]


@pytest.mark.asyncio
async def test_scoped_manager_session_needs_live_role_and_never_system_admin(directory, monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.gateway.routers import agent_directory as routes

    d, identity, private = directory
    user = SimpleNamespace(id="alice", system_role="user")

    async def current(request):
        return user

    monkeypatch.setattr(routes, "get_current_user_from_request", current)
    monkeypatch.setattr(routes, "get_directory", lambda: d)
    request = Request({"type": "http"})
    request.state.auth_source = "session"
    with pytest.raises(HTTPException):
        await routes._admin(request)
    identity.roles = lambda subject: {"realm/agent-directory-manager"}
    assert await routes._admin(request, "alice") == "alice"
    assert (await routes.access(request))["can_manage"] is True
    assert user.system_role == "user"
    request.state.auth_source = "pat"
    with pytest.raises(HTTPException):
        await routes._admin(request)
    request.state.auth_source = "session"
    identity.roles = lambda subject: set()
    with pytest.raises(HTTPException):
        await routes._admin(request)
    assert (await routes.access(request))["can_manage"] is False


@pytest.mark.parametrize("invalid", [None, "oidc-disabled", "missing-provider", "auth-bypass", "authorization-disabled", "authorization-open", "missing-policy", "ephemeral-db"])
def test_directory_bootstrap_uses_real_native_auth_config(directory, monkeypatch, invalid):
    import deerflow.config.app_config as app_config
    from deerflow.agent_directory import get_directory
    from deerflow.config.app_config import AppConfig

    d, identity, private = directory
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "database": {"backend": "sqlite"},
            "authorization": {"enabled": True, "fail_closed": True, "provider": {"use": "test.Provider"}},
            "auth": {"oidc": {"enabled": True, "providers": {"realm": {"display_name": "Test", "issuer": "https://identity.example.test", "client_id": "test"}}}},
            "agent_directory": d.config.model_dump(),
        }
    )
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    if invalid == "oidc-disabled":
        config.auth.oidc.enabled = False
    if invalid == "missing-provider":
        config.auth.oidc.providers = {}
    if invalid == "auth-bypass":
        monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    if invalid == "authorization-disabled":
        config.authorization.enabled = False
    if invalid == "authorization-open":
        config.authorization.fail_closed = False
    if invalid == "missing-policy":
        config.authorization.provider = None
    if invalid == "ephemeral-db":
        config.database.backend = "memory"
    monkeypatch.setattr(app_config, "get_app_config", lambda: config)
    if invalid:
        with pytest.raises(ValueError, match="directory requires"):
            get_directory(private)
    else:
        assert get_directory(private).config.provider == "realm"


def test_directory_profile_rejects_legacy_service_credential_exception():
    from deerflow.config.agent_directory_config import DirectoryProfile

    with pytest.raises(ValueError):
        DirectoryProfile(label="CMDB", role="agent-directory-cmdb-read", permission_ids=["read"], mcp_service_auth=["cmdb-readonly"])


def test_native_editable_agent_can_be_published_without_operator_snapshot_fields(directory):
    d, identity, private = directory
    private.create("draft", {"name": "draft", "skills": [], "mcp_plugins": ["template:test-source"], "allowed_subagents": []}, "first version", user_id="owner")
    d.publish("published-draft", "owner", "draft", "cmdb", actor="owner", expected_revision=0)
    record = d.state()["agents"]["published-draft"]
    assert record["definition"]["config"]["immutable_definition"] is True
    assert record["definition"]["config"]["mcp_plugins"] == ["template:test-source"]
    private.update("draft", {}, "second version", user_id="owner")
    identity.members.add("alice-sub")
    assert d.snapshot("published-draft", "alice").soul == "first version"

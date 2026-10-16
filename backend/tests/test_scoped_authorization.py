"""Synthetic operator grants: both construction and execution fail closed."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from deerflow.authz.provider import AuthzDecision, AuthzRequest, Principal
from deerflow.authz.scoped import ScopedAuthorizationProvider
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY


class Delegate:
    name = "synthetic-central"

    def __init__(self):
        self.denied = set()
        self.calls = []

    def authorize(self, request):
        self.calls.append((request.resource, request.action, request.target))
        return AuthzDecision(allow=(request.resource, request.action, request.target) not in self.denied)

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal, resource_type, candidates):
        return list(candidates)


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "policy.json"
    caps = [
        {"resource": "tool", "action": "call", "target": "read_fact", "server_name": "source-a", "server_digest": "a" * 64},
        {"resource": "mcp_server", "action": "connect", "target": "source-a", "server_digest": "a" * 64},
        {"resource": "tool", "action": "call", "target": "read_file"},
        {"resource": "skill", "action": "activate", "target": "method-r1"},
    ]
    policy = {"version": 1, "revision": "r1", "grants": [{"id": "grant-a", "owner_id": "owner-a", "project_id": "project-a", "agent_name": "agent-a", "capabilities": caps}]}
    path.write_text(json.dumps(policy))
    delegate = Delegate()
    provider = ScopedAuthorizationProvider(policy_path=str(path), delegate=delegate)
    context = {"user_id": "owner-a", "agent_name": "agent-a", PROJECT_CONTEXT_KEY: {"project_id": "project-a"}}
    principal = Principal(user_id="owner-a", agent_name="agent-a", attributes=provider.prepare_run_attributes(context))
    request = AuthzRequest(principal, "tool", "call", "read_fact", {"mcp_source": {"server_name": "source-a", "configuration_digest": "a" * 64}})
    return path, policy, delegate, provider, context, principal, request


def test_both_layers_require_exact_scope(env):
    _, _, _, provider, _, principal, request = env
    assert provider.filter_resources(principal, "tool", ["read_fact", "ungranted"]) == ["read_fact"]
    assert provider.authorize(request).allow
    assert not provider.authorize(replace(request, principal=replace(principal, user_id="other-owner"))).allow
    assert not provider.authorize(replace(request, principal=Principal(user_id="owner-a"))).allow


@pytest.mark.parametrize("field,value", [("user_id", "other-owner"), ("agent_name", "other-agent"), (PROJECT_CONTEXT_KEY, {"project_id": "other-project"}), (PROJECT_CONTEXT_KEY, None)])
def test_admission_does_not_join_grants_across_scopes(env, field, value):
    _, _, _, provider, context, _, request = env
    principal = Principal(user_id=context["user_id"], agent_name=context["agent_name"], attributes=provider.prepare_run_attributes({**context, field: value}))
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []
    assert not provider.authorize(replace(request, principal=principal)).allow


def test_central_and_server_denial_are_not_bypassed_by_maintenance(env):
    _, _, delegate, provider, _, principal, request = env
    principal.is_internal = True
    delegate.denied.add(("mcp_server", "connect", "source-a"))
    assert not provider.authorize(request).allow
    delegate.denied.clear()
    delegate.denied.add(("tool", "call", "read_fact"))
    assert not provider.authorize(request).allow


@pytest.mark.parametrize("origin", [None, {"server_name": "source-b", "configuration_digest": "a" * 64}, {"server_name": "source-a", "configuration_digest": "b" * 64}])
def test_same_tool_name_does_not_authorize_a_different_server(env, origin):
    provider, request = env[3], env[6]
    assert not provider.authorize(replace(request, context={"mcp_source": origin})).allow


def test_live_revoke_and_new_grants_do_not_expand_pinned_run(env):
    path, policy, _, provider, _, principal, request = env
    assert provider.authorize(request).allow
    policy["revision"] = "r2"
    policy["grants"][0]["capabilities"].append({"resource": "tool", "action": "call", "target": "new_tool"})
    path.write_text(json.dumps(policy))
    assert provider.filter_resources(principal, "tool", ["read_fact", "new_tool"]) == ["read_fact"]
    policy["grants"][0]["enabled"] = False
    path.write_text(json.dumps(policy))
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []
    assert not provider.authorize(request).allow


def test_policy_read_or_validation_failure_never_reuses_stale_allow(env):
    path, _, _, provider, _, principal, request = env
    assert provider.authorize(request).allow
    path.write_text("{")
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []
    assert not provider.authorize(request).allow
    path.unlink()
    assert not provider.authorize(request).allow


def test_non_run_routes_still_delegate_and_do_not_gain_authority(env):
    _, _, delegate, provider, _, _, _ = env
    request = AuthzRequest(Principal(user_id="owner-a"), "route", "read", "route:threads:read")
    assert provider.authorize(request).allow
    delegate.denied.add(("route", "read", "route:threads:read"))
    assert not provider.authorize(request).allow


def test_skill_dependency_requires_actual_permission(env):
    _, _, delegate, provider, _, principal, _ = env
    request = AuthzRequest(principal, "tool", "call", "read_file", {"skill_name": "method-r1"})
    assert provider.authorize(request).allow
    assert not provider.authorize(replace(request, context={"skill_name": "other-method"})).allow
    delegate.denied.add(("skill", "activate", "method-r1"))
    assert not provider.authorize(request).allow


@pytest.mark.asyncio
async def test_async_path_checks_same_live_policy(env):
    path, policy, _, provider, _, _, request = env
    assert (await provider.aauthorize(request)).allow
    policy["grants"][0]["enabled"] = False
    path.write_text(json.dumps(policy))
    assert not (await provider.aauthorize(request)).allow


def test_real_tool_filter_checks_origin(env):
    from langchain_core.tools import StructuredTool

    from deerflow.authz.enforcement import filter_tools_by_authorization
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    provider, principal = env[3], env[5]
    tools = []
    for server in ["source-a", "source-b"]:
        tool = StructuredTool.from_function(lambda: "synthetic", name="read_fact", description="Synthetic source read")
        tag_mcp_tool(tool, server_name=server, transport="http", configuration_digest="a" * 64)
        tools.append(tool)
    filtered = filter_tools_by_authorization(tools, provider=provider, principal=principal, fail_closed=True)
    assert filtered == [tools[0]]


def test_guardrail_adapter_cannot_lose_origin_or_bypass_scope_for_framework(env):
    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.guardrails.provider import GuardrailRequest

    provider, principal = env[3], env[5]
    adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tool_names=["tool_search"])
    kwargs = {"user_id": principal.user_id, "agent_name": principal.agent_name, "authz_attributes": principal.attributes}
    request = GuardrailRequest("read_fact", {}, mcp_source={"server_name": "source-a", "configuration_digest": "a" * 64}, **kwargs)
    assert adapter.evaluate(request).allow
    assert not adapter.evaluate(replace(request, mcp_source={"server_name": "source-b", "configuration_digest": "a" * 64})).allow
    assert not adapter.evaluate(GuardrailRequest("tool_search", {}, **kwargs)).allow


@pytest.mark.asyncio
async def test_scope_admission_discards_client_attributes_before_server_producer(env):
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    provider, context = env[3], env[4]
    config = {"context": {**context, "authz_attributes": {"forged": True}}, "configurable": {"authz_attributes": {"forged": True}}}
    await bind_run_authorization_attributes(config, provider=provider, project_context=context[PROJECT_CONTEXT_KEY])
    assert "forged" not in config["context"]["authz_attributes"]
    principal = Principal(user_id="owner-a", agent_name="agent-a", attributes=config["context"]["authz_attributes"])
    assert provider.authorize(replace(env[6], principal=principal)).allow
    assert config["configurable"]["authz_attributes"] == config["context"]["authz_attributes"]


@pytest.mark.asyncio
async def test_missing_scope_producer_never_preserves_forged_attributes(env):
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    config = {"context": {"authz_attributes": {"forged": True}}, "configurable": {"authz_attributes": {"forged": True}}}
    await bind_run_authorization_attributes(config, provider=env[2])
    assert "authz_attributes" not in config["context"]
    assert "authz_attributes" not in config["configurable"]


def test_visibility_requires_server_permission_in_both_policies(env):
    path, policy, delegate, provider, _, principal, _ = env
    delegate.denied.add(("mcp_server", "connect", "source-a"))
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []
    delegate.denied.clear()
    policy["grants"][0]["capabilities"] = [cap for cap in policy["grants"][0]["capabilities"] if cap["resource"] != "mcp_server"]
    path.write_text(json.dumps(policy))
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []


def test_direct_server_check_requires_exact_configuration_digest(env):
    provider, principal = env[3], env[5]
    request = AuthzRequest(principal, "mcp_server", "connect", "source-a", {"mcp_source": {"server_name": "source-a", "configuration_digest": "b" * 64}})
    assert not provider.authorize(request).allow
    assert not provider.authorize(replace(request, context={})).allow


def test_malformed_central_filter_is_not_treated_as_allowed_keys(env):
    _, _, delegate, provider, _, principal, _ = env
    delegate.filter_resources = lambda *args: {"read_fact": False}
    assert provider.filter_resources(principal, "tool", ["read_fact"]) == []


def test_central_success_decision_provenance_is_preserved(env):
    delegate, provider = env[2], env[3]
    decision = AuthzDecision(True, policy_id="central-r1", metadata={"decision_id": "decision-a"})
    delegate.authorize = lambda request: decision
    request = AuthzRequest(Principal(user_id="owner-a"), "route", "read", "route:threads:read")
    assert provider.authorize(request) is decision


@pytest.mark.parametrize("version", [True, 1.0])
def test_policy_version_is_an_integer_not_bool_or_float(env, version):
    path, policy, _, provider, _, principal, request = env
    policy["version"] = version
    path.write_text(json.dumps(policy))
    assert not provider.authorize(request).allow


def test_unknown_resource_is_denied_even_when_central_allows(env):
    provider = env[3]
    request = AuthzRequest(Principal(user_id="owner-a"), "unknown-resource", "call", "anything")
    assert not provider.authorize(request).allow
    assert provider.filter_resources(request.principal, request.resource, ["anything"]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted_project", [None, {"project_id": "other-project"}])
async def test_internal_forged_project_cannot_be_signed_as_a_real_scope(env, trusted_project):
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    provider, context, request = env[3], env[4], env[6]
    config = {"context": {**context, "is_internal": True}, "configurable": {PROJECT_CONTEXT_KEY: context[PROJECT_CONTEXT_KEY]}}
    await bind_run_authorization_attributes(config, provider=provider, project_context=trusted_project)
    principal = Principal(user_id="owner-a", agent_name="agent-a", is_internal=True, attributes=config["context"]["authz_attributes"])
    assert not provider.authorize(replace(request, principal=principal)).allow
    assert PROJECT_CONTEXT_KEY not in config["configurable"]
    assert config["context"].get(PROJECT_CONTEXT_KEY) == trusted_project


def test_malformed_mcp_origin_never_downgrades_to_builtin_permission(env):
    from langchain_core.tools import StructuredTool

    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.authz.enforcement import filter_tools_by_authorization
    from deerflow.guardrails.provider import GuardrailRequest
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    provider, principal = env[3], env[5]
    tool = StructuredTool.from_function(lambda: "synthetic", name="read_file", description="Synthetic malformed MCP source")
    tag_mcp_tool(tool)
    assert filter_tools_by_authorization([tool], provider=provider, principal=principal, fail_closed=True) == []
    request = GuardrailRequest("read_file", {}, user_id=principal.user_id, authz_attributes=principal.attributes, is_mcp=True)
    assert not GuardrailAuthorizationAdapter(provider).evaluate(request).allow


@pytest.mark.parametrize("field,before,after", [("env", {"DATA_ROOT": "/a"}, {"DATA_ROOT": "/b"}), ("headers", {"X-Tenant-Id": "a"}, {"X-Tenant-Id": "b"})])
def test_server_digest_covers_route_and_tenant_configuration(field, before, after):
    from deerflow.tools.mcp_metadata import mcp_configuration_digest

    assert mcp_configuration_digest({"type": "http", field: before}) != mcp_configuration_digest({"type": "http", field: after})


@pytest.mark.asyncio
@pytest.mark.parametrize("context_agent,legacy_agent,expected", [(None, "agent-a", True), ("agent-a", "other-agent", True), ("other-agent", "agent-a", False)])
async def test_scope_and_factory_resolve_agent_carriers_consistently(env, context_agent, legacy_agent, expected):
    from deerflow.agents.lead_agent.agent import _get_runtime_config
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    provider, request = env[3], env[6]
    context = {"user_id": "owner-a"}
    if context_agent is not None:
        context["agent_name"] = context_agent
    config = {"context": context, "configurable": {"agent_name": legacy_agent, "user_id": "forged-owner"}}
    await bind_run_authorization_attributes(config, provider=provider, project_context={"project_id": "project-a"})
    effective = _get_runtime_config(config)
    principal = Principal(user_id=effective["user_id"], agent_name=effective["agent_name"], attributes=effective["authz_attributes"])
    assert provider.authorize(replace(request, principal=principal)).allow is expected
    assert effective["agent_name"] == config["context"]["authz_attributes"]["capability_scope"]["agent_name"]


@pytest.mark.parametrize("tool,args", [("read_file", {"path": "/mnt/skills/custom/other-method/SKILL.md"}), ("read_file", {"path": "/mnt/skills/custom/../public/other-method/SKILL.md"})])
def test_native_skill_body_read_requires_skill_grant(env, tool, args):
    provider, principal = env[3], env[5]
    assert not provider.authorize(AuthzRequest(principal, "tool", "call", tool, {"tool_input": args})).allow
    assert provider.authorize(AuthzRequest(principal, "tool", "call", "read_file", {"tool_input": {"path": "/mnt/skills/custom/method-r1/SKILL.md"}})).allow
    assert provider.authorize(AuthzRequest(principal, "tool", "call", "read_file", {"tool_input": {"path": "/mnt/user-data/uploads/SKILL.md"}})).allow


def test_skill_visibility_uses_same_provider_scope(env, monkeypatch):
    from types import SimpleNamespace

    from deerflow.authz.tool_filter import filter_skill_names

    provider, principal = env[3], env[5]
    monkeypatch.setattr("deerflow.authz.tool_filter.resolve_authorization_provider", lambda config: provider)
    config = SimpleNamespace(authorization=SimpleNamespace(enabled=True, default_role="user"))
    assert filter_skill_names(["method-r1", "other-method"], context={"user_id": "owner-a", "agent_name": "agent-a", "authz_attributes": principal.attributes}, app_config=config) == ["method-r1"]


def test_slash_and_secret_binding_recheck_current_skill_permission(env):
    from types import SimpleNamespace

    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

    path, policy, _, provider, _, principal, _ = env
    middleware = SkillActivationMiddleware(slash_source_owner_token="synthetic", authorization_provider=provider, authorization_principal=principal)
    middleware._storage = lambda: (_ for _ in ()).throw(AssertionError("Unauthorized slash must not read content"))
    failure = middleware._resolve_activation("/other-method")
    assert failure.failure_message is not None and "authorized" in failure.failure_message
    skill = SimpleNamespace(name="method-r1", enabled=True, required_secrets=("synthetic-secret-name",), secrets_autonomous=True)
    registry = {"/mnt/skills/public/method-r1/SKILL.md": skill}
    assert middleware._resolve_registry_skill(registry, next(iter(registry)), require_autonomous=True) is skill
    policy["grants"][0]["capabilities"] = [cap for cap in policy["grants"][0]["capabilities"] if cap["resource"] != "skill"]
    path.write_text(json.dumps(policy))
    assert middleware._resolve_registry_skill(registry, next(iter(registry)), require_autonomous=True) is None


def test_active_skill_policy_cannot_cache_authority_across_revocation(env):
    from pathlib import Path
    from types import SimpleNamespace

    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware
    from deerflow.skills.types import Skill, SkillCategory

    path, policy, _, provider, _, principal, _ = env
    skill = Skill(
        name="method-r1",
        description="Synthetic",
        license="MIT",
        skill_dir=Path("/tmp/synthetic"),
        skill_file=Path("/tmp/synthetic/SKILL.md"),
        relative_path=Path("method-r1"),
        category=SkillCategory.PUBLIC,
        allowed_tools=("read_fact",),
        enabled=True,
    )
    container_path = skill.get_container_file_path("/mnt/skills")
    middleware = SkillToolPolicyMiddleware(slash_source_owner_token="synthetic", authorization_provider=provider, authorization_principal=principal)
    middleware._storage = lambda: SimpleNamespace(load_skills=lambda enabled_only=False: [skill], get_container_root=lambda: "/mnt/skills")
    context = {}
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), state={"skill_context": [{"path": container_path}]})
    assert "read_fact" in middleware._allowed_names(request)
    middleware._store_policy_decision(request, ("skill_context", (container_path,)), {"read_fact"})
    policy["grants"][0]["capabilities"] = [cap for cap in policy["grants"][0]["capabilities"] if cap["resource"] != "skill"]
    path.write_text(json.dumps(policy))
    assert "read_fact" not in middleware._allowed_names(request)


def test_custom_native_skill_root_is_not_hardcoded(env):
    path, _, delegate, _, context, _, _ = env
    provider = ScopedAuthorizationProvider(policy_path=str(path), delegate=delegate, skill_root="/custom/skills")
    principal = Principal(user_id="owner-a", agent_name="agent-a", attributes=provider.prepare_run_attributes(context))
    request = AuthzRequest(principal, "tool", "call", "read_file", {"tool_input": {"path": "/custom/skills/public/other-method/SKILL.md"}})
    assert not provider.authorize(request).allow


@pytest.mark.parametrize("change", [{"is_subagent": True}, {"agent_name": "other-agent"}, {"agent_name": None}])
def test_pinned_scope_cannot_be_reused_by_another_execution_subject(env, change):
    provider, principal, request = env[3], env[5], env[6]
    # Build through the same resolver used by assembly, not a forged grant.
    from deerflow.authz.principal import build_principal_from_context

    context = {"user_id": principal.user_id, "agent_name": "agent-a", "authz_attributes": principal.attributes, **change}
    actual = build_principal_from_context(context, default_role="user")
    assert provider.filter_resources(actual, "tool", ["read_fact", "read_file"]) == []
    assert provider.filter_resources(actual, "skill", ["method-r1"]) == []
    assert not provider.authorize(replace(request, principal=actual)).allow


def test_adapter_denies_inherited_parent_scope_in_child_execution(env):
    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.guardrails.provider import GuardrailRequest

    principal = env[5]
    request = GuardrailRequest("read_fact", {}, user_id=principal.user_id, authz_attributes=principal.attributes, is_subagent=True, mcp_source={"server_name": "source-a", "configuration_digest": "a" * 64})
    assert not GuardrailAuthorizationAdapter(env[3]).evaluate(request).allow


@pytest.mark.asyncio
async def test_admitted_legacy_agent_selector_is_mirrored_into_execution_context(env):
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    config = {"context": {"user_id": "owner-a"}, "configurable": {"agent_name": "agent-a"}}
    await bind_run_authorization_attributes(config, provider=env[3], project_context={"project_id": "project-a"})
    assert config["context"]["agent_name"] == "agent-a"


@pytest.mark.parametrize("revocation", ["operator", "central"])
def test_skill_revocation_fences_every_protected_capability_not_only_skill_md(env, revocation):
    path, policy, delegate, provider, _, principal, request = env
    assert provider.authorize(request).allow
    if revocation == "operator":
        policy["grants"][0]["capabilities"] = [cap for cap in policy["grants"][0]["capabilities"] if cap["resource"] != "skill"]
        path.write_text(json.dumps(policy))
    else:
        delegate.denied.add(("skill", "activate", "method-r1"))
    # No dependency inference from path syntax: aliases and all package files
    # are fenced by the admitted authority itself, before any tool executes.
    for path_name in ["/mnt/skills/public/method-r1/references/note.md", "/mnt/user-data/alias/note.md", "/mnt/skills/public/method-r1/scripts/read.py"]:
        read = AuthzRequest(principal, "tool", "call", "read_file", {"tool_input": {"path": path_name}})
        assert not provider.authorize(read).allow
    assert provider.filter_resources(principal, "tool", ["read_file", "read_fact"]) == []
    assert not provider.authorize(request).allow


@pytest.mark.asyncio
@pytest.mark.parametrize("request_scoped", [False, True])
async def test_raw_durable_mcp_caller_cannot_connect_with_unadmitted_scope(monkeypatch, request_scoped):
    from types import SimpleNamespace

    from deerflow.authz import run_scope
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller

    monkeypatch.setattr(run_scope, "_background_authorization_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(run_scope, "resolve_authorization_provider_spec", lambda cfg: None)
    monkeypatch.setattr(run_scope, "construct_authorization_provider", lambda *a: SimpleNamespace(requires_run_scope=True))
    caller = McpTaskToolCaller.__new__(McpTaskToolCaller)
    # No extensions, pool, OAuth or connection exists: deny must precede all.
    with pytest.raises(PermissionError, match="admission"):
        await caller.call_tool(server_name="source-a", tool_name="raw-background", arguments={}, user_id="owner-a", thread_id="thread-a", request_scoped_headers=request_scoped)


@pytest.mark.asyncio
async def test_durable_submit_cannot_use_an_alternate_driver_to_bypass_admission(monkeypatch):
    from types import SimpleNamespace

    from app.mcp_tasks.service import McpTaskService
    from deerflow.authz import run_scope

    monkeypatch.setattr(run_scope, "_background_authorization_config", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(run_scope, "resolve_authorization_provider_spec", lambda cfg: None)
    monkeypatch.setattr(run_scope, "construct_authorization_provider", lambda *a: SimpleNamespace(requires_run_scope=True))
    # No driver or repository exists; neither may be reached on scope denial.
    service = McpTaskService.__new__(McpTaskService)
    with pytest.raises(PermissionError, match="admission"):
        await service.submit(driver_name="alternate-driver", request=SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,legacy_mode", [(True, False), ("true", False), ("false", False), (None, True), (None, "false")])
async def test_bootstrap_mode_never_reuses_a_lead_agent_scope(env, mode, legacy_mode):
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    context = {"user_id": "owner-a", "agent_name": "agent-a"}
    if mode is not None:
        context["is_bootstrap"] = mode
    config = {"context": context, "configurable": {"is_bootstrap": legacy_mode}}
    from deerflow.authz.provider import AuthorizationAdmissionDenied

    with pytest.raises(AuthorizationAdmissionDenied, match="Bootstrap"):
        await bind_run_authorization_attributes(config, provider=env[3], project_context={"project_id": "project-a"})
    assert "authz_attributes" not in config["context"]
    assert "authz_attributes" not in config["configurable"]


def test_scope_requires_physical_skill_projection_even_when_all_names_are_allowed(env, monkeypatch):
    from types import SimpleNamespace

    from deerflow.authz import tool_filter

    principal = env[5]
    monkeypatch.setattr(tool_filter, "resolve_authorization_provider", lambda cfg: env[3])
    names, projection_required = tool_filter.resolve_skill_authorization(
        ["method-r1"], context={"user_id": "owner-a", "agent_name": "agent-a", "authz_attributes": principal.attributes}, app_config=SimpleNamespace(authorization=SimpleNamespace(enabled=True, default_role="user"))
    )
    assert names == ["method-r1"]
    assert projection_required is True


@pytest.mark.asyncio
async def test_explicit_lead_mode_wins_over_legacy_bootstrap_selector(env):
    from deerflow.authz.principal import build_principal_from_context
    from deerflow.authz.run_scope import bind_run_authorization_attributes

    config = {"context": {"user_id": "owner-a", "agent_name": "agent-a", "is_bootstrap": False}, "configurable": {"is_bootstrap": True}}
    await bind_run_authorization_attributes(config, provider=env[3], project_context={"project_id": "project-a"})
    principal = build_principal_from_context(config["context"], default_role="user")
    assert env[3].filter_resources(principal, "tool", ["read_fact"]) == ["read_fact"]


@pytest.mark.parametrize("source", ["operator", "central"])
def test_live_fence_restores_only_original_authority_after_explicit_regrant(env, source):
    path, policy, delegate, provider, _, principal, request = env
    assert provider.authorize(request).allow
    original_caps = list(policy["grants"][0]["capabilities"])
    if source == "operator":
        policy["grants"][0]["capabilities"] = [cap for cap in original_caps if cap["resource"] != "skill"]
        path.write_text(json.dumps(policy))
    else:
        delegate.denied.add(("skill", "activate", "method-r1"))
    assert not provider.authorize(request).allow
    policy["grants"][0]["capabilities"] = original_caps + [{"resource": "tool", "action": "call", "target": "newly-granted"}]
    path.write_text(json.dumps(policy))
    delegate.denied.clear()
    assert provider.authorize(request).allow
    assert provider.filter_resources(principal, "tool", ["read_fact", "newly-granted"]) == ["read_fact"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_actual_sandbox_gate_matches_exact_scope_and_central_authority(env, monkeypatch, asynchronous):
    import asyncio
    from types import SimpleNamespace

    from deerflow.authz import sandbox_authz
    from deerflow.config.authorization_config import AuthorizationConfig
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    path, policy, delegate, provider, context, _, _ = env
    policy["grants"][0]["capabilities"].append({"resource": "sandbox", "action": "execute", "target": "default"})
    path.write_text(json.dumps(policy))
    context = {**context, "authz_attributes": provider.prepare_run_attributes(context)}
    app_config = SimpleNamespace(authorization=AuthorizationConfig(enabled=True))
    monkeypatch.setattr(sandbox_authz, "resolve_authorization_provider", lambda cfg: provider)

    def invoke():
        if asynchronous:
            return asyncio.run(sandbox_authz.authorize_sandbox_execution_async(context=context, app_config=app_config))
        return sandbox_authz.authorize_sandbox_execution(context=context, app_config=app_config)

    invoke()
    assert ("sandbox", "execute", "default") in delegate.calls
    delegate.denied.add(("sandbox", "execute", "default"))
    with pytest.raises(SandboxAuthorizationError):
        invoke()
    delegate.denied.clear()
    policy["grants"][0]["capabilities"] = [cap for cap in policy["grants"][0]["capabilities"] if cap["resource"] != "sandbox"]
    path.write_text(json.dumps(policy))
    with pytest.raises(SandboxAuthorizationError):
        invoke()


@pytest.mark.parametrize(
    "rule,allowed",
    [
        ({"allow": True}, True),
        ({"allow": "*"}, True),
        ({"allow": ["*"]}, True),
        ({"allow": ["default"]}, True),
        ({"allow": False}, False),
        ({"allow": []}, False),
        ({"allow": True, "deny": ["*"]}, False),
        ({"allow": ["default"], "deny": ["*"]}, False),
        ({"allow": ["*"], "deny": ["default"]}, False),
    ],
)
def test_sandbox_rbac_preserves_legacy_singleton_allow_and_deny(rule, allowed):
    from deerflow.authz.rbac import RbacAuthorizationProvider

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": rule}})
    request = AuthzRequest(Principal(user_id="owner-a", role="user"), "sandbox", "execute", "default")
    assert provider.authorize(request).allow is allowed
    assert provider.filter_resources(request.principal, "sandbox", ["default"]) == (["default"] if allowed else [])


def test_sandbox_legacy_alias_does_not_turn_tool_lists_into_globs():
    from deerflow.authz.rbac import RbacAuthorizationProvider

    provider = RbacAuthorizationProvider(roles={"user": {"tools": {"allow": ["*"]}}})
    assert not provider.authorize(AuthzRequest(Principal(user_id="owner-a", role="user"), "tool", "call", "read_file")).allow

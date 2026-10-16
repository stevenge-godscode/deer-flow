"""Operator-owned run capability grants, intersected with the central provider.

No business routing or workflow belongs here. Admission pins an initial set;
every execution intersects it with the current policy. User-owned Agent/skill
configuration cannot grant access. Policy files must be atomically replaced by
the operator and must not be writable by the Agent's sandbox or management API.
"""

from __future__ import annotations

import asyncio
import posixpath
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deerflow.authz.provider import AuthorizationAdmissionDenied, AuthorizationProvider, AuthzDecision, AuthzReason, AuthzRequest, Principal
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.reflection import resolve_variable
from deerflow.runtime.context_keys import PROJECT_CONTEXT_KEY

_SCOPE_KEY = "capability_scope"
_CENTRAL_RESOURCES = frozenset({"route", "model", "application"})
_ACTIONS = {"tool": "call", "skill": "activate", "mcp_server": "connect", "sandbox": "execute"}


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    resource: Literal["tool", "skill", "mcp_server", "sandbox"]
    action: str = Field(min_length=1)
    target: str = Field(min_length=1)
    server_name: str | None = None
    server_digest: str | None = None

    @field_validator("target", "server_name")
    @classmethod
    def exact_identifiers(cls, value):
        if value is not None and (not value.strip() or any(c in value for c in "*?[]")):
            raise ValueError("Capabilities require nonempty exact identifiers")
        return value

    @field_validator("server_digest")
    @classmethod
    def valid_digest(cls, value):
        if value is not None and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("Server configuration digest must be SHA-256")
        return value

    @property
    def key(self):
        return self.resource, self.action, self.target, self.server_name, self.server_digest


class ScopedGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    enabled: bool = True
    capabilities: list[Capability]


class ScopePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    revision: str = Field(min_length=1)
    grants: list[ScopedGrant]

    @field_validator("version", mode="before")
    @classmethod
    def integer_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("Policy version must be an integer")
        return value


class RunScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    owner_id: str
    project_id: str
    agent_name: str
    policy_revision: str
    grants: list[ScopedGrant]


class ScopedAuthorizationProvider:
    """Require a pinned/current exact grant AND the configured central policy."""

    name = "scoped-authorization"
    requires_run_scope = True
    requires_skill_authorization = True
    requires_tool_origin = True
    requires_infrastructure_authorization = True

    def __init__(self, *, policy_path: str, delegate: AuthorizationProvider | None = None, delegate_use: str | None = None, delegate_config: dict | None = None, skill_root: str = DEFAULT_SKILLS_CONTAINER_PATH):
        if delegate is not None and delegate_use is not None:
            raise ValueError("Specify exactly one delegate")
        if delegate is None:
            if not delegate_use:
                raise ValueError("A central authorization delegate is required")
            delegate = resolve_variable(delegate_use, expected_type=type)(**(delegate_config or {}))
        if not isinstance(delegate, AuthorizationProvider):
            raise TypeError("Delegate must implement AuthorizationProvider")
        self._delegate = delegate
        self._policy_path = Path(policy_path)
        self._skill_root = posixpath.normpath(skill_root)
        if not self._skill_root.startswith("/") or self._skill_root == "/":
            raise ValueError("A canonical absolute skill container root is required")

    def _read_policy(self) -> ScopePolicy:
        # No cached allow: an unreadable, truncated or invalid new policy denies.
        policy = ScopePolicy.model_validate_json(self._policy_path.read_bytes())
        ids = [grant.id for grant in policy.grants]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate grant identity")
        for grant in policy.grants:
            for cap in grant.capabilities:
                if cap.action != _ACTIONS[cap.resource]:
                    raise ValueError("Unsupported capability action")
                if cap.resource == "tool" and bool(cap.server_name) != bool(cap.server_digest):
                    raise ValueError("MCP tools require both server identity and configuration digest")
                if cap.resource == "mcp_server" and (not cap.server_digest or cap.server_name is not None):
                    raise ValueError("MCP server permission requires digest and target identity")
                if cap.resource in {"skill", "sandbox"} and (cap.server_name is not None or cap.server_digest is not None):
                    raise ValueError("Only MCP capabilities may carry server identity")
        return policy

    @staticmethod
    def _matches(grant: ScopedGrant, scope: RunScope) -> bool:
        return grant.enabled and (grant.owner_id, grant.project_id, grant.agent_name) == (scope.owner_id, scope.project_id, scope.agent_name)

    def prepare_run_attributes(self, context: dict) -> dict:
        """Called only after Gateway clears untrusted attrs and resolves membership."""
        policy = self._read_policy()
        project = context.get(PROJECT_CONTEXT_KEY)
        scope = RunScope(
            owner_id=str(context.get("user_id") or ""), project_id=str(project.get("project_id") or "") if isinstance(project, dict) else "", agent_name=str(context.get("agent_name") or ""), policy_revision=policy.revision, grants=[]
        )
        # Bootstrap has a different toolset and filesystem policy. A lead
        # Agent grant must never authorize that alternate execution mode.
        if context.get("is_bootstrap"):
            raise AuthorizationAdmissionDenied("Bootstrap execution requires separate capability admission")
        scope.grants = [grant for grant in policy.grants if self._matches(grant, scope)]
        return {_SCOPE_KEY: scope.model_dump()}

    @staticmethod
    def _deny(code: str, revision: str | None = None) -> AuthzDecision:
        return AuthzDecision(allow=False, reasons=[AuthzReason(code=code)], policy_id="authz:scoped", metadata={"policy_revision": revision})

    def _capabilities(self, principal: Principal):
        policy = self._read_policy()
        scope = RunScope.model_validate(principal.attributes.get(_SCOPE_KEY))
        # This grant is for the admitted lead Agent. Delegation requires its
        # own admission contract; copying a parent's attributes is not proof.
        if principal.is_subagent or principal.agent_name != scope.agent_name or not scope.owner_id or not scope.project_id or not scope.agent_name or principal.user_id != scope.owner_id:
            return policy, set()
        current = {grant.id: grant for grant in policy.grants if self._matches(grant, scope)}
        pinned_keys = set()
        capabilities = set()
        for pinned in scope.grants:
            if not self._matches(pinned, scope):
                continue
            pinned_keys.update(cap.key for cap in pinned.capabilities)
            live = current.get(pinned.id)
            if live is not None:
                # Each complete grant matches independently; never splice scopes.
                capabilities.update({cap.key for cap in pinned.capabilities} & {cap.key for cap in live.capabilities})
        # A sandbox may still contain files projected at admission. Authority
        # shrinkage fences the entire protected execution, including aliases,
        # support files and shell reads. A new run rebuilds the narrower view.
        # Knowledge already returned to the model cannot be retroactively erased.
        if not pinned_keys <= capabilities:
            return policy, set()
        for resource, action, target, _server, _digest in pinned_keys:
            if resource == "skill" and not self._delegate.authorize(AuthzRequest(principal, resource, action, target)).allow:
                return policy, set()
        return policy, capabilities

    def _scope_check(self, request: AuthzRequest, *, visibility: bool = False) -> AuthzDecision:
        if request.resource not in _ACTIONS:
            return AuthzDecision(allow=True) if request.resource in _CENTRAL_RESOURCES else self._deny("authz.unknown_resource")
        if request.context.get("is_subagent") is True:
            return self._deny("authz.delegation_not_admitted")
        try:
            policy, keys = self._capabilities(request.principal)
            origin = request.context.get("mcp_source")
            server = origin.get("server_name") if isinstance(origin, dict) else None
            digest = origin.get("configuration_digest") if isinstance(origin, dict) else None
            if request.resource == "tool" and request.context.get("is_mcp") is True and (not isinstance(server, str) or not server or not isinstance(digest, str) or len(digest) != 64):
                return self._deny("authz.mcp_origin_required", policy.revision)
            possible = [key for key in keys if key[:3] == (request.resource, request.action, request.target)]
            if visibility:
                allowed = bool(possible)
            elif request.resource == "tool":
                allowed = (request.resource, request.action, request.target, server, digest) in keys
                if server:
                    allowed = allowed and ("mcp_server", "connect", server, None, digest) in keys
            elif request.resource == "mcp_server":
                allowed = server == request.target and (request.resource, request.action, request.target, None, digest) in keys
            else:
                allowed = bool(possible)
            skill = self._skill_target(request)
            if skill:
                allowed = allowed and ("skill", "activate", skill, None, None) in keys
            if not allowed:
                return self._deny("authz.scope_denied", policy.revision)
            return AuthzDecision(allow=True, policy_id="authz:scoped", metadata={"policy_revision": policy.revision})
        except Exception:
            return self._deny("authz.scope_unavailable")

    def _skill_target(self, request: AuthzRequest) -> str | None:
        if request.resource != "tool" or request.context.get("is_mcp") is True or request.context.get("mcp_source") is not None:
            return None
        explicit = request.context.get("skill_name")
        if isinstance(explicit, str) and explicit:
            return explicit
        args = request.context.get("tool_input")
        if not isinstance(args, dict):
            return None
        if request.target in {"read_file", "read_file_tool"} and isinstance(args.get("path"), str):
            path = posixpath.normpath(args["path"])
            if path.startswith(self._skill_root + "/") and path.endswith("/SKILL.md"):
                return posixpath.basename(posixpath.dirname(path))
        if request.target == "describe_skill":
            names = [args[key] for key in ("name", "skill_name") if isinstance(args.get(key), str)]
            if len(set(names)) > 1:
                raise ValueError("Conflicting skill selector")
            return names[0] if names else None
        return None

    def _dependencies(self, request: AuthzRequest) -> list[AuthzRequest]:
        dependencies = []
        origin = request.context.get("mcp_source")
        if request.resource == "tool" and isinstance(origin, dict) and origin.get("server_name"):
            dependencies.append(AuthzRequest(request.principal, "mcp_server", "connect", origin["server_name"], request.context))
        skill = self._skill_target(request)
        if skill:
            dependencies.append(AuthzRequest(request.principal, "skill", "activate", skill, request.context))
        return dependencies

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        scope = self._scope_check(request)
        if not scope.allow:
            return scope
        decision = self._delegate.authorize(request)
        if not decision.allow:
            return decision
        for check in self._dependencies(request):
            dependency = self._delegate.authorize(check)
            if not dependency.allow:
                return dependency
        if request.resource not in _ACTIONS:
            return decision
        return AuthzDecision(allow=True, reasons=decision.reasons, policy_id=decision.policy_id, metadata={**decision.metadata, "scope_policy_revision": scope.metadata.get("policy_revision")})

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        scope = await asyncio.to_thread(self._scope_check, request)
        if not scope.allow:
            return scope
        decision = await self._delegate.aauthorize(request)
        if not decision.allow:
            return decision
        for check in self._dependencies(request):
            dependency = await self._delegate.aauthorize(check)
            if not dependency.allow:
                return dependency
        if request.resource not in _ACTIONS:
            return decision
        return AuthzDecision(allow=True, reasons=decision.reasons, policy_id=decision.policy_id, metadata={**decision.metadata, "scope_policy_revision": scope.metadata.get("policy_revision")})

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        allowed = self._delegate.filter_resources(principal, resource_type, candidates)
        if not isinstance(allowed, list) or any(not isinstance(name, str) for name in allowed):
            return []
        delegated = set(allowed)
        if resource_type not in _ACTIONS:
            return [name for name in candidates if name in delegated] if resource_type in _CENTRAL_RESOURCES else []
        try:
            _, keys = self._capabilities(principal)
        except Exception:
            return []
        visible = []
        for name in candidates:
            if name not in delegated:
                continue
            for resource, action, target, server, digest in keys:
                if (resource, action, target) != (resource_type, _ACTIONS[resource_type], name):
                    continue
                context = {}
                if server or resource == "mcp_server":
                    context["mcp_source"] = {"server_name": server or target, "configuration_digest": digest}
                if self.authorize(AuthzRequest(principal, resource, action, target, context)).allow:
                    visible.append(name)
                    break
        return visible

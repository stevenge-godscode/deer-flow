"""Operator-scoped published Agents backed by live identity roles.

The directory shares only immutable definitions and pinned single-file skills.
All conversation, memory, project and credential ownership remains the actor's.
Synchronous consumers call this off-loop, as they do the native AgentStore.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from deerflow.config.agent_directory_config import DirectoryConfig
from deerflow.config.agents_config import validate_agent_name
from deerflow.persistence.agents.base import AgentStore, ImmutableAgentDefinitionError, definition_document, snapshot_from_document
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


class DirectoryConflict(ValueError):
    """Refresh the administrator's revision before retrying a mutation."""


class IdentityDirectoryClient:
    """Realm-bound service user; never application/global administrator auth.

    Credentials stay in the mounted Secret. Responses are reduced before they
    enter a browser response. Redirects and transport exception text are suppressed.
    """

    def __init__(self, config: DirectoryConfig):
        self.config = config

    def call(self, endpoint, *, query=None, body=None):
        secret = json.loads(Path(self.config.credential_file).read_text(encoding="utf-8"))
        params = {"accessKey": secret["access_key"], "accessSecret": secret["access_secret"], **(query or {})}
        try:
            with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
                response = client.request("POST" if body is not None else "GET", self.config.origin + "/api/" + endpoint, params=params, json=body)
            if response.status_code != 200:
                raise RuntimeError("Identity directory unavailable")
            result = response.json()
            if result.get("status") != "ok":
                raise RuntimeError("Identity directory rejected the operation")
            return result.get("data")
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            raise RuntimeError("Identity directory unavailable") from None

    def user(self, subject):
        user = self.call("get-user", query={"owner": self.config.realm, "userId": subject})
        if not user or user.get("owner") != self.config.realm or user.get("id") != subject or user.get("isForbidden") or user.get("isDeleted"):
            raise ValueError("Identity account is unavailable")
        return user

    def roles(self, subject):
        user = self.user(subject)
        return {r["owner"] + "/" + r["name"] for r in user.get("roles") or [] if r.get("isEnabled") is True}

    def role(self, role):
        if role not in {p.role for p in self.config.profiles.values()}:
            raise ValueError("Unmanaged role")
        value = self.call("get-role", query={"id": self.config.realm + "/" + role})
        if not value or value.get("owner") != self.config.realm or value.get("name") != role or value.get("isEnabled") is not True:
            raise ValueError("Managed role unavailable")
        return value

    def members(self, role):
        return sorted(self.role(role).get("users") or [])

    def membership(self, role, subject, enabled):
        user = self.user(subject)
        key = self.config.realm + "/" + user["name"]
        current = self.role(role)
        users = set(current.get("users") or [])
        users.add(key) if enabled else users.discard(key)
        result = self.call("update-role", query={"id": self.config.realm + "/" + role, "columns": "users"}, body={"users": sorted(users)})
        if result != "Affected" and result is not True:
            raise RuntimeError("Identity role update was not confirmed")
        if set(self.role(role).get("users") or []) != users:
            raise RuntimeError("Identity role verification failed")


class AgentDirectory:
    def __init__(self, config, private_store, *, identity=None, user_lookup: Callable | None = None):
        from deerflow.config.paths import get_paths

        self.config = DirectoryConfig.model_validate(config)
        self.root = Path(self.config.root) if self.config.root else get_paths().base_dir / "agent-directory"
        self.private = private_store
        self.identity = identity or IdentityDirectoryClient(self.config)
        self.user_lookup = user_lookup or self._user

    @staticmethod
    def _user(user_id):
        from deerflow.config.app_config import get_app_config
        from deerflow.persistence.agents.sql import get_sync_sessionmaker
        from deerflow.persistence.user.model import UserRow

        config = get_app_config()
        if config.database.backend not in ("sqlite", "postgres"):
            return None
        with get_sync_sessionmaker(config.database.app_sync_sqlalchemy_url)() as session:
            return session.execute(select(UserRow).where(UserRow.id == user_id)).scalar_one_or_none()

    def state(self):
        try:
            value = json.loads((self.root / "catalog.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema": "deerflow.agent-directory/v1", "revision": 0, "agents": {}, "audit": []}
        if value.get("schema") != "deerflow.agent-directory/v1" or not isinstance(value.get("agents"), dict) or not isinstance(value.get("audit"), list):
            raise ValueError("Invalid published directory")
        return value

    @contextmanager
    def transaction(self, revision):
        import fcntl

        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.root / ".write.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.state()
            if revision != state["revision"]:
                raise DirectoryConflict("Directory changed; refresh and retry")
            yield state

    def commit(self, state, actor, action, details):
        state["revision"] += 1
        state["audit"].append({"revision": state["revision"], "at": datetime.now(UTC).isoformat(), "actor": actor, "action": action, **details})
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".catalog-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.root / "catalog.json")
            parent = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state["revision"]

    def subject(self, user_id):
        user = self.user_lookup(user_id)
        if user is None or user.oauth_provider != self.config.provider or not user.oauth_id:
            raise ValueError("Account must belong to the configured identity provider")
        return user.oauth_id

    def roles(self, user_id):
        try:
            return self.identity.roles(self.subject(user_id))
        except Exception:
            # Directory reads and tools must never gain access on provider failure.
            return set()

    def visible(self, user_id):
        state = self.state()
        if not state["agents"]:
            return []
        roles = self.roles(user_id)
        return [r for r in state["agents"].values() if r["enabled"] and self.config.realm + "/" + self.config.profiles[r["profile"]].role in roles]

    def allowed(self, name, user_id):
        record = self.state()["agents"].get(name)
        if record is None:
            return True
        if not record["enabled"]:
            return False
        return self.config.realm + "/" + self.config.profiles[record["profile"]].role in self.roles(user_id)

    def snapshot(self, name, user_id):
        record = self.state()["agents"].get(name)
        if record is None or not self.allowed(name, user_id):
            raise FileNotFoundError("Published Agent unavailable")
        return snapshot_from_document(record["definition"], name)

    def publish(self, name, source_owner, source_name, profile, *, actor, expected_revision):
        name = validate_agent_name(name)
        if profile not in self.config.profiles:
            raise ValueError("Unknown approved access profile")
        snapshot = self.private.get_definition_snapshot(source_name, user_id=source_owner)
        if not snapshot.config.immutable_definition or snapshot.config.skills is None:
            raise ValueError("Only immutable Agents with explicit pinned skills can be published")
        # Capture full verified bodies, never copy personal workspaces or credentials.
        bodies = {}
        if snapshot.config.skills:
            from deerflow.skills.definition import verified_skill
            from deerflow.skills.storage import get_or_new_user_skill_storage

            registry = {s.name: s for s in get_or_new_user_skill_storage(source_owner).load_skills(enabled_only=False)}
            for skill_name in snapshot.config.skills:
                skill = verified_skill(registry[skill_name], snapshot.config.skill_body_sha256)
                bodies[skill_name] = skill.skill_file.read_bytes().decode("utf-8")
                if hashlib.sha256(bodies[skill_name].encode("utf-8")).hexdigest() != snapshot.config.skill_body_sha256[skill_name]:
                    raise ValueError("Skill changed during publication")
        with self.transaction(expected_revision) as state:
            if name in state["agents"] or any(a.name == name for _, a in self.private.list_all()):
                raise DirectoryConflict("Published version name is already reserved")
            definition = definition_document({**snapshot.config.model_dump(mode="json"), "name": name}, snapshot.soul or "", name)
            state["agents"][name] = {"name": name, "profile": profile, "enabled": True, "definition": definition, "skills": bodies, "source_digest": snapshot.digest}
            return self.commit(state, actor, "publish", {"name": name, "profile": profile, "digest": definition["digest"]})

    def set_enabled(self, name, enabled, *, actor, expected_revision):
        with self.transaction(expected_revision) as state:
            if name not in state["agents"]:
                raise ValueError("Unknown published version")
            state["agents"][name]["enabled"] = enabled
            return self.commit(state, actor, "enable" if enabled else "disable", {"name": name})

    def set_membership(self, profile, user_id, enabled, *, actor, expected_revision):
        if profile not in self.config.profiles:
            raise ValueError("Unknown approved access profile")
        subject = self.subject(user_id)
        with self.transaction(expected_revision) as state:
            # Persist intent first: remote failure or process death remains auditable.
            self.commit(state, actor, "grant-request" if enabled else "revoke-request", {"profile": profile, "account": user_id})
            try:
                self.identity.membership(self.config.profiles[profile].role, subject, enabled)
            except Exception:
                self.commit(state, actor, "identity-update-failed", {"profile": profile, "account": user_id})
                raise RuntimeError("Identity role update failed; refresh before retrying") from None
            return self.commit(state, actor, "grant" if enabled else "revoke", {"profile": profile, "account": user_id})

    def skills(self, user_id):
        from dataclasses import replace

        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        result = {}
        for record in self.visible(user_id):
            for name, body in record["skills"].items():
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if record["definition"]["config"]["skill_body_sha256"].get(name) != digest:
                    raise ValueError("Directory skill body identity mismatch")
                validate_agent_name(name)
                # Immutable content-addressed source; user/thread projections copy bytes.
                target = self.root / "skills" / digest / name / "SKILL.md"
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, temp = tempfile.mkstemp(dir=target.parent)
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                            stream.write(body)
                        os.replace(temp, target)
                    finally:
                        Path(temp).unlink(missing_ok=True)
                if target.is_symlink() or target.read_bytes() != body.encode("utf-8"):
                    raise ValueError("Directory skill source changed")
                skill = parse_skill_file(target, SkillCategory.INTEGRATION, Path("agent-directory") / name)
                if skill is None or skill.name != name:
                    raise ValueError("Invalid directory skill")
                if name in result and result[name].skill_file != target:
                    raise ValueError("Conflicting published skill versions")
                result[name] = replace(skill, enabled=True)
        return list(result.values())

    def signature(self, user_id):
        records = self.visible(user_id)
        return [(r["name"], r["definition"]["digest"]) for r in records]


class DirectoryAgentStore(AgentStore):
    def __init__(self, private, directory):
        self.private, self.directory = private, directory

    def _record(self, name):
        return self.directory.state()["agents"].get(name)

    def get(self, name, *, user_id=None):
        return self.get_definition_snapshot(name, user_id=user_id).config if self._record(name) else self.private.get(name, user_id=user_id)

    def get_definition_snapshot(self, name, *, user_id=None):
        if self._record(name):
            return self.directory.snapshot(name, user_id or get_effective_user_id())
        return self.private.get_definition_snapshot(name, user_id=user_id)

    def exists(self, name, *, user_id=None):
        if self._record(name):
            return self.directory.allowed(name, user_id or get_effective_user_id())
        return self.private.exists(name, user_id=user_id)

    def get_soul(self, name, *, user_id=None):
        return self.get_definition_snapshot(name, user_id=user_id).soul if self._record(name) else self.private.get_soul(name, user_id=user_id)

    def list(self, *, user_id=None):
        records = self.directory.visible(user_id or get_effective_user_id())
        reserved = set(self.directory.state()["agents"])
        return sorted([a for a in self.private.list(user_id=user_id) if a.name not in reserved] + [snapshot_from_document(r["definition"], r["name"]).config for r in records], key=lambda a: a.name)

    def list_all(self):
        # Catalog names remain reserved even when disabled/unassigned; admission
        # must never mistake them for legacy config-only names.
        records = self.directory.state()["agents"]
        return self.private.list_all() + [("agent-directory", snapshot_from_document(r["definition"], n).config) for n, r in records.items()]

    def _writable(self, name):
        if self._record(name):
            raise ImmutableAgentDefinitionError("Published directory versions are managed by administrators")

    def create(self, name, config, soul, *, user_id=None):
        self._writable(name)
        return self.private.create(name, config, soul, user_id=user_id)

    def update(self, name, config, soul, *, user_id=None):
        self._writable(name)
        return self.private.update(name, config, soul, user_id=user_id)

    def delete(self, name, *, user_id=None):
        self._writable(name)
        return self.private.delete(name, user_id=user_id)

    def signature(self):
        return self.private.signature(), self.directory.state()["revision"]


def get_directory(private_store=None):
    from deerflow.config.app_config import get_app_config

    try:
        config = get_app_config()
    except FileNotFoundError:
        if os.getenv("DEER_FLOW_CONFIG_PATH"):
            raise
        from deerflow.config.app_config import AppConfig

        try:
            AppConfig.resolve_config_path()
        except FileNotFoundError:
            return None
        raise
    settings = getattr(config, "agent_directory", None)
    if not settings or not settings.enabled:
        return None
    if not config.auth.enabled or not config.authorization.enabled or not config.authorization.fail_closed or config.database.backend not in ("sqlite", "postgres"):
        raise ValueError("Agent directory requires authenticated durable users and fail-closed authorization")
    if private_store is None:
        from deerflow.persistence.agents import make_private_agent_store

        private_store = make_private_agent_store(config)
    return AgentDirectory(settings, private_store)

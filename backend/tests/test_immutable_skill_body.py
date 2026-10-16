"""Pinned skill bodies: synthetic bytes, no model/network."""

import hashlib
from pathlib import Path

import pytest

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory


def make_skill(tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    f = root / "SKILL.md"
    f.write_bytes(b"---\nname: method-v1\ndescription: synthetic method\nallowed-tools: Read\n---\nDo synthetic work.\n")
    return parse_skill_file(f, SkillCategory.CUSTOM, Path("pack"))


def test_body_identity_uses_exact_bytes_and_verified_metadata(tmp_path):
    from deerflow.skills.definition import verified_skill

    skill = make_skill(tmp_path)
    expected = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    checked = verified_skill(skill, expected)
    assert checked.allowed_tools == ("read_file",)
    skill.skill_file.write_bytes(skill.skill_file.read_bytes().replace(b"Read", b"Write"))
    with pytest.raises(ValueError, match="identity"):
        verified_skill(skill, expected)


def test_pinned_skill_cannot_load_unpinned_support_files(tmp_path):
    from deerflow.skills.definition import verified_skill

    skill = make_skill(tmp_path)
    expected = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    (skill.skill_dir / "script.py").write_text("changed resource")
    with pytest.raises(ValueError, match="single-file"):
        verified_skill(skill, expected)


def test_projection_hashes_actual_copy_not_source(tmp_path):
    from deerflow.skills.definition import verify_projected_skill_bodies
    from deerflow.skills.projection import SkillProjectionPaths

    skill = make_skill(tmp_path)
    expected = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    roots = {c: tmp_path / "view" / c for c in ["public", "custom", "legacy", "integrations"]}
    target = roots["custom"] / "pack"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(skill.skill_file.read_bytes())
    projection = SkillProjectionPaths(**roots)
    verify_projected_skill_bodies([skill], projection, expected)
    (target / "SKILL.md").write_text("tampered copy")
    with pytest.raises(ValueError, match="identity"):
        verify_projected_skill_bodies([skill], projection, expected)


def test_unsupported_provider_defaults_fail_closed():
    from deerflow.sandbox.sandbox_provider import SandboxProvider

    assert SandboxProvider.supports_immutable_skill_projection is False


def test_live_policy_rejects_changed_frontmatter_instead_of_widening(tmp_path):
    from types import SimpleNamespace

    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    skill = make_skill(tmp_path)
    pins = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    policy = SkillToolPolicyMiddleware(slash_source_owner_token="synthetic", available_skills={skill.name}, skill_body_sha256=pins)
    policy._storage = lambda: SimpleNamespace(load_skills=lambda **kwargs: [skill], get_container_root=lambda: "/mnt/skills")
    path = skill.get_container_file_path()
    assert "read_file" in policy._allowed_names_for_paths((path,))
    skill.skill_file.write_bytes(skill.skill_file.read_bytes().replace(b"Read", b"Write"))
    assert "write_file" not in policy._allowed_names_for_paths((path,))


def test_slash_activation_rejects_body_drift(tmp_path):
    from types import SimpleNamespace

    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

    skill = make_skill(tmp_path)
    pins = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    middleware = SkillActivationMiddleware(slash_source_owner_token="synthetic", available_skills={skill.name}, skill_body_sha256=pins)
    storage = SimpleNamespace(load_skills=lambda **kwargs: [skill], get_container_root=lambda: "/mnt/skills", get_skills_root_path=lambda: tmp_path, validate_skill_file_path=lambda path: path.resolve())
    middleware._storage = lambda: storage
    assert middleware._resolve_activation("/method-v1 task").activation is not None
    skill.skill_file.write_bytes(skill.skill_file.read_bytes().replace(b"synthetic work", b"changed work"))
    assert middleware._resolve_activation("/method-v1 task").activation is None


def test_sandbox_refuses_provider_without_readonly_body_guarantee(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deerflow.sandbox.exceptions import SandboxRuntimeError
    from deerflow.sandbox.middleware import SandboxMiddleware

    skill = make_skill(tmp_path)
    pins = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    provider = SimpleNamespace(supports_agent_skill_isolation=True, supports_immutable_skill_projection=False)
    storage = SimpleNamespace(load_skills=lambda **kwargs: [skill])
    monkeypatch.setattr("deerflow.sandbox.middleware.get_sandbox_provider", lambda: provider)
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: object())
    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda *args, **kwargs: storage)
    middleware = SandboxMiddleware(available_skills={skill.name}, skill_body_sha256=pins)
    with pytest.raises(SandboxRuntimeError, match="immutable"):
        middleware._prepare_agent_skill_projection("thread", user_id="owner")


def test_pinned_policy_bypasses_cached_model_decision(tmp_path):
    from test_skill_tool_policy_middleware import ModelRequestStub, NamedTool, StorageStub, ToolRequestStub

    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    skill = make_skill(tmp_path)
    pins = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    middleware = SkillToolPolicyMiddleware(slash_source_owner_token="synthetic", available_skills={skill.name}, skill_body_sha256=pins)
    middleware._storage = lambda: StorageStub([skill])
    state = {"skill_context": [{"path": skill.get_container_file_path()}]}
    context = {}
    middleware._filter_model_request(ModelRequestStub([NamedTool("read_file")], state=state, context=context))
    skill.skill_file.write_bytes(skill.skill_file.read_bytes().replace(b"Read", b"Write"))
    request = ToolRequestStub("write_file", state=state, context=context)
    assert "write_file" not in middleware._allowed_names(request)


def test_secret_conditions_use_verified_metadata_after_registry_drift(tmp_path):
    from dataclasses import replace

    from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
    from deerflow.skills.types import SecretRequirement

    skill = make_skill(tmp_path)
    skill.skill_file.write_bytes(skill.skill_file.read_bytes().replace(b"allowed-tools: Read", b"allowed-tools: Read\nrequired-secrets: [SYNTHETIC_SECRET]\nsecrets-autonomous: false"))
    pinned = parse_skill_file(skill.skill_file, skill.category, skill.relative_path)
    pins = {skill.name: hashlib.sha256(skill.skill_file.read_bytes()).hexdigest()}
    stale_registry = replace(pinned, secrets_autonomous=True, required_secrets=(SecretRequirement("WRONG_SECRET"),))
    middleware = SkillActivationMiddleware(slash_source_owner_token="synthetic", skill_body_sha256=pins)
    path = skill.get_container_file_path()
    assert middleware._resolve_registry_skill({path: stale_registry}, path, require_autonomous=True) is None
    actual = middleware._resolve_registry_skill({path: stale_registry}, path, require_autonomous=False)
    assert actual.required_secrets == (SecretRequirement("SYNTHETIC_SECRET"),)


def test_one_disabled_pinned_active_skill_cannot_remove_a_restriction(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware

    skill = make_skill(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_file = other_dir / "SKILL.md"
    other_file.write_text("---\nname: other-v1\ndescription: synthetic unrestricted companion\n---\nbody\n")
    other = parse_skill_file(other_file, SkillCategory.CUSTOM, Path("other"))
    pins = {s.name: hashlib.sha256(s.skill_file.read_bytes()).hexdigest() for s in [skill, other]}
    registry = [skill, other]
    policy = SkillToolPolicyMiddleware(slash_source_owner_token="synthetic", skill_body_sha256=pins)
    policy._storage = lambda: SimpleNamespace(load_skills=lambda **kwargs: registry, get_container_root=lambda: "/mnt/skills")
    paths = tuple(s.get_container_file_path() for s in registry)
    assert "write_file" not in policy._allowed_names_for_paths(paths)
    registry[0] = replace(skill, enabled=False)
    assert policy._allowed_names_for_paths(paths) is not None
    assert "write_file" not in policy._allowed_names_for_paths(paths)

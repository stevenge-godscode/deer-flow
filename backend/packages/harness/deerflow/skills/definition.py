"""Exact-byte identity for published single-file Agent skills.

Published bodies deliberately exclude resource/script packages until those
packages have their own complete manifest. Legacy skill loading is unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import Skill


def verified_skill(skill: Skill, expected: dict[str, str], *, skill_file: Path | None = None) -> Skill:
    """Parse policy and metadata from the same bytes that match the pin."""
    path = skill_file if skill_file is not None else skill.skill_file
    if path.is_symlink() or not path.is_file():
        raise ValueError("Published skill body identity is unavailable")
    # Whole-package identity is not implied by a SKILL.md hash. Reject other
    # files/directories rather than letting unpinned code or evidence execute.
    if any(child.name != "SKILL.md" for child in path.parent.iterdir()):
        raise ValueError("Published skill bodies currently require a single-file package")
    raw = path.read_bytes()
    if expected.get(skill.name) != hashlib.sha256(raw).hexdigest():
        raise ValueError("Published skill body identity mismatch")
    parsed = parse_skill_file(path, skill.category, skill.relative_path, source=raw.decode("utf-8"))
    if parsed is None or parsed.name != skill.name:
        raise ValueError("Published skill body identity is invalid")
    return replace(parsed, enabled=skill.enabled)


def verify_projected_skill_bodies(skills: list[Skill], projection, expected: dict[str, str]) -> None:
    """Verify the physical copies actually exposed by the sandbox mounts."""
    for skill in skills:
        root = getattr(projection, skill.category.value).resolve(strict=True)
        path = root / skill.relative_path / "SKILL.md"
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError("Published skill projection identity escapes its category")
        verified_skill(skill, expected, skill_file=path)

"""Session-only administrator API for published Agent and identity role management."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.deps import get_current_user_from_request, require_admin_user
from deerflow.agent_directory import DirectoryConflict, get_directory

router = APIRouter(prefix="/api/agent-directory", tags=["agent-directory"])


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0)


class Publication(Mutation):
    name: str = Field(pattern=r"^[a-z0-9-]+$", max_length=100)
    source_owner: str = Field(min_length=1, max_length=100)
    source_name: str = Field(pattern=r"^[A-Za-z0-9-]+$", max_length=100)
    profile: str = Field(min_length=1, max_length=100)


class Enable(Mutation):
    enabled: bool


class Membership(Enable):
    profile: str = Field(min_length=1, max_length=100)
    account_id: str = Field(min_length=1, max_length=100)


async def _admin(request: Request, expected_user: str | None = None):
    await require_admin_user(request, detail="Administrator session required")
    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(403, "Administrator browser session required")
    user = await get_current_user_from_request(request)
    if expected_user is not None and expected_user != str(user.id):
        raise HTTPException(409, "Signed-in account changed; reload this page")
    return str(user.id)


def _directory():
    directory = get_directory()
    if directory is None:
        raise HTTPException(404, "Agent directory is not enabled")
    return directory


async def _run(function):
    try:
        return await asyncio.to_thread(function)
    except HTTPException:
        raise
    except DirectoryConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, FileNotFoundError, KeyError):
        raise HTTPException(422, "Directory request is invalid or the source is unavailable") from None
    except Exception:
        raise HTTPException(503, "Agent directory or identity service is unavailable") from None


@router.get("")
async def dashboard(request: Request):
    await _admin(request)

    def read():
        from deerflow.config.app_config import get_app_config
        from deerflow.persistence.agents.sql import get_sync_sessionmaker
        from deerflow.persistence.user.model import UserRow

        directory = _directory()
        state = directory.state()
        profiles = {k: p.model_dump() for k, p in directory.config.profiles.items()}
        with get_sync_sessionmaker(get_app_config().database.app_sync_sqlalchemy_url)() as session:
            users = session.execute(select(UserRow).where(UserRow.oauth_provider == directory.config.provider).order_by(UserRow.id).limit(501)).scalars().all()
        accounts = []
        for user in users[:500]:
            # Administrative reads fail visibly; unavailable identity data must
            # never render as a successful empty membership list.
            available = True
            try:
                roles = directory.identity.roles(user.oauth_id)
            except ValueError:
                roles = set()
                available = False
            accounts.append({"id": user.id, "email": user.email, "available": available, "profiles": [k for k, p in directory.config.profiles.items() if directory.config.realm + "/" + p.role in roles]})
        return {
            "revision": state["revision"],
            "profiles": profiles,
            "accounts": accounts,
            "accounts_truncated": len(users) > 500,
            "agents": [{"name": n, "display_name": r["definition"]["config"].get("display_name"), "profile": r["profile"], "enabled": r["enabled"], "digest": r["definition"]["digest"]} for n, r in state["agents"].items()],
            "sources": [{"owner": owner, "name": a.name, "display_name": a.display_name} for owner, a in directory.private.list_all() if a.immutable_definition],
            "audit": state["audit"][-100:],
        }

    return await _run(read)


@router.post("/versions")
async def publish(body: Publication, request: Request, x_expected_user_id: Annotated[str, Header()]):
    actor = await _admin(request, x_expected_user_id)
    return {"revision": await _run(lambda: _directory().publish(body.name, body.source_owner, body.source_name, body.profile, actor=actor, expected_revision=body.expected_revision))}


@router.patch("/versions/{name}")
async def enable(name: str, body: Enable, request: Request, x_expected_user_id: Annotated[str, Header()]):
    actor = await _admin(request, x_expected_user_id)
    return {"revision": await _run(lambda: _directory().set_enabled(name, body.enabled, actor=actor, expected_revision=body.expected_revision))}


@router.put("/memberships")
async def membership(body: Membership, request: Request, x_expected_user_id: Annotated[str, Header()]):
    actor = await _admin(request, x_expected_user_id)
    return {"revision": await _run(lambda: _directory().set_membership(body.profile, body.account_id, body.enabled, actor=actor, expected_revision=body.expected_revision))}

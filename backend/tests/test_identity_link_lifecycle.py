"""Atomic ownership/link lifecycle tests with native SQLite/SQLAlchemy repositories."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserIdentityEventRow


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "users.sqlite"))
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield SQLiteUserRepository(sf), sf
    await engine.dispose()


@pytest.mark.asyncio
async def test_atomic_link_keeps_id_and_revokes_old_version(repo):
    r, sf = repo
    u = await r.create_user(User(email="legacy@example.com", password_hash="preserved-hash"))
    linked = await r.link_oauth_identity(str(u.id), "genesis-dev", "sub-a", "https://issuer.example.com", 0)
    assert linked.id == u.id and linked.email == u.email and linked.password_hash == u.password_hash
    assert linked.system_role == "user" and linked.oauth_id == "sub-a" and linked.token_version == 1
    assert (await r.get_user_by_oauth("genesis-dev", "sub-a")).id == u.id
    with pytest.raises(ValueError):
        await r.link_oauth_identity(str(u.id), "genesis-dev", "sub-a", "https://issuer.example.com", 0)
    async with sf() as s:
        events = (await s.scalars(select(UserIdentityEventRow))).all()
        assert len(events) == 1 and events[0].event == "link" and events[0].issuer == "https://issuer.example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("role,password,provider,sub,version", [("admin", "hash", None, None, 0), ("user", None, None, None, 0), ("user", "hash", "other", "already", 0), ("user", "hash", None, None, 1)])
async def test_invalid_or_stale_target_keeps_state(repo, role, password, provider, sub, version):
    r, sf = repo
    u = await r.create_user(User(email="target@example.com", password_hash=password, system_role=role, oauth_provider=provider, oauth_id=sub))
    with pytest.raises(ValueError):
        await r.link_oauth_identity(str(u.id), "genesis-dev", "new", "https://issuer.example.com", version)
    saved = await r.get_user_by_id(str(u.id))
    assert saved.oauth_provider == provider and saved.oauth_id == sub and saved.token_version == 0
    async with sf() as s:
        assert (await s.scalars(select(UserIdentityEventRow))).all() == []


@pytest.mark.asyncio
async def test_other_owner_cannot_take_existing_identity(repo):
    r, sf = repo
    a = await r.create_user(User(email="a@example.com", password_hash="hash"))
    b = await r.create_user(User(email="b@example.com", password_hash="hash"))
    await r.link_oauth_identity(str(a.id), "genesis-dev", "bound", "https://issuer.example.com", 0)
    with pytest.raises(ValueError):
        await r.link_oauth_identity(str(b.id), "genesis-dev", "bound", "https://issuer.example.com", 0)
    assert (await r.get_user_by_id(str(b.id))).oauth_id is None


@pytest.mark.asyncio
async def test_unlink_requires_current_binding_and_keeps_password_owner(repo):
    r, sf = repo
    u = await r.create_user(User(email="unlink@example.com", password_hash="hash"))
    await r.link_oauth_identity(str(u.id), "genesis-dev", "own", "https://issuer.example.com", 0)
    with pytest.raises(ValueError):
        await r.unlink_oauth_identity(str(u.id), "genesis-dev", "other", "https://issuer.example.com", 1)
    with pytest.raises(ValueError):
        await r.unlink_oauth_identity(str(u.id), "genesis-dev", "own", "https://issuer.example.com", 0)
    saved = await r.unlink_oauth_identity(str(u.id), "genesis-dev", "own", "https://issuer.example.com", 1)
    assert saved.id == u.id and saved.password_hash == "hash" and saved.oauth_id is None and saved.token_version == 2
    async with sf() as s:
        assert [e.event for e in (await s.scalars(select(UserIdentityEventRow).order_by(UserIdentityEventRow.created_at))).all()] == ["link", "unlink"]


@pytest.mark.asyncio
async def test_oidc_only_user_cannot_unlink_without_alternative_login(repo):
    r, _ = repo
    u = await r.create_user(User(email="oidc@example.com", oauth_provider="genesis-dev", oauth_id="sub"))
    with pytest.raises(ValueError):
        await r.unlink_oauth_identity(str(u.id), "genesis-dev", "sub", "https://issuer.example.com", 0)
    assert (await r.get_user_by_id(str(u.id))).oauth_id == "sub"


@pytest.mark.asyncio
async def test_concurrent_links_allow_one_binding_and_one_audit_event(repo):
    r, sf = repo
    u = await r.create_user(User(email="race@example.com", password_hash="hash"))
    outcomes = await asyncio.gather(*[r.link_oauth_identity(str(u.id), "genesis-dev", sub, "https://issuer.example.com", 0) for sub in ("one", "two")], return_exceptions=True)
    assert sum(isinstance(x, User) for x in outcomes) == 1
    assert sum(isinstance(x, ValueError) for x in outcomes) == 1
    async with sf() as s:
        assert len((await s.scalars(select(UserIdentityEventRow))).all()) == 1

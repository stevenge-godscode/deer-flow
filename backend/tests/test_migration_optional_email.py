import asyncio
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

PREVIOUS = "0026_user_identity_events"
REVISION = "0027_optional_oidc_email"


def test_migration_head_includes_current_dev_revision():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        # The deployed DEV database is at this revision; older images cannot boot.
        assert ScriptDirectory.from_config(_get_alembic_config(engine)).get_current_head() == REVISION
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.parametrize("driver", ["sqlite", "postgres"])
def test_contact_migration_preserves_owners_and_evidence_and_refuses_lossy_rollback(tmp_path, driver):
    url = "sqlite+aiosqlite:///" + str(tmp_path / "contacts.sqlite")
    if driver == "postgres":
        url = os.getenv("DEERFLOW_TEST_POSTGRES_URL", "")
        if not url:
            pytest.skip("Dedicated PostgreSQL CI database required")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    cfg = _get_alembic_config(engine)
    command.upgrade(cfg, PREVIOUS)
    sync = sa.create_engine(url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg"))
    with sync.begin() as c:
        c.execute(sa.text("INSERT INTO users(id,email,system_role,created_at,token_version,needs_setup) VALUES('local','local@example.test','user',CURRENT_TIMESTAMP,0,FALSE)"))
        c.execute(
            sa.text("INSERT INTO user_identity_events(id,user_id,provider,issuer,subject,event,proof,token_version,created_at) VALUES('event','local','genesis-dev','https://issuer.test','sub','link','password+oidc',1,CURRENT_TIMESTAMP)")
        )
    command.upgrade(cfg, REVISION)
    with sync.begin() as c:
        if driver == "sqlite":
            c.execute(sa.text("PRAGMA foreign_keys=ON"))
            assert c.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        assert c.scalar(sa.text("SELECT user_id FROM user_identity_events WHERE id='event'")) == "local"
        c.execute(sa.text("INSERT INTO users(id,email,system_role,created_at,token_version,needs_setup,oauth_provider,oauth_id) VALUES('wx',NULL,'user',CURRENT_TIMESTAMP,0,FALSE,'genesis-dev','wx-sub')"))
        c.execute(sa.text("INSERT INTO users(id,email,system_role,created_at,token_version,needs_setup,oauth_provider,oauth_id) VALUES('wx2',NULL,'user',CURRENT_TIMESTAMP,0,FALSE,'genesis-dev','wx-sub2')"))
    for extra in [
        "NULL,NULL,'user',NULL",
        "'genesis-dev','other','admin',NULL",
        "'genesis-dev','other','user','secret'",
    ]:
        with pytest.raises(sa.exc.IntegrityError):
            with sync.begin() as c:
                c.execute(sa.text("INSERT INTO users(id,email,created_at,token_version,needs_setup,oauth_provider,oauth_id,system_role,password_hash) VALUES('invalid',NULL,CURRENT_TIMESTAMP,0,FALSE," + extra + ")"))
    with pytest.raises(RuntimeError, match="Email-less verified accounts exist"):
        command.downgrade(cfg, PREVIOUS)
    with sync.begin() as c:
        assert c.scalar(sa.text("SELECT COUNT(*) FROM users")) == 3
        assert c.scalar(sa.text("SELECT COUNT(*) FROM user_identity_events")) == 1
        c.execute(sa.text("UPDATE users SET email=id||'@verified.example.test' WHERE email IS NULL"))
    command.downgrade(cfg, PREVIOUS)
    with sync.connect() as c:
        assert c.scalar(sa.text("SELECT COUNT(*) FROM users")) == 3
        assert c.scalar(sa.text("SELECT COUNT(*) FROM user_identity_events")) == 1
    sync.dispose()
    asyncio.run(engine.dispose())

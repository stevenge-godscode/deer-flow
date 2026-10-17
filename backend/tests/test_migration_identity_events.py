import asyncio

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config

REVISION = "0026_user_identity_events"
PREVIOUS = "0025_repair_run_change_seq"


def test_identity_migration_extends_single_existing_head(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "chain.sqlite"))
    script = ScriptDirectory.from_config(_get_alembic_config(engine))
    assert script.get_heads() == ["0027_optional_oidc_email"]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(REVISION) <= 32
    asyncio.run(engine.dispose())


def test_upgrade_and_application_rollback_preserve_identity_evidence(tmp_path):
    url = "sqlite+aiosqlite:///" + str(tmp_path / "migrate.sqlite")
    engine = create_async_engine(url)
    cfg = _get_alembic_config(engine)
    command.upgrade(cfg, PREVIOUS)
    command.upgrade(cfg, REVISION)
    sync = sa.create_engine(url.replace("+aiosqlite", ""))
    with sync.begin() as c:
        c.execute(sa.text("INSERT INTO users(id,email,system_role,created_at,token_version,needs_setup) VALUES('local','legacy@example.com','user',CURRENT_TIMESTAMP,0,0)"))
        c.execute(
            sa.text(
                "INSERT INTO user_identity_events(id,user_id,provider,issuer,subject,event,proof,token_version,created_at) VALUES('event','local','genesis-dev','https://issuer.example.com','sub','link','password+oidc',1,CURRENT_TIMESTAMP)"
            )
        )
    command.downgrade(cfg, PREVIOUS)
    with sync.begin() as c:
        assert c.scalar(sa.text("SELECT COUNT(*) FROM user_identity_events")) == 1
        # The old user repository columns still support reads and writes.
        c.execute(sa.text("UPDATE users SET token_version=token_version+1 WHERE id='local'"))
        assert c.scalar(sa.text("SELECT token_version FROM users WHERE id='local'")) == 1
    command.upgrade(cfg, REVISION)
    with sync.connect() as c:
        assert c.scalar(sa.text("SELECT COUNT(*) FROM user_identity_events")) == 1
    sync.dispose()
    asyncio.run(engine.dispose())

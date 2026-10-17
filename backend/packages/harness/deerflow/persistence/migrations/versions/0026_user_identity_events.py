"""Account association audit after the accepted 0025 schema.

Application rollback retains evidence while restoring the known predecessor
stamp. A later upgrade validates and reuses that retained table.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_user_identity_events"
down_revision = "0025_repair_run_change_seq"
branch_labels = None
depends_on = None

_STRINGS = {"id": 36, "user_id": 36, "provider": 32, "issuer": 512, "subject": 128, "event": 16, "proof": 32}


def _validate_retained_table(bind):
    inspector = sa.inspect(bind)
    columns = {c["name"]: c for c in inspector.get_columns("user_identity_events")}
    if set(columns) != set(_STRINGS) | {"token_version", "created_at"}:
        raise RuntimeError("Retained identity audit columns have drifted")
    for name, length in _STRINGS.items():
        column = columns[name]
        if not isinstance(column["type"], sa.String) or column["type"].length != length or column["nullable"]:
            raise RuntimeError("Retained identity audit column shape has drifted")
    if not isinstance(columns["token_version"]["type"], sa.Integer) or columns["token_version"]["nullable"] or not isinstance(columns["created_at"]["type"], sa.DateTime) or columns["created_at"]["nullable"]:
        raise RuntimeError("Retained identity audit lifecycle shape has drifted")
    if inspector.get_pk_constraint("user_identity_events")["constrained_columns"] != ["id"]:
        raise RuntimeError("Retained identity audit primary key has drifted")
    foreign_keys = inspector.get_foreign_keys("user_identity_events")
    if not any(f["constrained_columns"] == ["user_id"] and f["referred_table"] == "users" and f["referred_columns"] == ["id"] and f.get("options", {}).get("ondelete") == "RESTRICT" for f in foreign_keys):
        raise RuntimeError("Retained identity audit ownership has drifted")
    checks = {c["name"] for c in inspector.get_check_constraints("user_identity_events")}
    if not {"ck_identity_event_kind", "ck_identity_event_version"}.issubset(checks):
        raise RuntimeError("Retained identity audit constraints are missing")
    if not any(i["name"] == "ix_user_identity_events_user_id" and i["column_names"] == ["user_id"] for i in inspector.get_indexes("user_identity_events")):
        raise RuntimeError("Retained identity audit ownership index is missing")


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_identity_events"):
        _validate_retained_table(bind)
        return
    op.create_table(
        "user_identity_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("proof", sa.String(32), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event IN ('link','unlink')", name="ck_identity_event_kind"),
        sa.CheckConstraint("token_version > 0", name="ck_identity_event_version"),
    )
    op.create_index("ix_user_identity_events_user_id", "user_identity_events", ["user_id"])


def downgrade():
    # Preserve evidence. The application must be stopped before this audited
    # rollback to the prior known revision; re-upgrade validates retained DDL.
    pass

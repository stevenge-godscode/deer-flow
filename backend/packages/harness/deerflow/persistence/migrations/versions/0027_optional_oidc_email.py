"""Genuine optional contact for proved OAuth identities; never a synthetic email."""

import sqlalchemy as sa
from alembic import op

revision = "0027_optional_oidc_email"
down_revision = "0026_user_identity_events"
branch_labels = None
depends_on = None

CHECK = "email IS NOT NULL OR (oauth_provider IS NOT NULL AND oauth_id IS NOT NULL AND oauth_provider <> '' AND oauth_id <> '' AND password_hash IS NULL AND system_role = 'user')"


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(320), nullable=True)
        batch.create_check_constraint("ck_users_optional_oidc_email", CHECK)


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM users WHERE email IS NULL")).scalar():
        raise RuntimeError("Email-less verified accounts exist: disable provider and reconcile before schema rollback; no fabricated contacts or deletion")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_optional_oidc_email", type_="check")
        batch.alter_column("email", existing_type=sa.String(320), nullable=False)

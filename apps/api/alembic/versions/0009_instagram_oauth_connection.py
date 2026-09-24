"""instagram oauth connection
Revision ID: 0009_instagram_oauth_connection
Revises: 0008_local_media_engine
"""
from alembic import op
import sqlalchemy as sa
revision="0009_instagram_oauth_connection";down_revision="0008_local_media_engine";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("publication_connections",sa.Column("id",sa.String(36),primary_key=True),sa.Column("channel",sa.String(32),nullable=False,unique=True),sa.Column("connector",sa.String(80),nullable=False),sa.Column("status",sa.String(40),nullable=False),sa.Column("account_display_name",sa.String(200)),sa.Column("account_id",sa.String(120)),sa.Column("account_type",sa.String(32)),sa.Column("username",sa.String(120)),sa.Column("scopes",sa.JSON,nullable=False),sa.Column("issued_at",sa.DateTime(timezone=True)),sa.Column("expires_at",sa.DateTime(timezone=True)),sa.Column("refresh_supported",sa.Boolean,nullable=False),sa.Column("last_validated_at",sa.DateTime(timezone=True)),sa.Column("auth_profile",sa.String(100),nullable=False),sa.Column("token_store_reference",sa.String(200)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("oauth_states",sa.Column("id",sa.String(36),primary_key=True),sa.Column("state_hash",sa.String(64),nullable=False,unique=True),sa.Column("provider",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("used_at",sa.DateTime(timezone=True)),sa.Column("return_path",sa.String(500)))
def downgrade():op.drop_table("oauth_states");op.drop_table("publication_connections")

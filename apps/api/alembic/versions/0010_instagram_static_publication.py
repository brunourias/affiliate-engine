"""instagram static publication execution
Revision ID: 0010_instagram_static_publication
Revises: 0009_instagram_oauth_connection
"""
from alembic import op
import sqlalchemy as sa
revision="0010_instagram_static_publication";down_revision="0009_instagram_oauth_connection";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("publication_executions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("creative_id",sa.String(36),sa.ForeignKey("creatives.id"),nullable=False),sa.Column("publication_candidate_id",sa.String(80),nullable=False),sa.Column("package_fingerprint",sa.String(64),nullable=False),sa.Column("execution_fingerprint",sa.String(64),nullable=False,unique=True),sa.Column("channel",sa.String(32),nullable=False),sa.Column("connector",sa.String(80),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("container_id",sa.String(120)),sa.Column("platform_media_id",sa.String(120)),sa.Column("remote_request_executed",sa.Boolean,nullable=False),sa.Column("failure_code",sa.String(80)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("published_at",sa.DateTime(timezone=True)))
def downgrade():op.drop_table("publication_executions")

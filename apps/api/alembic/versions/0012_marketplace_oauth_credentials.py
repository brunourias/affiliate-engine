"""managed encrypted marketplace oauth credentials

Revision ID: 0012_marketplace_oauth_credentials
Revises: 0011_publication_execution_retry
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_marketplace_oauth_credentials"
down_revision = "0011_publication_execution_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_oauth_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_account_id", sa.String(80)),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True)),
        sa.Column("token_type", sa.String(32)),
        sa.Column("scope", sa.Text()),
        sa.Column("credential_status", sa.String(32), nullable=False, server_default="AVAILABLE"),
        sa.Column("refresh_not_before", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", name="uq_marketplace_oauth_credential_provider"),
    )


def downgrade():
    op.drop_table("marketplace_oauth_credentials")

"""Mercado Livre connection and capability diagnostics."""
from alembic import op
import sqlalchemy as sa

revision = "0002_marketplace_capabilities"
down_revision = "0001_v1a"


def upgrade():
    op.create_table(
        "marketplace_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False, unique=True),
        sa.Column("site_id", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("auth_mode", sa.String(24), nullable=False),
        sa.Column("external_account_id", sa.String(80)),
        sa.Column("external_nickname", sa.String(120)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "marketplace_capabilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("capability_key", sa.String(60), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("endpoint", sa.String(300)),
        sa.Column("http_method", sa.String(12)),
        sa.Column("last_http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("message", sa.Text()),
        sa.Column("metadata", sa.JSON()),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "capability_key", name="uq_marketplace_capability_provider_key"),
    )
    op.create_index("idx_marketplace_capability_status", "marketplace_capabilities", ["provider", "status"])


def downgrade():
    op.drop_table("marketplace_capabilities")
    op.drop_table("marketplace_connections")

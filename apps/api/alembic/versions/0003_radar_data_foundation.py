"""Mercado Livre Radar data foundation."""
from alembic import op
import sqlalchemy as sa

revision = "0003_radar_data_foundation"
down_revision = "0002_marketplace_capabilities"


def upgrade():
    op.create_table("marketplace_categories", sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(40), nullable=False), sa.Column("site_id", sa.String(16), nullable=False), sa.Column("external_category_id", sa.String(80), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("parent_external_category_id", sa.String(80)), sa.Column("source_capability", sa.String(60), nullable=False), sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("provider", "external_category_id", name="uq_marketplace_category_provider_external"))
    op.create_table("radar_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(40), nullable=False), sa.Column("site_id", sa.String(16), nullable=False), sa.Column("trigger_type", sa.String(20), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("requested_category_id", sa.String(80)), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("sources_requested", sa.JSON(), nullable=False), sa.Column("sources_succeeded", sa.JSON(), nullable=False), sa.Column("sources_failed", sa.JSON(), nullable=False), sa.Column("discovered_count", sa.Integer(), nullable=False), sa.Column("error_summary", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("radar_signals", sa.Column("id", sa.String(36), primary_key=True), sa.Column("radar_run_id", sa.String(36), sa.ForeignKey("radar_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("provider", sa.String(40), nullable=False), sa.Column("site_id", sa.String(16), nullable=False), sa.Column("source_type", sa.String(40), nullable=False), sa.Column("source_capability", sa.String(60), nullable=False), sa.Column("category_external_id", sa.String(80)), sa.Column("entity_type", sa.String(30), nullable=False), sa.Column("external_id", sa.String(120)), sa.Column("display_text", sa.String(500)), sa.Column("rank", sa.Integer()), sa.Column("source_payload", sa.JSON()), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("idx_radar_signals_run", "radar_signals", ["radar_run_id"])
    op.create_index("idx_radar_signals_source_observed", "radar_signals", ["source_type", "observed_at"])
    op.create_index("idx_radar_signals_entity", "radar_signals", ["entity_type", "external_id"])
    op.create_index("idx_radar_signals_category_observed", "radar_signals", ["category_external_id", "observed_at"])


def downgrade():
    op.drop_table("radar_signals")
    op.drop_table("radar_runs")
    op.drop_table("marketplace_categories")

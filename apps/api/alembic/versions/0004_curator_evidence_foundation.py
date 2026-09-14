"""curator evidence foundation

Revision ID: 0004_curator_evidence_foundation
Revises: 0003_radar_data_foundation
"""
from alembic import op
import sqlalchemy as sa
revision="0004_curator_evidence_foundation"; down_revision="0003_radar_data_foundation"; branch_labels=None; depends_on=None
def upgrade():
    op.create_table("curator_candidates",sa.Column("id",sa.String(36),primary_key=True),sa.Column("provider",sa.String(40),nullable=False),sa.Column("site_id",sa.String(16)),sa.Column("source_type",sa.String(24),nullable=False),sa.Column("source_radar_signal_id",sa.String(36),sa.ForeignKey("radar_signals.id")),sa.Column("source_radar_run_id",sa.String(36),sa.ForeignKey("radar_runs.id")),sa.Column("entity_type",sa.String(24),nullable=False),sa.Column("external_id",sa.String(120)),sa.Column("category_external_id",sa.String(80)),sa.Column("source_display_text",sa.String(500)),sa.Column("working_title",sa.String(300)),sa.Column("source_url",sa.String(1000)),sa.Column("notes",sa.Text),sa.Column("status",sa.String(24),nullable=False),sa.Column("evidence_status",sa.String(32),nullable=False),sa.Column("evidence_level",sa.String(32),nullable=False),sa.Column("first_seen_at",sa.DateTime(timezone=True),nullable=False),sa.Column("last_seen_at",sa.DateTime(timezone=True),nullable=False),sa.Column("stale_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_curator_candidate_status","curator_candidates",["status","updated_at"])
    op.create_table("curator_evidence",sa.Column("id",sa.String(36),primary_key=True),sa.Column("candidate_id",sa.String(36),sa.ForeignKey("curator_candidates.id",ondelete="CASCADE"),nullable=False),sa.Column("evidence_type",sa.String(40),nullable=False),sa.Column("value_text",sa.Text),sa.Column("value_number",sa.Integer),sa.Column("value_cents",sa.Integer),sa.Column("value_json",sa.JSON),sa.Column("source_kind",sa.String(32),nullable=False),sa.Column("source_name",sa.String(200)),sa.Column("source_url",sa.String(1000)),sa.Column("source_reference",sa.String(300)),sa.Column("confidence",sa.String(16),nullable=False),sa.Column("verification_status",sa.String(20),nullable=False),sa.Column("observed_at",sa.DateTime(timezone=True),nullable=False),sa.Column("valid_until",sa.DateTime(timezone=True)),sa.Column("metadata",sa.JSON),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_curator_evidence_candidate","curator_evidence",["candidate_id","observed_at"])
def downgrade():
    op.drop_index("ix_curator_evidence_candidate",table_name="curator_evidence"); op.drop_table("curator_evidence"); op.drop_index("ix_curator_candidate_status",table_name="curator_candidates"); op.drop_table("curator_candidates")

"""immutable curator assessments
Revision ID: 0005_curator_assessments
Revises: 0004_curator_evidence_foundation
"""
from alembic import op
import sqlalchemy as sa
revision="0005_curator_assessments";down_revision="0004_curator_evidence_foundation";branch_labels=None;depends_on=None
def upgrade():
    op.create_table("curator_assessments",sa.Column("id",sa.String(36),primary_key=True),sa.Column("candidate_id",sa.String(36),sa.ForeignKey("curator_candidates.id",ondelete="CASCADE"),nullable=False),sa.Column("assessment_version",sa.Integer,nullable=False),sa.Column("previous_assessment_id",sa.String(36),sa.ForeignKey("curator_assessments.id")),sa.Column("evidence_status",sa.String(32),nullable=False),sa.Column("evidence_level",sa.String(32),nullable=False),sa.Column("trust_gate",sa.String(32),nullable=False),sa.Column("trust_reasons",sa.JSON,nullable=False),sa.Column("trust_warnings",sa.JSON,nullable=False),sa.Column("recommendation_score",sa.Integer),sa.Column("recommendation_coverage_percent",sa.Integer,nullable=False),sa.Column("recommendation_label",sa.String(40)),sa.Column("opportunity_score",sa.Integer),sa.Column("opportunity_coverage_percent",sa.Integer,nullable=False),sa.Column("price_verdict",sa.String(32),nullable=False),sa.Column("price_to_buy_cents",sa.Integer),sa.Column("editorial_verdict",sa.String(40),nullable=False),sa.Column("recommendation_pillars",sa.JSON,nullable=False),sa.Column("opportunity_pillars",sa.JSON,nullable=False),sa.Column("evidence_ids_used",sa.JSON,nullable=False),sa.Column("unknown_fields",sa.JSON,nullable=False),sa.Column("rationale",sa.JSON,nullable=False),sa.Column("evaluated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("candidate_id","assessment_version",name="uq_curator_assessment_candidate_version"))
    op.create_index("ix_curator_assessment_candidate_version","curator_assessments",["candidate_id","assessment_version"])
def downgrade():op.drop_index("ix_curator_assessment_candidate_version",table_name="curator_assessments");op.drop_table("curator_assessments")

"""Add provenance and single-active gate for controlled media handoff.

Revision ID: 0020_media_job_handoff
Revises: 0019_creative_handoff_idempotency
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_media_job_handoff"
down_revision = "0019_creative_handoff_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    # Existing jobs remain historical: provenance and gate keys stay NULL.
    # attempt_number receives a safe default for both existing and new rows.
    with op.batch_alter_table("media_jobs") as batch:
        batch.add_column(sa.Column("creation_source", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("creation_key", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("active_key", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("source_creative_approval_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("input_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("previous_media_job_id", sa.String(length=36), nullable=True))
        batch.create_unique_constraint("uq_media_jobs_creation_key", ["creation_key"])
        batch.create_unique_constraint("uq_media_jobs_active_key", ["active_key"])
        batch.create_foreign_key("fk_media_jobs_source_creative_approval", "approvals", ["source_creative_approval_id"], ["id"])
        batch.create_foreign_key("fk_media_jobs_previous_job", "media_jobs", ["previous_media_job_id"], ["id"])


def downgrade():
    with op.batch_alter_table("media_jobs") as batch:
        batch.drop_constraint("fk_media_jobs_previous_job", type_="foreignkey")
        batch.drop_constraint("fk_media_jobs_source_creative_approval", type_="foreignkey")
        batch.drop_constraint("uq_media_jobs_active_key", type_="unique")
        batch.drop_constraint("uq_media_jobs_creation_key", type_="unique")
        batch.drop_column("previous_media_job_id")
        batch.drop_column("attempt_number")
        batch.drop_column("input_fingerprint")
        batch.drop_column("source_creative_approval_id")
        batch.drop_column("active_key")
        batch.drop_column("creation_key")
        batch.drop_column("creation_source")

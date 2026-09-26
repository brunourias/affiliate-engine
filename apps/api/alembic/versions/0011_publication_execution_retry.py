"""explicit manual publication retry
Revision ID: 0011_publication_execution_retry
Revises: 0010_instagram_static_publication
"""
from alembic import op
import sqlalchemy as sa
revision="0011_publication_execution_retry";down_revision="0010_instagram_static_publication";branch_labels=None;depends_on=None
def upgrade():
    with op.batch_alter_table("publication_executions") as batch:
        batch.add_column(sa.Column("retry_of_execution_id",sa.String(36),nullable=True))
        batch.add_column(sa.Column("attempt_number",sa.Integer(),nullable=False,server_default="1"))
        batch.create_foreign_key("fk_publication_execution_retry_of","publication_executions",["retry_of_execution_id"],["id"])
        batch.create_unique_constraint("uq_publication_execution_retry_of",["retry_of_execution_id"])
def downgrade():
    with op.batch_alter_table("publication_executions") as batch:
        batch.drop_constraint("uq_publication_execution_retry_of",type_="unique")
        batch.drop_constraint("fk_publication_execution_retry_of",type_="foreignkey")
        batch.drop_column("attempt_number");batch.drop_column("retry_of_execution_id")

"""create_resume_summaries_table

Revision ID: 04ed2e52cb9a
Revises:
Create Date: 2026-04-30 01:35:42.899205

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "04ed2e52cb9a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resume_summaries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("jd_id", sa.String(), nullable=False),
        sa.Column("professional_profile", sa.Text(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("skill_gaps", sa.JSON(), nullable=False),
        sa.Column("experience_relevance", sa.Text(), nullable=False),
        sa.Column("red_flags", sa.JSON(), nullable=False),
        sa.Column("notable_items", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "jd_id", name="uq_candidate_jd"),
    )
    op.create_index("ix_resume_summaries_candidate_id", "resume_summaries", ["candidate_id"])
    op.create_index("ix_resume_summaries_jd_id", "resume_summaries", ["jd_id"])


def downgrade() -> None:
    op.drop_index("ix_resume_summaries_jd_id", table_name="resume_summaries")
    op.drop_index("ix_resume_summaries_candidate_id", table_name="resume_summaries")
    op.drop_table("resume_summaries")

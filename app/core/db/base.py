"""SQLAlchemy declarative base and ORM models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ResumeSummary(Base):
    __tablename__ = "resume_summaries"
    __table_args__ = (UniqueConstraint("candidate_id", "jd_id", name="uq_candidate_jd"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    jd_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    professional_profile: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list] = mapped_column(JSON, nullable=False)
    skill_gaps: Mapped[list] = mapped_column(JSON, nullable=False)
    experience_relevance: Mapped[str] = mapped_column(Text, nullable=False)
    red_flags: Mapped[list] = mapped_column(JSON, nullable=False)
    notable_items: Mapped[list] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

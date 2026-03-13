import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class DigestPolicy(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "digest_policy"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(100), nullable=False)
    target_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    include_categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exclude_categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    max_items: Mapped[int] = mapped_column(Integer, default=50)
    include_weather: Mapped[bool] = mapped_column(default=True)
    include_feeds: Mapped[bool] = mapped_column(default=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    template: Mapped[str] = mapped_column(String(100), default="default")


class DigestRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "digest_run"

    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("digest_policy.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    sections: Mapped[list["DigestSection"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class DigestSection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "digest_section"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("digest_run.id", ondelete="CASCADE"), nullable=False)
    section_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped["DigestRun"] = relationship(back_populates="sections")

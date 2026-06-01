import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


# ---------------------------------------------------------------------------
# RSS Prompt (must be defined first — referenced by FK from RssFeed/RssItem)
# ---------------------------------------------------------------------------

class RssPrompt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "rss_prompt"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # item_summary = Einzel-Artikel-Zusammenfassung, feed_briefing = Feed-Briefing
    prompt_type: Mapped[str] = mapped_column(String(30), default="item_summary")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class RssFeed(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "rss_feed"

    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- LLM summarization config ---
    auto_summarize_items: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auto_briefing: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    item_summary_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rss_prompt.id", ondelete="SET NULL"), nullable=True
    )
    briefing_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rss_prompt.id", ondelete="SET NULL"), nullable=True
    )
    summary_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    briefing_count: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    last_briefing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["RssItem"]] = relationship(back_populates="feed", cascade="all, delete-orphan")
    briefings: Mapped[list["RssBriefing"]] = relationship(back_populates="feed", cascade="all, delete-orphan")


class RssItem(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "rss_item"

    feed_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rss_feed.id", ondelete="CASCADE"), nullable=False)
    guid: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Per-article AI summary (latest wins, no per-item history) ---
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ai_summary_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rss_prompt.id", ondelete="SET NULL"), nullable=True
    )
    ai_summary_prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_summarized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # none | pending | processing | done | error
    summary_status: Mapped[str] = mapped_column(String(20), default="none", server_default="none", nullable=False)
    summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    feed: Mapped["RssFeed"] = relationship(back_populates="items")


class RssBriefing(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "rss_briefing"

    feed_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rss_feed.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rss_prompt.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    feed: Mapped["RssFeed"] = relationship(back_populates="briefings")

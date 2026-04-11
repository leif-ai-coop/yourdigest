import uuid
from datetime import datetime
from sqlalchemy import (
    String, Boolean, Text, Integer, Float, DateTime, ForeignKey, JSON,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


# ---------------------------------------------------------------------------
# Podcast Prompt (must be defined first — referenced by FK from other tables)
# ---------------------------------------------------------------------------

class PodcastPrompt(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_prompt"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(30), default="map_summary")
    # map_summary = Chunk-Zusammenfassung, reduce_summary = Gesamt-Zusammenfassung
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Podcast Feed
# ---------------------------------------------------------------------------

class PodcastFeed(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_feed"

    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_process_new: Mapped[bool] = mapped_column(Boolean, default=True)

    map_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    reduce_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    transcription_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary_model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    max_episode_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_episode_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_audio_size_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keep_audio_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ignore_title_patterns: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prefer_external_transcript_url: Mapped[bool] = mapped_column(Boolean, default=False)

    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    episodes: Mapped[list["PodcastEpisode"]] = relationship(
        back_populates="feed", cascade="all, delete-orphan"
    )
    map_prompt: Mapped["PodcastPrompt | None"] = relationship(foreign_keys=[map_prompt_id])
    reduce_prompt: Mapped["PodcastPrompt | None"] = relationship(foreign_keys=[reduce_prompt_id])


# ---------------------------------------------------------------------------
# Podcast Episode
# ---------------------------------------------------------------------------

class PodcastEpisode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_episode"

    feed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_feed.id", ondelete="CASCADE"), nullable=False
    )

    # Identity / Dedup
    guid: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Discovery
    discovery_status: Mapped[str] = mapped_column(String(20), default="new")  # new | accepted | skipped
    skipped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Processing
    processing_status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | downloading | chunking | transcribing | summarizing_chunks | reducing | done | error
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_retryable: Mapped[bool] = mapped_column(Boolean, default=True)

    # Chunking
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_overlap_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_strategy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Audio
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Delivery convenience cache
    first_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # User flags
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    summarize_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    feed: Mapped["PodcastFeed"] = relationship(back_populates="episodes")
    chunks: Mapped[list["PodcastEpisodeChunk"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["PodcastArtifact"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_podcast_episode_feed_guid", "feed_id", "guid"),
        Index("ix_podcast_episode_processing", "processing_status", "locked_at"),
    )


# ---------------------------------------------------------------------------
# Podcast Episode Chunk
# ---------------------------------------------------------------------------

class PodcastEpisodeChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_episode_chunk"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episode.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    map_summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    map_summary_model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | transcribing | summarizing | done | error
    error_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    episode: Mapped["PodcastEpisode"] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("episode_id", "chunk_index", name="uq_chunk_episode_index"),
    )


# ---------------------------------------------------------------------------
# Podcast Artifact (versionierte Endprodukte: transcript / summary)
# ---------------------------------------------------------------------------

class PodcastArtifact(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_artifact"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episode.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)  # transcript | summary

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    episode: Mapped["PodcastEpisode"] = relationship(back_populates="artifacts")
    prompt: Mapped["PodcastPrompt | None"] = relationship(foreign_keys=[prompt_id])

    __table_args__ = (
        # Nur ein aktives Artifact pro Episode+Typ
        Index(
            "ix_podcast_artifact_active",
            "episode_id", "artifact_type",
            unique=True,
            postgresql_where="is_active = true",
        ),
    )


# ---------------------------------------------------------------------------
# Podcast Processing Run
# ---------------------------------------------------------------------------

class PodcastProcessingRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_processing_run"

    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episode.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episode_chunk.id", ondelete="CASCADE"), nullable=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    # download | chunk | transcribe | map_summary | reduce_summary
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running | completed | failed
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Podcast Mail Policy
# ---------------------------------------------------------------------------

class PodcastMailPolicy(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_mail_policy"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(100), nullable=False)
    target_email: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    feed_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Podcast Delivery Run (generisch: digest + podcast_mail)
# ---------------------------------------------------------------------------

class PodcastDeliveryRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_delivery_run"

    delivery_channel: Mapped[str] = mapped_column(String(30), nullable=False)  # digest | podcast_mail
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # running | completed | failed
    episode_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_prompt.id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    episodes: Mapped[list["PodcastDeliveryRunEpisode"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PodcastDeliveryRunEpisode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "podcast_delivery_run_episode"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_delivery_run.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_episode.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("podcast_artifact.id", ondelete="SET NULL"), nullable=True
    )

    run: Mapped["PodcastDeliveryRun"] = relationship(back_populates="episodes")

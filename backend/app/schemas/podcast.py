import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Podcast Prompt
# ---------------------------------------------------------------------------

class PodcastPromptCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = Field(None, max_length=1000)
    system_prompt: str = Field(max_length=20000)
    prompt_type: str = Field("map_summary", pattern=r'^(map_summary|reduce_summary)$')
    is_default: bool = False


class PodcastPromptUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=1000)
    system_prompt: str | None = Field(None, max_length=20000)
    prompt_type: str | None = Field(None, pattern=r'^(map_summary|reduce_summary)$')
    is_default: bool | None = None


class PodcastPromptResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    prompt_type: str
    version: int
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Podcast Feed
# ---------------------------------------------------------------------------

class PodcastFeedCreate(BaseModel):
    url: str = Field(max_length=2000)
    title: str | None = Field(None, max_length=500)
    enabled: bool = True
    auto_process_new: bool = True
    map_prompt_id: uuid.UUID | None = None
    reduce_prompt_id: uuid.UUID | None = None
    transcription_model: str | None = Field(None, max_length=200)
    summary_model: str | None = Field(None, max_length=200)
    fetch_interval_minutes: int = Field(30, ge=5, le=1440)
    max_episode_duration_seconds: int | None = Field(None, ge=60)
    min_episode_duration_seconds: int | None = Field(None, ge=0)
    max_audio_size_mb: int | None = Field(None, ge=1)
    keep_audio_days: int | None = Field(None, ge=0)
    ignore_title_patterns: list[str] | None = None
    prefer_external_transcript_url: bool = False
    language: str | None = Field(None, max_length=10)


class PodcastFeedUpdate(BaseModel):
    url: str | None = Field(None, max_length=2000)
    title: str | None = Field(None, max_length=500)
    enabled: bool | None = None
    auto_process_new: bool | None = None
    map_prompt_id: uuid.UUID | None = None
    reduce_prompt_id: uuid.UUID | None = None
    transcription_model: str | None = Field(None, max_length=200)
    summary_model: str | None = Field(None, max_length=200)
    fetch_interval_minutes: int | None = Field(None, ge=5, le=1440)
    max_episode_duration_seconds: int | None = None
    min_episode_duration_seconds: int | None = None
    max_audio_size_mb: int | None = None
    keep_audio_days: int | None = None
    ignore_title_patterns: list[str] | None = None
    prefer_external_transcript_url: bool | None = None
    language: str | None = Field(None, max_length=10)


class PodcastFeedResponse(BaseModel):
    id: uuid.UUID
    url: str
    title: str | None
    description: str | None
    image_url: str | None
    slug: str | None
    language: str | None
    enabled: bool
    auto_process_new: bool
    map_prompt_id: uuid.UUID | None
    reduce_prompt_id: uuid.UUID | None
    transcription_model: str | None
    summary_model: str | None
    fetch_interval_minutes: int
    max_episode_duration_seconds: int | None
    min_episode_duration_seconds: int | None
    max_audio_size_mb: int | None
    keep_audio_days: int | None
    ignore_title_patterns: list[str] | None
    prefer_external_transcript_url: bool
    last_fetched_at: datetime | None
    last_successful_fetch_at: datetime | None
    consecutive_failures: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Podcast Episode
# ---------------------------------------------------------------------------

class PodcastEpisodeResponse(BaseModel):
    id: uuid.UUID
    feed_id: uuid.UUID
    guid: str | None
    audio_url: str | None
    title: str | None
    description: str | None
    link: str | None
    episode_number: int | None
    season_number: int | None
    audio_size_bytes: int | None
    mime_type: str | None
    duration_seconds: int | None
    published_at: datetime | None
    discovery_status: str
    skipped_reason: str | None
    processing_status: str
    processing_attempts: int
    error_class: str | None
    error_message: str | None
    is_retryable: bool
    chunk_count: int | None
    is_saved: bool
    summarize_enabled: bool
    first_delivery_at: datetime | None
    last_delivery_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PodcastEpisodeUpdate(BaseModel):
    is_saved: bool | None = None
    summarize_enabled: bool | None = None
    discovery_status: str | None = Field(None, pattern=r'^(new|accepted|skipped)$')


class PodcastEpisodeBulkAction(BaseModel):
    episode_ids: list[uuid.UUID]
    action: str = Field(pattern=r'^(save|unsave|enable_summarize|disable_summarize|retry|skip|accept)$')


# ---------------------------------------------------------------------------
# Podcast Episode Detail (with artifacts)
# ---------------------------------------------------------------------------

class PodcastArtifactResponse(BaseModel):
    id: uuid.UUID
    episode_id: uuid.UUID
    artifact_type: str
    content: str | None
    prompt_id: uuid.UUID | None
    prompt_version: int | None
    model: str | None
    input_hash: str | None
    word_count: int | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PodcastChunkResponse(BaseModel):
    id: uuid.UUID
    chunk_index: int
    start_seconds: float
    end_seconds: float
    status: str
    transcript_text: str | None
    map_summary_text: str | None
    error_class: str | None
    error_message: str | None
    processing_attempts: int
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class PodcastEpisodeDetailResponse(PodcastEpisodeResponse):
    artifacts: list[PodcastArtifactResponse] = []
    chunks: list[PodcastChunkResponse] = []
    feed_title: str | None = None


# ---------------------------------------------------------------------------
# Podcast Processing Run
# ---------------------------------------------------------------------------

class PodcastProcessingRunResponse(BaseModel):
    id: uuid.UUID
    episode_id: uuid.UUID
    chunk_id: uuid.UUID | None
    stage: str
    status: str
    model: str | None
    prompt_id: uuid.UUID | None
    prompt_version: int | None
    started_at: datetime
    completed_at: datetime | None
    error_class: str | None
    error_message: str | None
    tokens_used: int | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Podcast Mail Policy
# ---------------------------------------------------------------------------

class PodcastMailPolicyCreate(BaseModel):
    name: str = Field(max_length=200)
    schedule_cron: str = Field(max_length=100, pattern=r'^[\d\s\*\/\-\,]+$')
    target_email: str = Field(max_length=255)
    prompt_id: uuid.UUID | None = None
    feed_filter: list[uuid.UUID] | None = None
    enabled: bool = True


class PodcastMailPolicyUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    schedule_cron: str | None = Field(None, max_length=100)
    target_email: str | None = Field(None, max_length=255)
    prompt_id: uuid.UUID | None = None
    feed_filter: list[uuid.UUID] | None = None
    enabled: bool | None = None


class PodcastMailPolicyResponse(BaseModel):
    id: uuid.UUID
    name: str
    schedule_cron: str
    target_email: str
    prompt_id: uuid.UUID | None
    feed_filter: list[uuid.UUID] | None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Podcast Delivery Run
# ---------------------------------------------------------------------------

class PodcastDeliveryRunResponse(BaseModel):
    id: uuid.UUID
    delivery_channel: str
    policy_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    status: str
    episode_count: int
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Queue / Operations Overview
# ---------------------------------------------------------------------------

class PodcastQueueStatus(BaseModel):
    pending_downloads: int
    active_downloads: int
    pending_transcriptions: int
    active_transcriptions: int
    pending_summaries: int
    active_summaries: int
    errors: int
    done_today: int
    total_episodes: int

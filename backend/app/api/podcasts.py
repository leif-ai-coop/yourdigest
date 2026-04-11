"""
Podcast API Router — CRUD for feeds, episodes, prompts, mail policies, queue status.
"""
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.exceptions import NotFoundError
from app.schemas.common import MessageResponse
from app.schemas.podcast import (
    PodcastFeedCreate, PodcastFeedUpdate, PodcastFeedResponse,
    PodcastEpisodeResponse, PodcastEpisodeUpdate, PodcastEpisodeBulkAction,
    PodcastEpisodeDetailResponse, PodcastArtifactResponse, PodcastChunkResponse,
    PodcastPromptCreate, PodcastPromptUpdate, PodcastPromptResponse,
    PodcastMailPolicyCreate, PodcastMailPolicyUpdate, PodcastMailPolicyResponse,
    PodcastProcessingRunResponse, PodcastDeliveryRunResponse,
    PodcastQueueStatus,
)
from app.models.podcast import (
    PodcastFeed, PodcastEpisode, PodcastEpisodeChunk, PodcastArtifact,
    PodcastPrompt, PodcastProcessingRun, PodcastMailPolicy,
    PodcastDeliveryRun, PodcastDeliveryRunEpisode,
)
from app.services.podcast_feed_service import fetch_podcast_feed

router = APIRouter()


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

@router.get("/feeds", response_model=list[PodcastFeedResponse])
async def list_feeds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PodcastFeed).order_by(PodcastFeed.created_at))
    return result.scalars().all()


@router.post("/feeds", response_model=PodcastFeedResponse, status_code=201)
async def create_feed(data: PodcastFeedCreate, db: AsyncSession = Depends(get_db)):
    feed = PodcastFeed(**data.model_dump())
    db.add(feed)
    await db.flush()

    # Immediately fetch to discover episodes
    count = await fetch_podcast_feed(db, feed)
    await db.refresh(feed)
    return feed


@router.put("/feeds/{feed_id}", response_model=PodcastFeedResponse)
async def update_feed(feed_id: uuid.UUID, data: PodcastFeedUpdate, db: AsyncSession = Depends(get_db)):
    feed = await db.get(PodcastFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(feed, key, value)
    await db.flush()
    await db.refresh(feed)
    return feed


@router.delete("/feeds/{feed_id}", response_model=MessageResponse)
async def delete_feed(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    feed = await db.get(PodcastFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    await db.delete(feed)
    return MessageResponse(message="Feed deleted")


@router.post("/feeds/{feed_id}/sync")
async def sync_feed(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    feed = await db.get(PodcastFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    count = await fetch_podcast_feed(db, feed)
    await db.refresh(feed)
    return {"new_episodes": count, "feed": feed.title or feed.url}


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------

@router.get("/episodes", response_model=list[PodcastEpisodeResponse])
async def list_episodes(
    feed_id: uuid.UUID | None = None,
    status: str | None = None,
    discovery: str | None = None,
    saved_only: bool = False,
    search: str | None = None,
    search_fields: str | None = None,  # comma-separated: title,description,summary,transcript
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = select(PodcastEpisode).order_by(desc(PodcastEpisode.published_at))

    if feed_id:
        query = query.where(PodcastEpisode.feed_id == feed_id)
    if status:
        query = query.where(PodcastEpisode.processing_status == status)
    if discovery:
        query = query.where(PodcastEpisode.discovery_status == discovery)
    if saved_only:
        query = query.where(PodcastEpisode.is_saved == True)

    if search and search.strip():
        words = search.strip().lower().split()
        fields = set((search_fields or "title,description,summary,transcript").split(","))
        from sqlalchemy import or_, exists

        # Each word must match in at least one of the selected fields
        for word in words:
            term = f"%{word}%"
            word_conditions = []
            if "title" in fields:
                word_conditions.append(PodcastEpisode.title.ilike(term))
            if "description" in fields:
                word_conditions.append(PodcastEpisode.description.ilike(term))
            if "summary" in fields or "transcript" in fields:
                artifact_conditions = []
                if "summary" in fields:
                    artifact_conditions.append(
                        and_(PodcastArtifact.artifact_type == "summary", PodcastArtifact.is_active == True, PodcastArtifact.content.ilike(term))
                    )
                if "transcript" in fields:
                    artifact_conditions.append(
                        and_(PodcastArtifact.artifact_type == "transcript", PodcastArtifact.is_active == True, PodcastArtifact.content.ilike(term))
                    )
                word_conditions.append(
                    exists().where(
                        and_(PodcastArtifact.episode_id == PodcastEpisode.id, or_(*artifact_conditions))
                    )
                )
            if word_conditions:
                query = query.where(or_(*word_conditions))

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/episodes/{episode_id}", response_model=PodcastEpisodeDetailResponse)
async def get_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PodcastEpisode)
        .options(
            selectinload(PodcastEpisode.artifacts),
            selectinload(PodcastEpisode.chunks),
        )
        .where(PodcastEpisode.id == episode_id)
    )
    episode = result.scalars().first()
    if not episode:
        raise NotFoundError("Episode not found")

    # Get feed title
    feed = await db.get(PodcastFeed, episode.feed_id)
    feed_title = feed.title if feed else None

    exclude_keys = {"_sa_instance_state", "artifacts", "chunks", "feed"}
    ep_dict = {k: v for k, v in episode.__dict__.items() if k not in exclude_keys}
    return PodcastEpisodeDetailResponse(
        **ep_dict,
        artifacts=[PodcastArtifactResponse.model_validate(a) for a in episode.artifacts],
        chunks=[PodcastChunkResponse.model_validate(c) for c in sorted(episode.chunks, key=lambda c: c.chunk_index)],
        feed_title=feed_title,
    )


@router.put("/episodes/{episode_id}", response_model=PodcastEpisodeResponse)
async def update_episode(episode_id: uuid.UUID, data: PodcastEpisodeUpdate, db: AsyncSession = Depends(get_db)):
    episode = await db.get(PodcastEpisode, episode_id)
    if not episode:
        raise NotFoundError("Episode not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(episode, key, value)
    await db.flush()
    await db.refresh(episode)
    return episode


@router.post("/episodes/action", response_model=MessageResponse)
async def bulk_episode_action(data: PodcastEpisodeBulkAction, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PodcastEpisode).where(PodcastEpisode.id.in_(data.episode_ids))
    )
    episodes = result.scalars().all()

    for episode in episodes:
        if data.action == "save":
            episode.is_saved = True
        elif data.action == "unsave":
            episode.is_saved = False
        elif data.action == "enable_summarize":
            episode.summarize_enabled = True
        elif data.action == "disable_summarize":
            episode.summarize_enabled = False
        elif data.action == "retry":
            episode.processing_status = "pending"
            episode.error_class = None
            episode.error_message = None
            episode.locked_at = None
            episode.retry_after = None
        elif data.action == "skip":
            episode.discovery_status = "skipped"
            episode.processing_status = "skipped"
            episode.skipped_reason = "manually skipped"
            episode.summarize_enabled = False
        elif data.action == "accept":
            episode.discovery_status = "accepted"
            episode.skipped_reason = None
            episode.processing_status = "pending"
            episode.summarize_enabled = True
            episode.error_class = None
            episode.error_message = None
            episode.locked_at = None

    return MessageResponse(message=f"{len(episodes)} episodes updated")


@router.post("/episodes/{episode_id}/retry", response_model=PodcastEpisodeResponse)
async def retry_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    episode = await db.get(PodcastEpisode, episode_id)
    if not episode:
        raise NotFoundError("Episode not found")
    episode.processing_status = "pending"
    episode.error_class = None
    episode.error_message = None
    episode.locked_at = None
    episode.retry_after = None
    await db.flush()
    await db.refresh(episode)
    return episode


@router.post("/episodes/{episode_id}/skip", response_model=PodcastEpisodeResponse)
async def skip_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Skip an episode — undo accept, stop processing."""
    episode = await db.get(PodcastEpisode, episode_id)
    if not episode:
        raise NotFoundError("Episode not found")
    episode.discovery_status = "skipped"
    episode.processing_status = "skipped"
    episode.skipped_reason = "manually skipped"
    episode.summarize_enabled = False
    episode.locked_at = None
    await db.flush()
    await db.refresh(episode)
    return episode


@router.post("/episodes/{episode_id}/process")
async def process_episode_now(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Queue an episode for immediate processing. Returns instantly, runs in background."""
    episode = await db.get(PodcastEpisode, episode_id)
    if not episode:
        raise NotFoundError("Episode not found")

    if episode.processing_status == "done":
        return {"message": "Episode already processed", "status": "done"}

    if episode.locked_at is not None:
        return {"message": "Episode is already being processed", "status": "locked"}

    # Accept if skipped
    if episode.discovery_status == "skipped":
        episode.discovery_status = "accepted"
        episode.skipped_reason = None
        episode.summarize_enabled = True

    # Set to pending so the worker picks it up
    episode.processing_status = "pending"
    episode.error_class = None
    episode.error_message = None
    await db.flush()

    # Fire background task
    import asyncio
    asyncio.create_task(_process_episode_background(str(episode_id)))

    return {"message": "Processing started", "status": "started"}


async def _process_episode_background(episode_id_str: str):
    """Run the full pipeline for one episode in the background."""
    import logging
    from uuid import UUID
    from app.database import async_session
    from app.services.podcast_processing_service import (
        download_episode_audio, chunk_episode_audio,
        transcribe_chunk, map_summarize_chunk, reduce_summarize_episode,
        cleanup_episode_audio,
    )

    logger = logging.getLogger(__name__)
    episode_id = UUID(episode_id_str)

    async with async_session() as db:
        try:
            episode = await db.get(PodcastEpisode, episode_id)
            if not episode:
                return
            feed = await db.get(PodcastFeed, episode.feed_id)

            # Stage 1: Download
            if not episode.audio_path:
                if not await download_episode_audio(db, episode):
                    await db.commit()
                    return

            # Stage 2: Chunk
            if not episode.chunk_count:
                if not await chunk_episode_audio(db, episode):
                    await db.commit()
                    return
                episode.processing_status = "transcribing"
                await db.commit()

            # Stage 3: Transcribe
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(PodcastEpisodeChunk)
                .where(PodcastEpisodeChunk.episode_id == episode.id)
                .order_by(PodcastEpisodeChunk.chunk_index)
            )
            chunks = result.scalars().all()

            transcription_model = feed.transcription_model if feed else None
            for chunk in chunks:
                if not chunk.transcript_text:
                    episode.processing_status = "transcribing"
                    await db.flush()
                    if not await transcribe_chunk(db, chunk, model=transcription_model):
                        await db.commit()
                        return
                    await db.commit()

            # Stage 4: Map-summarize
            episode.processing_status = "summarizing_chunks"
            await db.commit()
            map_prompt = None
            if feed and feed.map_prompt_id:
                map_prompt = await db.get(PodcastPrompt, feed.map_prompt_id)
            summary_model = feed.summary_model if feed else None

            for chunk in chunks:
                if not chunk.map_summary_text:
                    if not await map_summarize_chunk(db, chunk, prompt=map_prompt, model=summary_model):
                        await db.commit()
                        return
                    await db.commit()

            # Stage 5: Reduce
            reduce_prompt = None
            if feed and feed.reduce_prompt_id:
                reduce_prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)
            if await reduce_summarize_episode(db, episode, prompt=reduce_prompt, model=summary_model):
                await cleanup_episode_audio(db, episode)
            await db.commit()

            logger.info(f"Background processing completed for episode {episode_id_str}")

        except Exception as e:
            logger.error(f"Background processing failed for episode {episode_id_str}: {e}")
            await db.rollback()


@router.post("/episodes/{episode_id}/resummarize")
async def resummarize_episode(
    episode_id: uuid.UUID,
    prompt_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger re-summarization of an episode (keeps transcript, regenerates summary)."""
    episode = await db.get(PodcastEpisode, episode_id)
    if not episode:
        raise NotFoundError("Episode not found")

    # Check transcript exists
    result = await db.execute(
        select(PodcastArtifact).where(
            PodcastArtifact.episode_id == episode_id,
            PodcastArtifact.artifact_type == "transcript",
            PodcastArtifact.is_active == True,
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("No transcript found — episode must be fully processed first")

    # Reset to summarizing_chunks stage (chunks still have transcripts)
    result = await db.execute(
        select(PodcastEpisodeChunk)
        .where(PodcastEpisodeChunk.episode_id == episode_id)
    )
    chunks = result.scalars().all()

    for chunk in chunks:
        if chunk.transcript_text:
            chunk.map_summary_text = None
            chunk.map_summary_model = None
            chunk.status = "pending"
            chunk.completed_at = None

    episode.processing_status = "pending"
    episode.error_class = None
    episode.error_message = None
    episode.locked_at = None

    await db.flush()
    return {"message": "Re-summarization queued", "episode_id": str(episode_id)}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@router.get("/prompts", response_model=list[PodcastPromptResponse])
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PodcastPrompt).order_by(PodcastPrompt.created_at))
    return result.scalars().all()


@router.post("/prompts", response_model=PodcastPromptResponse, status_code=201)
async def create_prompt(data: PodcastPromptCreate, db: AsyncSession = Depends(get_db)):
    prompt = PodcastPrompt(**data.model_dump())
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.put("/prompts/{prompt_id}", response_model=PodcastPromptResponse)
async def update_prompt(prompt_id: uuid.UUID, data: PodcastPromptUpdate, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(PodcastPrompt, prompt_id)
    if not prompt:
        raise NotFoundError("Prompt not found")

    update_data = data.model_dump(exclude_unset=True)

    # Bump version if system_prompt changes
    if "system_prompt" in update_data and update_data["system_prompt"] != prompt.system_prompt:
        prompt.version += 1

    for key, value in update_data.items():
        setattr(prompt, key, value)

    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.delete("/prompts/{prompt_id}", response_model=MessageResponse)
async def delete_prompt(prompt_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(PodcastPrompt, prompt_id)
    if not prompt:
        raise NotFoundError("Prompt not found")
    await db.delete(prompt)
    return MessageResponse(message="Prompt deleted")


# ---------------------------------------------------------------------------
# Mail Policies
# ---------------------------------------------------------------------------

@router.get("/mail-policies", response_model=list[PodcastMailPolicyResponse])
async def list_mail_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PodcastMailPolicy).order_by(PodcastMailPolicy.created_at))
    return result.scalars().all()


@router.post("/mail-policies", response_model=PodcastMailPolicyResponse, status_code=201)
async def create_mail_policy(data: PodcastMailPolicyCreate, db: AsyncSession = Depends(get_db)):
    policy = PodcastMailPolicy(**data.model_dump())
    db.add(policy)
    await db.flush()
    await db.refresh(policy)

    # Reload scheduler
    from app.worker.scheduler import reload_podcast_mail_schedules
    await reload_podcast_mail_schedules()

    return policy


@router.put("/mail-policies/{policy_id}", response_model=PodcastMailPolicyResponse)
async def update_mail_policy(policy_id: uuid.UUID, data: PodcastMailPolicyUpdate, db: AsyncSession = Depends(get_db)):
    policy = await db.get(PodcastMailPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(policy, key, value)
    await db.flush()
    await db.refresh(policy)

    from app.worker.scheduler import reload_podcast_mail_schedules
    await reload_podcast_mail_schedules()

    return policy


@router.delete("/mail-policies/{policy_id}", response_model=MessageResponse)
async def delete_mail_policy(policy_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    policy = await db.get(PodcastMailPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")
    await db.delete(policy)

    from app.worker.scheduler import reload_podcast_mail_schedules
    await reload_podcast_mail_schedules()

    return MessageResponse(message="Mail policy deleted")


@router.post("/mail-policies/{policy_id}/run")
async def run_mail_policy(
    policy_id: uuid.UUID,
    since_hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    policy = await db.get(PodcastMailPolicy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")

    from app.services.podcast_delivery_service import send_podcast_mail
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    run = await send_podcast_mail(db, policy, since=since)
    return {"status": run.status, "episode_count": run.episode_count, "error": run.error}


# ---------------------------------------------------------------------------
# Processing Runs (operations view)
# ---------------------------------------------------------------------------

@router.get("/processing-runs", response_model=list[PodcastProcessingRunResponse])
async def list_processing_runs(
    episode_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(PodcastProcessingRun).order_by(desc(PodcastProcessingRun.started_at)).limit(limit)
    if episode_id:
        query = query.where(PodcastProcessingRun.episode_id == episode_id)
    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Delivery Runs
# ---------------------------------------------------------------------------

@router.get("/delivery-runs", response_model=list[PodcastDeliveryRunResponse])
async def list_delivery_runs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PodcastDeliveryRun).order_by(desc(PodcastDeliveryRun.started_at)).limit(limit)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Queue Status
# ---------------------------------------------------------------------------

@router.get("/queue", response_model=PodcastQueueStatus)
async def get_queue_status(db: AsyncSession = Depends(get_db)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Count by processing status
    status_counts = {}
    result = await db.execute(
        select(PodcastEpisode.processing_status, func.count(PodcastEpisode.id))
        .group_by(PodcastEpisode.processing_status)
    )
    for status, count in result.all():
        status_counts[status] = count

    # Done today
    result = await db.execute(
        select(func.count(PodcastEpisode.id))
        .where(
            PodcastEpisode.processing_status == "done",
            PodcastEpisode.last_processed_at >= today_start,
        )
    )
    done_today = result.scalar() or 0

    # Total
    result = await db.execute(select(func.count(PodcastEpisode.id)))
    total = result.scalar() or 0

    return PodcastQueueStatus(
        pending_downloads=status_counts.get("pending", 0),
        active_downloads=status_counts.get("downloading", 0) + status_counts.get("chunking", 0),
        pending_transcriptions=status_counts.get("transcribing", 0),
        active_transcriptions=status_counts.get("transcribing", 0),
        pending_summaries=status_counts.get("summarizing_chunks", 0) + status_counts.get("reducing", 0),
        active_summaries=status_counts.get("summarizing_chunks", 0) + status_counts.get("reducing", 0),
        errors=status_counts.get("error", 0),
        done_today=done_today,
        total_episodes=total,
    )

"""
Podcast API Router — CRUD for feeds, episodes, prompts, mail policies, queue status.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, async_session
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
    if status == "active":
        # In-progress (download/chunk/transcribe/summarize) — multiple statuses.
        query = query.where(PodcastEpisode.processing_status.in_(
            ["downloading", "chunking", "transcribing", "summarizing", "summarizing_chunks", "reducing"]
        ))
    elif status:
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
    """Queue an episode for immediate processing. Returns instantly, runs in background sequentially."""
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
    # Must commit before starting worker — worker uses separate session
    await db.commit()

    # Start background worker if not already running
    import asyncio
    task = asyncio.ensure_future(_ensure_queue_worker())
    task.add_done_callback(_worker_done_callback)

    return {"message": "Processing queued", "status": "queued"}


def _worker_done_callback(task):
    """Log any unhandled exception from the queue worker task."""
    if task.exception():
        logging.getLogger(__name__).error(f"Queue worker task crashed: {task.exception()}", exc_info=task.exception())


# ---------------------------------------------------------------------------
# Sequential processing worker (DB-based queue, one at a time)
# ---------------------------------------------------------------------------

_worker_running = False


async def _ensure_queue_worker():
    """Start the queue worker if not already running. Picks pending episodes from DB."""
    global _worker_running
    _log = logging.getLogger(__name__)
    if _worker_running:
        _log.debug("Queue worker already running, skipping")
        return
    _worker_running = True
    _log.info("Queue worker started")

    try:
        while True:
            async with async_session() as db:
                result = await db.execute(
                    select(PodcastEpisode)
                    .where(
                        PodcastEpisode.processing_status == "pending",
                        PodcastEpisode.discovery_status == "accepted",
                        PodcastEpisode.summarize_enabled == True,
                        PodcastEpisode.locked_at.is_(None),
                    )
                    .order_by(PodcastEpisode.created_at.desc())
                    .limit(1)
                )
                episode = result.scalars().first()
                if not episode:
                    _log.info("Queue worker: no more pending episodes, stopping")
                    break
                episode_id = str(episode.id)
                _log.info(f"Queue worker: processing episode {episode.title}")

            try:
                await _process_single_episode(episode_id)
            except Exception as e:
                _log.error(f"Queue worker: episode {episode_id} failed: {e}", exc_info=True)
    except Exception as e:
        _log.error(f"Queue worker error: {e}", exc_info=True)
    finally:
        _worker_running = False
        _log.info("Queue worker stopped")


async def _process_single_episode(episode_id_str: str):
    """Run the full pipeline for one episode. Auto-selects Gemini or OpenRouter path."""
    from uuid import UUID
    from app.services.podcast_processing_service import (
        download_episode_audio, chunk_episode_audio,
        transcribe_chunk, transcribe_episode_gemini,
        summarize_episode, cleanup_episode_audio, _use_gemini_direct,
    )

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

            transcription_model = feed.transcription_model if feed else None

            if _use_gemini_direct():
                # Gemini path: single transcription call on full audio
                if not await transcribe_episode_gemini(db, episode, model=transcription_model):
                    await db.commit()
                    return
            else:
                # OpenRouter path: chunk → transcribe each chunk
                if not episode.chunk_count:
                    if not await chunk_episode_audio(db, episode):
                        await db.commit()
                        return
                    episode.processing_status = "transcribing"
                    await db.commit()

                from sqlalchemy import select as sa_select
                result = await db.execute(
                    sa_select(PodcastEpisodeChunk)
                    .where(PodcastEpisodeChunk.episode_id == episode.id)
                    .order_by(PodcastEpisodeChunk.chunk_index)
                )
                chunks = result.scalars().all()

                for chunk in chunks:
                    if not chunk.transcript_text:
                        episode.processing_status = "transcribing"
                        await db.flush()
                        if not await transcribe_chunk(db, chunk, model=transcription_model):
                            await db.commit()
                            return
                        await db.commit()

            # Stage: Summarize (single call on full transcript)
            reduce_prompt = None
            if feed and feed.reduce_prompt_id:
                reduce_prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)
            summary_model = feed.summary_model if feed else None

            if await summarize_episode(db, episode, prompt=reduce_prompt, model=summary_model):
                await cleanup_episode_audio(db, episode)
            await db.commit()

            logger.info(f"Queue processing completed for episode {episode_id_str}")

        except Exception as e:
            logger.error(f"Queue processing failed for episode {episode_id_str}: {e}")
            await db.rollback()


@router.post("/episodes/{episode_id}/resummarize")
async def resummarize_episode(
    episode_id: uuid.UUID,
    prompt_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Re-summarize an episode using existing transcript. Runs in background."""
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
        raise NotFoundError("Kein Transkript vorhanden — Episode muss erst vollstaendig verarbeitet werden")

    episode.processing_status = "summarizing"
    episode.error_class = None
    episode.error_message = None
    await db.commit()

    # Run summary in background
    import asyncio
    asyncio.ensure_future(_resummarize_background(str(episode_id), str(prompt_id) if prompt_id else None))

    return {"message": "Re-Summarization gestartet", "episode_id": str(episode_id)}


async def _resummarize_background(episode_id_str: str, prompt_id_str: str | None):
    """Run summary on existing transcript in the background."""
    from uuid import UUID
    from app.services.podcast_processing_service import summarize_episode

    try:
        async with async_session() as db:
            episode = await db.get(PodcastEpisode, UUID(episode_id_str))
            if not episode:
                return
            feed = await db.get(PodcastFeed, episode.feed_id)

            prompt = None
            if prompt_id_str:
                prompt = await db.get(PodcastPrompt, UUID(prompt_id_str))
            elif feed and feed.reduce_prompt_id:
                prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)

            summary_model = feed.summary_model if feed and feed.summary_model else None
            await summarize_episode(db, episode, prompt=prompt, model=summary_model)
            await db.commit()
            logger.info(f"Re-summarized episode '{episode.title}'")
    except Exception as e:
        logger.error(f"Re-summarize failed for {episode_id_str}: {e}", exc_info=True)


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
    dump = data.model_dump()
    if dump.get("feed_filter"):
        dump["feed_filter"] = [str(x) for x in dump["feed_filter"]]
    policy = PodcastMailPolicy(**dump)
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
        if key == "feed_filter" and value:
            value = [str(x) for x in value]
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
    policy_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(PodcastDeliveryRun).order_by(desc(PodcastDeliveryRun.started_at)).limit(limit)
    if policy_id:
        query = query.where(PodcastDeliveryRun.policy_id == policy_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/delivery-runs/{run_id}/episodes")
async def get_delivery_run_episodes(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get episodes included in a specific delivery run."""
    result = await db.execute(
        select(
            PodcastDeliveryRunEpisode,
            PodcastEpisode.title,
            PodcastFeed.title.label("feed_title"),
        )
        .join(PodcastEpisode, PodcastEpisode.id == PodcastDeliveryRunEpisode.episode_id)
        .join(PodcastFeed, PodcastFeed.id == PodcastEpisode.feed_id)
        .where(PodcastDeliveryRunEpisode.run_id == run_id)
    )
    return [
        {"episode_title": row[1], "feed_title": row[2]}
        for row in result.all()
    ]


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

    active_statuses = ["downloading", "chunking", "transcribing", "summarizing_chunks", "reducing"]
    active = sum(status_counts.get(s, 0) for s in active_statuses)

    return PodcastQueueStatus(
        queued=status_counts.get("pending", 0),
        active=active,
        manual_queue=1 if _worker_running else 0,
        errors=status_counts.get("error", 0),
        done=status_counts.get("done", 0),
        done_today=done_today,
        skipped=status_counts.get("skipped", 0),
        total_episodes=total,
    )

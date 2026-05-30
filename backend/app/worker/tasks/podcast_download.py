"""
Worker task: Download audio for pending podcast episodes.
Two paths:
  - Gemini API: Download → transcribe full audio (no chunking)
  - OpenRouter: Download → chunk → (transcription handled by podcast_transcribe job)
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.podcast import PodcastEpisode, PodcastFeed
from app.services.podcast_processing_service import (
    download_episode_audio, chunk_episode_audio, transcribe_episode_gemini,
    summarize_episode, cleanup_episode_audio, release_stale_locks, _use_gemini_direct,
)

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 2


async def podcast_download_job():
    """Periodic job: download and process pending podcast episodes."""
    async with async_session() as db:
        try:
            await release_stale_locks(db)
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to release stale locks: {e}")
            await db.rollback()

    async with async_session() as db:
        try:
            result = await db.execute(
                select(PodcastEpisode)
                .where(
                    PodcastEpisode.processing_status == "pending",
                    PodcastEpisode.discovery_status == "accepted",
                    PodcastEpisode.summarize_enabled == True,
                    PodcastEpisode.locked_at.is_(None),
                    PodcastEpisode.audio_url.isnot(None),
                )
                .order_by(PodcastEpisode.published_at.desc())
                .limit(MAX_CONCURRENT)
            )
            episodes = result.scalars().all()

            if not episodes:
                return

            for episode in episodes:
                if episode.retry_after and episode.retry_after > datetime.now(timezone.utc):
                    continue

                # Download
                success = await download_episode_audio(db, episode)
                if not success:
                    await db.commit()
                    continue

                if _use_gemini_direct():
                    # Gemini path: transcribe full audio in one call
                    feed = await db.get(PodcastFeed, episode.feed_id)
                    model = feed.transcription_model if feed and feed.transcription_model else None
                    success = await transcribe_episode_gemini(db, episode, model=model)
                    if not success:
                        await db.commit()
                        continue
                    # Transcription done — summarize immediately
                    from app.models.podcast import PodcastPrompt
                    prompt = None
                    if feed and feed.reduce_prompt_id:
                        prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)
                    summary_model = feed.summary_model if feed and feed.summary_model else None
                    success = await summarize_episode(db, episode, prompt=prompt, model=summary_model)
                    if success:
                        await cleanup_episode_audio(db, episode)
                    await db.commit()
                else:
                    # OpenRouter path: chunk, then transcribe/summarize handled by other workers
                    success = await chunk_episode_audio(db, episode)
                    if success:
                        episode.processing_status = "transcribing"
                    await db.commit()

            logger.info(f"Podcast download job processed {len(episodes)} episodes")

        except Exception as e:
            logger.error(f"Podcast download job error: {e}")
            await db.rollback()

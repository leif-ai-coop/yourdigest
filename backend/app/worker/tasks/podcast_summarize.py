"""
Worker task: Map-summarize chunks + reduce-summarize episodes.
Two phases:
  1. Map: summarize individual chunks (summarizing_chunks)
  2. Reduce: combine chunk summaries into final episode summary (reducing)
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.podcast import (
    PodcastEpisode, PodcastEpisodeChunk, PodcastFeed, PodcastPrompt,
)
from app.services.podcast_processing_service import (
    map_summarize_chunk, reduce_summarize_episode, cleanup_episode_audio,
)

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_RUN = 3


async def podcast_summarize_job():
    """Periodic job: map-summarize chunks and reduce-summarize episodes."""
    async with async_session() as db:
        try:
            # Phase 1: Map-summarize chunks
            result = await db.execute(
                select(PodcastEpisodeChunk)
                .join(PodcastEpisode, PodcastEpisode.id == PodcastEpisodeChunk.episode_id)
                .where(
                    PodcastEpisodeChunk.status == "pending",
                    PodcastEpisodeChunk.transcript_text.isnot(None),
                    PodcastEpisodeChunk.map_summary_text.is_(None),
                    PodcastEpisodeChunk.locked_at.is_(None),
                    PodcastEpisode.processing_status == "summarizing_chunks",
                )
                .order_by(PodcastEpisodeChunk.episode_id, PodcastEpisodeChunk.chunk_index)
                .limit(MAX_CHUNKS_PER_RUN)
            )
            chunks = result.scalars().all()

            for chunk in chunks:
                if chunk.retry_after and chunk.retry_after > datetime.now(timezone.utc):
                    continue

                # Get map prompt from feed config
                episode = await db.get(PodcastEpisode, chunk.episode_id)
                feed = await db.get(PodcastFeed, episode.feed_id) if episode else None
                prompt = None
                if feed and feed.map_prompt_id:
                    prompt = await db.get(PodcastPrompt, feed.map_prompt_id)

                model = feed.summary_model if feed and feed.summary_model else None
                await map_summarize_chunk(db, chunk, prompt=prompt, model=model)
                await db.commit()

            # Phase 2: Check if any episodes are ready for reduce
            result = await db.execute(
                select(PodcastEpisode)
                .where(
                    PodcastEpisode.processing_status == "summarizing_chunks",
                    PodcastEpisode.locked_at.is_(None),
                )
            )
            episodes = result.scalars().all()

            for episode in episodes:
                # Check all chunks are done
                chunk_result = await db.execute(
                    select(PodcastEpisodeChunk)
                    .where(PodcastEpisodeChunk.episode_id == episode.id)
                )
                ep_chunks = chunk_result.scalars().all()

                all_done = all(c.status == "done" for c in ep_chunks)
                if not all_done:
                    continue

                # Get reduce prompt and model
                feed = await db.get(PodcastFeed, episode.feed_id)
                prompt = None
                if feed and feed.reduce_prompt_id:
                    prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)
                model = feed.summary_model if feed and feed.summary_model else None

                success = await reduce_summarize_episode(db, episode, prompt=prompt, model=model)
                await db.commit()

                # Cleanup audio after successful processing
                if success:
                    await cleanup_episode_audio(db, episode)
                    await db.commit()

            if chunks or episodes:
                logger.info(f"Podcast summarize job: {len(chunks)} chunks mapped, {len([e for e in episodes])} episodes checked for reduce")

        except Exception as e:
            logger.error(f"Podcast summarize job error: {e}")
            await db.rollback()

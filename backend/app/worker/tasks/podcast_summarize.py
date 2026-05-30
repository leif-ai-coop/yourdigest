"""
Worker task: Summarize episodes with completed transcripts.
Single summary call on full transcript — no Map-Reduce.
"""
import logging

from sqlalchemy import select

from app.database import async_session
from app.models.podcast import (
    PodcastEpisode, PodcastEpisodeChunk, PodcastFeed, PodcastPrompt,
)
from app.services.podcast_processing_service import summarize_episode, cleanup_episode_audio

logger = logging.getLogger(__name__)


async def podcast_summarize_job():
    """Periodic job: summarize episodes that have all chunks transcribed."""
    async with async_session() as db:
        try:
            # Find episodes ready for summary (transcribing or legacy summarizing_chunks)
            result = await db.execute(
                select(PodcastEpisode)
                .where(
                    PodcastEpisode.processing_status.in_(["transcribing", "summarizing_chunks"]),
                    PodcastEpisode.locked_at.is_(None),
                )
            )
            episodes = result.scalars().all()

            for episode in episodes:
                chunk_result = await db.execute(
                    select(PodcastEpisodeChunk)
                    .where(PodcastEpisodeChunk.episode_id == episode.id)
                )
                chunks = chunk_result.scalars().all()

                if not chunks:
                    continue

                all_transcribed = all(c.transcript_text is not None for c in chunks)
                any_errors = any(c.status == "error" for c in chunks)

                if any_errors:
                    non_retryable = all(not c.is_retryable for c in chunks if c.status == "error")
                    if non_retryable:
                        episode.processing_status = "error"
                        episode.error_class = "transcription"
                        episode.error_message = "One or more chunks failed to transcribe"
                        await db.commit()
                    continue

                if not all_transcribed:
                    continue

                # All chunks transcribed — summarize
                feed = await db.get(PodcastFeed, episode.feed_id)
                prompt = None
                if feed and feed.reduce_prompt_id:
                    prompt = await db.get(PodcastPrompt, feed.reduce_prompt_id)
                model = feed.summary_model if feed and feed.summary_model else None

                success = await summarize_episode(db, episode, prompt=prompt, model=model)
                await db.commit()

                if success:
                    await cleanup_episode_audio(db, episode)
                    await db.commit()

            if episodes:
                logger.info(f"Podcast summarize job checked {len(episodes)} episodes")

        except Exception as e:
            logger.error(f"Podcast summarize job error: {e}")
            await db.rollback()

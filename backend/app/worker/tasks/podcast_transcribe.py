"""
Worker task: Transcribe pending podcast chunks.
Picks chunks with status='pending' that have audio but no transcript.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from app.database import async_session
from app.models.podcast import PodcastEpisode, PodcastEpisodeChunk, PodcastFeed
from app.services.podcast_processing_service import transcribe_chunk

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_RUN = 3


async def podcast_transcribe_job():
    """Periodic job: transcribe pending podcast chunks."""
    async with async_session() as db:
        try:
            # Find chunks that need transcription (have audio, no transcript)
            result = await db.execute(
                select(PodcastEpisodeChunk)
                .join(PodcastEpisode, PodcastEpisode.id == PodcastEpisodeChunk.episode_id)
                .where(
                    PodcastEpisodeChunk.status == "pending",
                    PodcastEpisodeChunk.audio_path.isnot(None),
                    PodcastEpisodeChunk.transcript_text.is_(None),
                    PodcastEpisodeChunk.locked_at.is_(None),
                    PodcastEpisode.processing_status == "transcribing",
                )
                .order_by(PodcastEpisodeChunk.episode_id, PodcastEpisodeChunk.chunk_index)
                .limit(MAX_CHUNKS_PER_RUN)
            )
            chunks = result.scalars().all()

            if not chunks:
                return

            for chunk in chunks:
                if chunk.retry_after and chunk.retry_after > datetime.now(timezone.utc):
                    continue

                # Get model from feed config
                episode = await db.get(PodcastEpisode, chunk.episode_id)
                feed = await db.get(PodcastFeed, episode.feed_id) if episode else None
                model = feed.transcription_model if feed and feed.transcription_model else None

                await transcribe_chunk(db, chunk, model=model)
                await db.commit()

            # Check if any episode has all chunks transcribed → advance to summarizing
            episode_ids = set(c.episode_id for c in chunks)
            for ep_id in episode_ids:
                episode = await db.get(PodcastEpisode, ep_id)
                if not episode or episode.processing_status != "transcribing":
                    continue

                all_chunks = await db.execute(
                    select(PodcastEpisodeChunk)
                    .where(PodcastEpisodeChunk.episode_id == ep_id)
                )
                all_chunks = all_chunks.scalars().all()

                # All chunks must have transcripts (status pending for map_summary or done)
                all_transcribed = all(c.transcript_text is not None for c in all_chunks)
                any_errors = any(c.status == "error" for c in all_chunks)

                if all_transcribed and not any_errors:
                    episode.processing_status = "summarizing_chunks"
                    await db.commit()
                elif any_errors:
                    # Check if all errors are non-retryable
                    non_retryable = all(
                        not c.is_retryable for c in all_chunks if c.status == "error"
                    )
                    if non_retryable:
                        episode.processing_status = "error"
                        episode.error_class = "transcription"
                        episode.error_message = "One or more chunks failed to transcribe"
                        await db.commit()

            logger.info(f"Podcast transcribe job processed {len(chunks)} chunks")

        except Exception as e:
            logger.error(f"Podcast transcribe job error: {e}")
            await db.rollback()

"""
Worker task: Download audio for pending podcast episodes.
Picks episodes with processing_status='pending' and discovery_status='accepted',
downloads audio, then chunks it.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from app.database import async_session
from app.models.podcast import PodcastEpisode
from app.services.podcast_processing_service import (
    download_episode_audio, chunk_episode_audio, release_stale_locks,
)

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 2  # Process up to 2 episodes per run


async def podcast_download_job():
    """Periodic job: download and chunk pending podcast episodes."""
    async with async_session() as db:
        try:
            # Release stale locks first
            await release_stale_locks(db)
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to release stale locks: {e}")
            await db.rollback()

    async with async_session() as db:
        try:
            # Find episodes ready for download
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
                # Check retry_after
                if episode.retry_after and episode.retry_after > datetime.now(timezone.utc):
                    continue

                # Download
                success = await download_episode_audio(db, episode)
                if not success:
                    await db.commit()
                    continue

                # Chunk immediately after download
                success = await chunk_episode_audio(db, episode)
                if success:
                    episode.processing_status = "transcribing"
                await db.commit()

            logger.info(f"Podcast download job processed {len(episodes)} episodes")

        except Exception as e:
            logger.error(f"Podcast download job error: {e}")
            await db.rollback()

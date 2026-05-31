import logging

from app.database import async_session
from app.services.podcast_processing_service import reap_orphan_audio

logger = logging.getLogger(__name__)


async def podcast_cleanup_job():
    """Periodically reap orphaned / stale podcast audio from the volume."""
    try:
        async with async_session() as db:
            await reap_orphan_audio(db)
    except Exception as e:
        logger.error(f"podcast_cleanup_job failed: {e}")

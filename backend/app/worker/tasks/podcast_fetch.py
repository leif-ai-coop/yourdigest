import logging
from app.database import async_session
from app.services.podcast_feed_service import fetch_all_podcast_feeds

logger = logging.getLogger(__name__)


async def podcast_fetch_job():
    """Periodic job: fetch new episodes from all enabled podcast feeds."""
    async with async_session() as db:
        try:
            total = await fetch_all_podcast_feeds(db)
            if total > 0:
                logger.info(f"Podcast fetch complete: {total} new episodes")
            await db.commit()
        except Exception as e:
            logger.error(f"Podcast fetch job error: {e}")
            await db.rollback()

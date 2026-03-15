import logging
from app.database import async_session
from app.services.feed_service import fetch_all_feeds

logger = logging.getLogger(__name__)


async def feed_fetch_job():
    """Periodic job: fetch new items from all enabled RSS feeds."""
    async with async_session() as db:
        try:
            total = await fetch_all_feeds(db)
            if total > 0:
                logger.info(f"Feed fetch complete: {total} new items")
            await db.commit()
        except Exception as e:
            logger.error(f"Feed fetch job error: {e}")
            await db.rollback()

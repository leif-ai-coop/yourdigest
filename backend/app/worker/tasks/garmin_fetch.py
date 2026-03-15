import logging
from app.database import async_session
from app.services.garmin_service import sync_all_accounts

logger = logging.getLogger(__name__)


async def garmin_fetch_job():
    """Periodic job: fetch today's Garmin data for all enabled accounts."""
    async with async_session() as db:
        try:
            count = await sync_all_accounts(db)
            if count > 0:
                logger.info(f"Garmin fetch complete: {count} snapshots")
            await db.commit()
        except Exception as e:
            logger.error(f"Garmin fetch job error: {e}")
            await db.rollback()

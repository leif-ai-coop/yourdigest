import logging
from app.database import async_session
from app.services.weather_service import fetch_all_weather

logger = logging.getLogger(__name__)


async def weather_fetch_job():
    """Periodic job: fetch weather data from all enabled sources."""
    async with async_session() as db:
        try:
            count = await fetch_all_weather(db)
            if count > 0:
                logger.info(f"Weather fetch complete: {count} snapshots")
            await db.commit()
        except Exception as e:
            logger.error(f"Weather fetch job error: {e}")
            await db.rollback()

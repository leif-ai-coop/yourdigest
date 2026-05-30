import logging

from app.database import async_session
from app.services import depot_service

logger = logging.getLogger(__name__)


async def depot_refresh_job():
    """Aktualisiert die Kurse aller aktiven Depot-Positionen via Marktdaten."""
    try:
        async with async_session() as db:
            result = await depot_service.refresh_prices(db)
            await db.commit()
            if result["refreshed"] or result["stale"]:
                logger.info(
                    f"Depot-Refresh: {result['refreshed']} aktualisiert, {result['stale']} ohne Kurs"
                )
    except Exception as e:
        logger.error(f"depot_refresh_job fehlgeschlagen: {e}")

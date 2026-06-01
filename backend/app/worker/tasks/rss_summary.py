import logging
from sqlalchemy import select, func

from app.database import async_session
from app.models.feed import RssFeed, RssItem
from app.services.rss_summary_service import summarize_item, generate_briefing

logger = logging.getLogger(__name__)

# Cost cap per run: at most this many pending item summaries are processed.
MAX_ITEMS_PER_RUN = 10


async def rss_summary_job():
    """Periodic job: summarize queued RSS items, then refresh auto-briefings.

    Items are summarized one at a time (sequential, bounded) and committed
    individually so a single failure never loses prior progress.
    """
    # --- 1. Pending item summaries ---
    async with async_session() as db:
        result = await db.execute(
            select(RssItem.id)
            .where(RssItem.summary_status == "pending")
            .order_by(RssItem.created_at)
            .limit(MAX_ITEMS_PER_RUN)
        )
        item_ids = [row[0] for row in result.all()]

    for item_id in item_ids:
        async with async_session() as db:
            try:
                item = await db.get(RssItem, item_id)
                if not item or item.summary_status != "pending":
                    continue
                await summarize_item(db, item)
                await db.commit()
            except Exception as e:
                logger.error(f"rss_summary_job item {item_id} error: {e}")
                await db.rollback()

    # --- 2. Auto-briefings for feeds with new content ---
    async with async_session() as db:
        result = await db.execute(
            select(RssFeed).where(RssFeed.enabled == True, RssFeed.auto_briefing == True)
        )
        feeds = result.scalars().all()
        due_feed_ids = []
        for feed in feeds:
            if feed.last_briefing_at is None:
                due_feed_ids.append(feed.id)
                continue
            # New items fetched since the last briefing?
            cnt = await db.scalar(
                select(func.count(RssItem.id)).where(
                    RssItem.feed_id == feed.id,
                    RssItem.created_at > feed.last_briefing_at,
                )
            )
            if cnt and cnt > 0:
                due_feed_ids.append(feed.id)

    for feed_id in due_feed_ids:
        async with async_session() as db:
            try:
                feed = await db.get(RssFeed, feed_id)
                if not feed:
                    continue
                briefing = await generate_briefing(db, feed)
                if briefing:
                    logger.info(f"Auto-briefing generated for feed '{feed.title or feed.url}'")
                await db.commit()
            except Exception as e:
                logger.error(f"rss_summary_job briefing {feed_id} error: {e}")
                await db.rollback()

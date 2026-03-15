import logging
from datetime import datetime, timezone

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feed import RssFeed, RssItem

logger = logging.getLogger(__name__)


async def fetch_feed(db: AsyncSession, feed: RssFeed) -> int:
    """Fetch new items from an RSS feed. Returns count of new items."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(feed.url, follow_redirects=True)
            resp.raise_for_status()

        parsed = feedparser.parse(resp.text)

        if parsed.bozo and not parsed.entries:
            error = str(parsed.bozo_exception) if parsed.bozo_exception else "Invalid feed"
            feed.last_error = error[:500]
            return 0

        # Update feed metadata from parsed data
        if parsed.feed.get("title") and not feed.title:
            feed.title = parsed.feed["title"][:200]
        if parsed.feed.get("subtitle") and not feed.description:
            feed.description = parsed.feed["subtitle"][:500]

        new_count = 0
        for entry in parsed.entries:
            guid = entry.get("id") or entry.get("link") or entry.get("title", "")
            if not guid:
                continue

            # Check if item already exists
            existing = await db.execute(
                select(RssItem).where(
                    RssItem.feed_id == feed.id,
                    RssItem.guid == guid,
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Parse published date
            published = None
            if entry.get("published_parsed"):
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass
            elif entry.get("updated_parsed"):
                try:
                    published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            # Get content
            content = None
            if entry.get("content"):
                content = entry.content[0].get("value", "")[:5000]
            elif entry.get("summary"):
                content = entry.summary[:5000]

            summary = entry.get("summary", "")[:1000] if entry.get("summary") else None

            item = RssItem(
                feed_id=feed.id,
                guid=guid,
                title=entry.get("title", "")[:500] if entry.get("title") else None,
                link=entry.get("link", "")[:1000] if entry.get("link") else None,
                summary=summary,
                content=content,
                author=entry.get("author", "")[:200] if entry.get("author") else None,
                published_at=published,
            )
            db.add(item)
            new_count += 1

        feed.last_fetched_at = datetime.now(timezone.utc)
        feed.last_error = None
        return new_count

    except httpx.HTTPError as e:
        feed.last_error = f"HTTP error: {e}"[:500]
        logger.error(f"Feed fetch failed for {feed.url}: {e}")
        return 0
    except Exception as e:
        feed.last_error = str(e)[:500]
        logger.error(f"Feed fetch failed for {feed.url}: {e}")
        return 0


async def fetch_all_feeds(db: AsyncSession) -> int:
    """Fetch all enabled feeds. Returns total new items."""
    result = await db.execute(
        select(RssFeed).where(RssFeed.enabled == True)
    )
    feeds = result.scalars().all()

    total = 0
    for feed in feeds:
        count = await fetch_feed(db, feed)
        if count > 0:
            logger.info(f"Fetched {count} new items from '{feed.title or feed.url}'")
        total += count

    return total

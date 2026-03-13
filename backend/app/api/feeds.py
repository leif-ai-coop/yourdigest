import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.feed import RssFeed, RssItem
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError

router = APIRouter()


@router.get("/")
async def list_feeds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RssFeed))
    return result.scalars().all()


@router.post("/", status_code=201)
async def add_feed(url: str, title: str | None = None, db: AsyncSession = Depends(get_db)):
    feed = RssFeed(url=url, title=title)
    db.add(feed)
    await db.flush()
    await db.refresh(feed)
    return feed


@router.delete("/{feed_id}", response_model=MessageResponse)
async def delete_feed(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    feed = await db.get(RssFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    await db.delete(feed)
    return MessageResponse(message="Feed deleted")


@router.get("/{feed_id}/items")
async def list_items(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RssItem).where(RssItem.feed_id == feed_id).order_by(RssItem.published_at.desc()).limit(50)
    )
    return result.scalars().all()

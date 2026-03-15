import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.feed import RssFeed, RssItem
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.feed_service import fetch_feed

router = APIRouter()


class FeedCreate(BaseModel):
    url: str
    title: str | None = None
    fetch_interval_minutes: int = 60
    enabled: bool = True


class FeedUpdate(BaseModel):
    title: str | None = None
    url: str | None = None
    fetch_interval_minutes: int | None = None
    enabled: bool | None = None


class FeedResponse(BaseModel):
    id: uuid.UUID
    url: str
    title: str | None
    description: str | None
    enabled: bool
    fetch_interval_minutes: int
    last_fetched_at: str | None
    last_error: str | None
    created_at: str

    model_config = {"from_attributes": True}


class FeedItemResponse(BaseModel):
    id: uuid.UUID
    feed_id: uuid.UUID
    guid: str
    title: str | None
    link: str | None
    summary: str | None
    author: str | None
    published_at: str | None
    is_read: bool
    created_at: str

    model_config = {"from_attributes": True}


@router.get("/")
async def list_feeds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RssFeed).order_by(RssFeed.created_at))
    return result.scalars().all()


@router.post("/", status_code=201)
async def add_feed(data: FeedCreate, db: AsyncSession = Depends(get_db)):
    feed = RssFeed(
        url=data.url,
        title=data.title,
        fetch_interval_minutes=data.fetch_interval_minutes,
        enabled=data.enabled,
    )
    db.add(feed)
    await db.flush()

    # Immediately fetch to populate title/items
    count = await fetch_feed(db, feed)
    await db.refresh(feed)
    return feed


@router.put("/{feed_id}")
async def update_feed(feed_id: uuid.UUID, data: FeedUpdate, db: AsyncSession = Depends(get_db)):
    feed = await db.get(RssFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(feed, key, value)
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


@router.post("/{feed_id}/sync")
async def sync_feed(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    feed = await db.get(RssFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    count = await fetch_feed(db, feed)
    await db.refresh(feed)
    return {"new_items": count, "feed": feed.title or feed.url}


@router.get("/{feed_id}/items")
async def list_items(feed_id: uuid.UUID, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RssItem)
        .where(RssItem.feed_id == feed_id)
        .order_by(desc(RssItem.published_at))
        .limit(limit)
    )
    return result.scalars().all()

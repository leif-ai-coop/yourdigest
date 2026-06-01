import uuid
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models.feed import RssFeed, RssItem, RssPrompt, RssBriefing
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.feed_service import fetch_feed

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

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
    auto_summarize_items: bool | None = None
    auto_briefing: bool | None = None
    item_summary_prompt_id: uuid.UUID | None = None
    briefing_prompt_id: uuid.UUID | None = None
    summary_model: str | None = None
    briefing_count: int | None = None


class RssPromptCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    prompt_type: str = "item_summary"  # item_summary | feed_briefing
    is_default: bool = False


class RssPromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    prompt_type: str | None = None
    is_default: bool | None = None


class ItemAction(BaseModel):
    item_ids: list[uuid.UUID]
    action: str  # read | unread | summarize


# ---------------------------------------------------------------------------
# Feeds CRUD
# ---------------------------------------------------------------------------

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
    await fetch_feed(db, feed)
    await db.refresh(feed)
    return feed


# ---------------------------------------------------------------------------
# Items (feed-spanning) — declared before /{feed_id} routes
# ---------------------------------------------------------------------------

@router.get("/items")
async def list_items(
    feed_id: uuid.UUID | None = None,
    is_read: bool | None = None,
    summary_status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Feed-spanning item list with filters + full-text-ish search."""
    query = (
        select(RssItem, RssFeed.title.label("feed_title"))
        .join(RssFeed, RssItem.feed_id == RssFeed.id)
        .order_by(desc(RssItem.published_at), desc(RssItem.created_at))
    )
    if feed_id:
        query = query.where(RssItem.feed_id == feed_id)
    if is_read is not None:
        query = query.where(RssItem.is_read == is_read)
    if summary_status:
        query = query.where(RssItem.summary_status == summary_status)
    if q:
        like = f"%{q}%"
        query = query.where(or_(
            RssItem.title.ilike(like),
            RssItem.summary.ilike(like),
            RssItem.content.ilike(like),
            RssItem.ai_summary.ilike(like),
        ))
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()
    return [
        {
            "id": str(item.id),
            "feed_id": str(item.feed_id),
            "feed_title": feed_title,
            "title": item.title,
            "link": item.link,
            "author": item.author,
            "published_at": str(item.published_at) if item.published_at else None,
            "is_read": item.is_read,
            "summary_status": item.summary_status,
            "has_ai_summary": bool(item.ai_summary),
            "created_at": str(item.created_at),
        }
        for item, feed_title in rows
    ]


@router.get("/items/{item_id}")
async def get_item(item_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    item = await db.get(RssItem, item_id)
    if not item:
        raise NotFoundError("Item not found")
    feed = await db.get(RssFeed, item.feed_id)
    return {
        "id": str(item.id),
        "feed_id": str(item.feed_id),
        "feed_title": feed.title if feed else None,
        "guid": item.guid,
        "title": item.title,
        "link": item.link,
        "author": item.author,
        "summary": item.summary,
        "content": item.content,
        "published_at": str(item.published_at) if item.published_at else None,
        "is_read": item.is_read,
        "ai_summary": item.ai_summary,
        "ai_summary_model": item.ai_summary_model,
        "ai_summarized_at": str(item.ai_summarized_at) if item.ai_summarized_at else None,
        "summary_status": item.summary_status,
        "summary_error": item.summary_error,
        "created_at": str(item.created_at),
    }


class ItemUpdate(BaseModel):
    is_read: bool | None = None


@router.put("/items/{item_id}")
async def update_item(item_id: uuid.UUID, data: ItemUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(RssItem, item_id)
    if not item:
        raise NotFoundError("Item not found")
    if data.is_read is not None:
        item.is_read = data.is_read
    await db.flush()
    return {"id": str(item.id), "is_read": item.is_read}


async def _summarize_item_background(item_id_str: str, prompt_id_str: str | None):
    from app.services.rss_summary_service import summarize_item
    try:
        async with async_session() as db:
            item = await db.get(RssItem, uuid.UUID(item_id_str))
            if not item:
                return
            prompt = await db.get(RssPrompt, uuid.UUID(prompt_id_str)) if prompt_id_str else None
            await summarize_item(db, item, prompt=prompt)
            await db.commit()
    except Exception as e:
        logger.error(f"RSS item summarize (bg) failed for {item_id_str}: {e}", exc_info=True)


@router.post("/items/{item_id}/summarize")
async def summarize_item_endpoint(
    item_id: uuid.UUID,
    prompt_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Summarize (or re-summarize) a single item. Runs in background."""
    item = await db.get(RssItem, item_id)
    if not item:
        raise NotFoundError("Item not found")
    item.summary_status = "pending"
    item.summary_error = None
    await db.commit()
    asyncio.ensure_future(_summarize_item_background(str(item_id), str(prompt_id) if prompt_id else None))
    return {"message": "Zusammenfassung gestartet", "item_id": str(item_id)}


@router.post("/items/action", response_model=MessageResponse)
async def items_action(data: ItemAction, db: AsyncSession = Depends(get_db)):
    for iid in data.item_ids:
        item = await db.get(RssItem, iid)
        if not item:
            continue
        if data.action == "read":
            item.is_read = True
        elif data.action == "unread":
            item.is_read = False
        elif data.action == "summarize":
            item.summary_status = "pending"
            item.summary_error = None
    await db.flush()
    if data.action == "summarize":
        for iid in data.item_ids:
            asyncio.ensure_future(_summarize_item_background(str(iid), None))
    return MessageResponse(message=f"Applied '{data.action}' to {len(data.item_ids)} items")


# ---------------------------------------------------------------------------
# Briefings (feed-spanning history) — declared before /{feed_id}
# ---------------------------------------------------------------------------

@router.get("/briefings")
async def list_briefings(
    feed_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(RssBriefing).order_by(desc(RssBriefing.created_at)).limit(limit)
    if feed_id:
        query = query.where(RssBriefing.feed_id == feed_id)
    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Prompts CRUD — declared before /{feed_id}
# ---------------------------------------------------------------------------

@router.get("/prompts")
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RssPrompt).order_by(RssPrompt.created_at))
    return result.scalars().all()


@router.post("/prompts", status_code=201)
async def create_prompt(data: RssPromptCreate, db: AsyncSession = Depends(get_db)):
    prompt = RssPrompt(**data.model_dump())
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: uuid.UUID, data: RssPromptUpdate, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(RssPrompt, prompt_id)
    if not prompt:
        raise NotFoundError("Prompt not found")
    update_data = data.model_dump(exclude_unset=True)
    if "system_prompt" in update_data and update_data["system_prompt"] != prompt.system_prompt:
        prompt.version += 1
    for key, value in update_data.items():
        setattr(prompt, key, value)
    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.delete("/prompts/{prompt_id}", response_model=MessageResponse)
async def delete_prompt(prompt_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(RssPrompt, prompt_id)
    if not prompt:
        raise NotFoundError("Prompt not found")
    await db.delete(prompt)
    return MessageResponse(message="Prompt deleted")


# ---------------------------------------------------------------------------
# Feed-scoped routes (parametric)
# ---------------------------------------------------------------------------

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
async def list_feed_items(feed_id: uuid.UUID, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RssItem)
        .where(RssItem.feed_id == feed_id)
        .order_by(desc(RssItem.published_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{feed_id}/briefing")
async def get_active_briefing(feed_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RssBriefing)
        .where(RssBriefing.feed_id == feed_id, RssBriefing.is_active == True)
        .order_by(desc(RssBriefing.created_at))
        .limit(1)
    )
    briefing = result.scalar_one_or_none()
    return briefing  # null if none yet


async def _generate_briefing_background(feed_id_str: str, prompt_id_str: str | None):
    from app.services.rss_summary_service import generate_briefing
    try:
        async with async_session() as db:
            feed = await db.get(RssFeed, uuid.UUID(feed_id_str))
            if not feed:
                return
            prompt = await db.get(RssPrompt, uuid.UUID(prompt_id_str)) if prompt_id_str else None
            await generate_briefing(db, feed, prompt=prompt)
            await db.commit()
    except Exception as e:
        logger.error(f"RSS briefing (bg) failed for {feed_id_str}: {e}", exc_info=True)


@router.post("/{feed_id}/briefing")
async def generate_briefing_endpoint(
    feed_id: uuid.UUID,
    prompt_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate a feed briefing over the latest N items. Runs in background."""
    feed = await db.get(RssFeed, feed_id)
    if not feed:
        raise NotFoundError("Feed not found")
    asyncio.ensure_future(_generate_briefing_background(str(feed_id), str(prompt_id) if prompt_id else None))
    return {"message": "Briefing-Erstellung gestartet", "feed_id": str(feed_id)}

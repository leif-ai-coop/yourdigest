"""LLM summarization for RSS: per-article summaries and per-feed briefings.

Mirrors the podcast summarization pattern (podcast_processing_service) but is
much lighter — RSS items already carry text, so there is no download/chunk/
transcribe stage. A summary is a single LLM call over the item (or, for a
briefing, over the latest N items of a feed).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feed import RssFeed, RssItem, RssPrompt, RssBriefing
from app.models.audit import AppSetting
from app.llm.provider import get_llm_provider
from app.services.digest_service import _html_to_text

logger = logging.getLogger(__name__)

DEFAULT_ITEM_PROMPT = (
    "Du bist ein praeziser Nachrichten-Assistent. Fasse den folgenden RSS-Artikel "
    "in wenigen klaren deutschen Saetzen zusammen. Nenne die Kernaussage zuerst, "
    "dann die wichtigsten Details. Keine Einleitung, keine Floskeln, kein Markdown-Titel."
)

DEFAULT_BRIEFING_PROMPT = (
    "Du bist ein Nachrichten-Briefing-Assistent. Fasse die folgenden Artikel eines "
    "RSS-Feeds zu einem kompakten Briefing auf Deutsch zusammen. Gruppiere thematisch, "
    "hebe das Wichtigste hervor und nutze knappe Stichpunkte (Markdown-Listen). "
    "Lass Unwichtiges weg."
)

# Max characters of an item's body fed to the LLM (keeps prompts bounded).
ITEM_TEXT_CAP = 6000
BRIEFING_ITEM_CAP = 1200


def _item_text(item: RssItem) -> str:
    """Build a plain-text representation of an item for the LLM."""
    raw = item.content or item.summary or ""
    text = _html_to_text(raw) if "<" in raw else raw
    parts = []
    if item.title:
        parts.append(item.title.strip())
    if item.author:
        parts.append(f"(von {item.author.strip()})")
    body = text.strip()[:ITEM_TEXT_CAP]
    if body:
        parts.append("\n\n" + body)
    return "\n".join(parts).strip()


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting and setting.value else None


async def _resolve_prompt(
    db: AsyncSession,
    feed: RssFeed | None,
    prompt_type: str,
    explicit: RssPrompt | None,
    feed_prompt_id,
    hardcoded_default: str,
) -> tuple[str, "RssPrompt | None"]:
    """Resolve (system_prompt_text, RssPrompt|None) via:
    explicit arg -> feed-configured prompt -> is_default prompt of type -> hardcoded."""
    if explicit is not None:
        return explicit.system_prompt, explicit
    if feed_prompt_id is not None:
        p = await db.get(RssPrompt, feed_prompt_id)
        if p is not None:
            return p.system_prompt, p
    result = await db.execute(
        select(RssPrompt)
        .where(RssPrompt.prompt_type == prompt_type, RssPrompt.is_default == True)
        .limit(1)
    )
    p = result.scalar_one_or_none()
    if p is not None:
        return p.system_prompt, p
    return hardcoded_default, None


async def _resolve_model(
    db: AsyncSession, feed: RssFeed | None, explicit: str | None, setting_key: str
) -> str | None:
    if explicit:
        return explicit
    if feed is not None and feed.summary_model:
        return feed.summary_model
    return await _get_setting(db, setting_key)  # None -> provider default


async def summarize_item(
    db: AsyncSession,
    item: RssItem,
    prompt: RssPrompt | None = None,
    model: str | None = None,
) -> bool:
    """Summarize a single RSS item. Writes ai_summary onto the item (latest wins)."""
    feed = await db.get(RssFeed, item.feed_id)
    item.summary_status = "processing"
    item.summary_error = None
    await db.flush()

    try:
        system_prompt, used_prompt = await _resolve_prompt(
            db, feed, "item_summary", prompt,
            feed.item_summary_prompt_id if feed else None, DEFAULT_ITEM_PROMPT,
        )
        used_model = await _resolve_model(db, feed, model, "rss_item_summary_model")

        text = _item_text(item)
        if not text:
            item.summary_status = "error"
            item.summary_error = "Kein Inhalt zum Zusammenfassen"
            await db.flush()
            return False

        llm = get_llm_provider()
        result = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            model=used_model,
            temperature=0.3,
            max_tokens=1500,
        )

        item.ai_summary = (result.get("content") or "").strip()
        item.ai_summary_model = result.get("model")
        item.ai_summary_prompt_id = used_prompt.id if used_prompt else None
        item.ai_summary_prompt_version = used_prompt.version if used_prompt else None
        item.ai_summarized_at = datetime.now(timezone.utc)
        item.summary_status = "done"
        item.summary_error = None
        await db.flush()
        return True

    except Exception as e:
        logger.error(f"RSS item summarize failed for {item.id}: {e}")
        item.summary_status = "error"
        item.summary_error = str(e)[:500]
        await db.flush()
        return False


async def generate_briefing(
    db: AsyncSession,
    feed: RssFeed,
    prompt: RssPrompt | None = None,
    model: str | None = None,
) -> RssBriefing | None:
    """Generate a briefing over the latest N items of a feed. Deactivates the
    previous active briefing and stores a new one (history kept)."""
    count = feed.briefing_count or 10
    result = await db.execute(
        select(RssItem)
        .where(RssItem.feed_id == feed.id)
        .order_by(desc(RssItem.published_at))
        .limit(count)
    )
    items = result.scalars().all()
    if not items:
        return None

    system_prompt, used_prompt = await _resolve_prompt(
        db, feed, "feed_briefing", prompt,
        feed.briefing_prompt_id, DEFAULT_BRIEFING_PROMPT,
    )
    used_model = await _resolve_model(db, feed, model, "rss_briefing_model")

    blocks = []
    for it in items:
        body = it.content or it.summary or ""
        body = (_html_to_text(body) if "<" in body else body).strip()[:BRIEFING_ITEM_CAP]
        date_str = it.published_at.strftime("%d.%m.%Y") if it.published_at else ""
        blocks.append(f"## {it.title or 'Ohne Titel'} ({date_str})\n{body}")
    user_content = (
        f"Feed: {feed.title or feed.url}\n\n"
        + "\n\n---\n\n".join(blocks)
    )

    llm = get_llm_provider()
    llm_result = await llm.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        model=used_model,
        temperature=0.3,
        max_tokens=4000,
    )

    # Deactivate previous active briefing(s)
    await db.execute(
        update(RssBriefing)
        .where(RssBriefing.feed_id == feed.id, RssBriefing.is_active == True)
        .values(is_active=False)
    )

    published = [it.published_at for it in items if it.published_at]
    briefing = RssBriefing(
        feed_id=feed.id,
        content=(llm_result.get("content") or "").strip(),
        model=llm_result.get("model"),
        prompt_id=used_prompt.id if used_prompt else None,
        prompt_version=used_prompt.version if used_prompt else None,
        item_count=len(items),
        period_start=min(published) if published else None,
        period_end=max(published) if published else None,
        is_active=True,
    )
    db.add(briefing)
    feed.last_briefing_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(briefing)
    return briefing

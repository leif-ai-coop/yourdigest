"""Dashboard: one aggregated summary endpoint + a per-user layout config.

Each summary block is wrapped in try/except so a single failing module yields
null instead of breaking the whole dashboard. Reuses existing service logic
(depot compute_totals, podcast queue counts, garmin snapshots, mail counts).
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc, func

from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailMessage
from app.models.classification import MailClassification
from app.models.depot import DepotPosition, DepotSnapshot
from app.models.garmin import GarminSnapshot
from app.models.podcast import PodcastEpisode, PodcastFeed
from app.models.feed import RssItem, RssFeed
from app.models.digest import DigestRun, DigestPolicy
from app.models.weather import WeatherSnapshot
from app.models.audit import AuditLog, AppSetting

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_WIDGET_IDS = ["inbox", "weather", "depot", "podcasts", "rss", "digests", "activity"]
# Each Health-page diagram is its own dashboard widget, id "health:<cardId>"
# (cardIds match HealthPage). The dashboard fetches /garmin/data and renders the
# exact same charts via the shared healthCharts module.
HEALTH_CHART_IDS = [
    "body-battery", "heart-rate", "sleep", "steps", "stress", "sleep-stress",
    "hrv", "spo2", "weight", "floors", "training-load", "fitness-age",
    "vo2max", "intensity", "activities",
]
HEALTH_WIDGET_IDS = [f"health:{h}" for h in HEALTH_CHART_IDS]
# Default layout: weather top-right next to inbox; health charts after depot.
DEFAULT_ORDER = ["inbox", "weather", "depot"] + HEALTH_WIDGET_IDS + ["podcasts", "rss", "digests", "activity"]
DEFAULT_VISIBLE_HEALTH = {"health:sleep", "health:stress"}
DEFAULT_HIDDEN = [w for w in HEALTH_WIDGET_IDS if w not in DEFAULT_VISIBLE_HEALTH]


def _valid_id(w: str) -> bool:
    return w in BASE_WIDGET_IDS or (isinstance(w, str) and w.startswith("health:"))


# ---------------------------------------------------------------------------
# Summary blocks
# ---------------------------------------------------------------------------

async def _inbox(db: AsyncSession) -> dict:
    """Inbox stats scoped to the last 24h + category distribution of those mails."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    base = (MailMessage.is_archived == False) & (MailMessage.date >= since)  # noqa: E712
    received = await db.scalar(select(func.count(MailMessage.id)).where(base))
    unread = await db.scalar(select(func.count(MailMessage.id)).where(base, MailMessage.is_read == False))  # noqa: E712
    flagged = await db.scalar(select(func.count(MailMessage.id)).where(base, MailMessage.is_flagged == True))  # noqa: E712
    # Category distribution over the last 24h (multi-category -> count each).
    cat_rows = (await db.execute(
        select(MailClassification.category, func.count(MailClassification.id))
        .join(MailMessage, MailMessage.id == MailClassification.message_id)
        .where(MailMessage.is_archived == False, MailMessage.date >= since)  # noqa: E712
        .group_by(MailClassification.category)
    )).all()
    categories = sorted(
        [{"category": c, "count": n} for c, n in cat_rows],
        key=lambda x: x["count"], reverse=True,
    )
    rows = (await db.execute(
        select(MailMessage).where(base).order_by(desc(MailMessage.date)).limit(5)
    )).scalars().all()
    latest = [{
        "id": str(m.id), "subject": m.subject, "from": m.from_address,
        "date": str(m.date) if m.date else None, "is_read": m.is_read,
    } for m in rows]
    return {"received": received or 0, "unread": unread or 0, "flagged": flagged or 0,
            "categories": categories, "latest": latest}


async def _depot(db: AsyncSession) -> dict:
    from app.services.depot_service import compute_totals
    totals = await compute_totals(db)
    # All snapshots (chronological) -> one point per calendar day (latest of the
    # day). Must NOT row-limit: a single day can hold many refresh snapshots,
    # which would otherwise crowd out earlier days.
    snaps = (await db.execute(
        select(DepotSnapshot).order_by(DepotSnapshot.captured_at)
    )).scalars().all()
    by_day: dict[str, float] = {}
    for s in snaps:
        if s.total_value is not None:
            by_day[s.captured_at.date().isoformat()] = float(s.total_value)
    series = [{"date": d, "value": v} for d, v in list(by_day.items())[-30:]]
    positions = (await db.execute(
        select(DepotPosition).where(DepotPosition.is_active == True)  # noqa: E712
        .order_by(desc(DepotPosition.last_value)).limit(3)
    )).scalars().all()
    top = [{
        "name": p.name, "last_value": float(p.last_value) if p.last_value is not None else None,
        "day_change_pct": float(p.day_change_pct) if p.day_change_pct is not None else None,
    } for p in positions]
    # compute_totals returns datetime for last_update -> stringify
    t = dict(totals)
    if t.get("last_update"):
        t["last_update"] = str(t["last_update"])
    return {"totals": t, "series": series, "top": top}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _podcasts(db: AsyncSession) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    feeds = await db.scalar(select(func.count(PodcastFeed.id)).where(PodcastFeed.enabled == True))  # noqa: E712
    new_24h = await db.scalar(select(func.count(PodcastEpisode.id)).where(PodcastEpisode.published_at >= since))
    rows = (await db.execute(
        select(PodcastEpisode, PodcastFeed.title)
        .join(PodcastFeed, PodcastFeed.id == PodcastEpisode.feed_id)
        .order_by(desc(PodcastEpisode.published_at)).limit(9)
    )).all()
    latest = [{
        "id": str(ep.id), "title": ep.title, "feed": feed_title, "status": ep.processing_status,
        "published_at": str(ep.published_at) if ep.published_at else None,
    } for ep, feed_title in rows]
    return {
        "feeds": feeds or 0,
        "new_24h": new_24h or 0,
        "latest": latest,
    }


async def _rss(db: AsyncSession) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    feeds = await db.scalar(select(func.count(RssFeed.id)).where(RssFeed.enabled == True))  # noqa: E712
    new_24h = await db.scalar(select(func.count(RssItem.id)).where(RssItem.published_at >= since))
    rows = (await db.execute(
        select(RssItem, RssFeed.title).join(RssFeed, RssFeed.id == RssItem.feed_id)
        .order_by(desc(RssItem.published_at)).limit(8)
    )).all()
    latest = [{
        "id": str(it.id), "title": it.title, "feed": feed_title,
        "published_at": str(it.published_at) if it.published_at else None,
    } for it, feed_title in rows]
    return {"feeds": feeds or 0, "new_24h": new_24h or 0, "latest": latest}


async def _digests(db: AsyncSession) -> dict:
    run = (await db.execute(
        select(DigestRun, DigestPolicy.name).join(DigestPolicy, DigestPolicy.id == DigestRun.policy_id)
        .order_by(desc(DigestRun.started_at)).limit(1)
    )).first()
    last = None
    if run:
        r, pname = run
        last = {"policy": pname, "status": r.status, "item_count": r.item_count,
                "started_at": str(r.started_at) if r.started_at else None}
    active = await db.scalar(select(func.count(DigestPolicy.id)).where(DigestPolicy.enabled == True))  # noqa: E712
    return {"last_run": last, "active_policies": active or 0}


async def _weather(db: AsyncSession) -> dict | None:
    snap = (await db.execute(
        select(WeatherSnapshot).order_by(desc(WeatherSnapshot.created_at)).limit(1)
    )).scalar_one_or_none()
    if not snap:
        return None
    cur = (snap.data or {}).get("current") if isinstance(snap.data, dict) else {}
    cur = cur if isinstance(cur, dict) else {}
    forecast = (snap.data or {}).get("forecast") if isinstance(snap.data, dict) else []
    return {
        "source": snap.source_name,
        "summary": snap.summary,
        "temperature": _num(cur.get("temp") if "temp" in cur else cur.get("temperature")),
        "feels_like": _num(cur.get("feels_like")),
        "condition": cur.get("weather_desc") or cur.get("condition"),
        "icon": cur.get("icon_type"),
        "humidity": _num(cur.get("humidity")),
        "wind": _num(cur.get("wind")),
        "uv_index": _num(cur.get("uv_index")),
        "forecast": (forecast or [])[:3],
        "at": str(snap.created_at),
    }


async def _activity(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8)
    )).scalars().all()
    items = [{"action": a.action, "entity_type": a.entity_type, "user": a.user,
              "at": str(a.created_at)} for a in rows]
    return {"recent": items}


_BLOCKS = {
    "inbox": _inbox, "depot": _depot, "podcasts": _podcasts,
    "rss": _rss, "digests": _digests, "weather": _weather, "activity": _activity,
}


@router.get("/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db)):
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat()}
    for key, fn in _BLOCKS.items():
        try:
            out[key] = await fn(db)
        except Exception as e:
            logger.warning(f"dashboard block '{key}' failed: {e}")
            out[key] = None
    return out


# ---------------------------------------------------------------------------
# Layout config (app_setting)
# ---------------------------------------------------------------------------

class DashboardConfig(BaseModel):
    order: list[str] = []
    hidden: list[str] = []


def _default_config() -> dict:
    return {"order": list(DEFAULT_ORDER), "hidden": list(DEFAULT_HIDDEN)}


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    setting = (await db.execute(
        select(AppSetting).where(AppSetting.key == "dashboard_config")
    )).scalar_one_or_none()
    cfg = _default_config()
    if setting and setting.value:
        try:
            stored = json.loads(setting.value)
            order = [w for w in stored.get("order", []) if _valid_id(w)]
            for w in DEFAULT_ORDER:  # append widgets added since the config was saved
                if w not in order:
                    order.append(w)
            hidden = [w for w in stored.get("hidden", []) if _valid_id(w)]
            cfg = {"order": order, "hidden": hidden}
        except (ValueError, TypeError):
            pass
    return cfg


@router.put("/config")
async def set_config(data: DashboardConfig, db: AsyncSession = Depends(get_db)):
    order = [w for w in data.order if _valid_id(w)]
    for w in DEFAULT_ORDER:
        if w not in order:
            order.append(w)
    hidden = [w for w in data.hidden if _valid_id(w)]
    payload = json.dumps({"order": order, "hidden": hidden})
    setting = (await db.execute(
        select(AppSetting).where(AppSetting.key == "dashboard_config")
    )).scalar_one_or_none()
    if setting:
        setting.value = payload
    else:
        db.add(AppSetting(key="dashboard_config", value=payload))
    return {"order": order, "hidden": hidden}

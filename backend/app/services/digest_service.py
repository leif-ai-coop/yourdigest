import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.mail import MailAccount, MailMessage, MailLink
from app.models.classification import MailClassification
from app.models.digest import DigestPolicy, DigestRun, DigestSection
from app.models.feed import RssItem
from app.models.weather import WeatherSnapshot
from app.models.garmin import GarminSnapshot
from app.llm.provider import get_llm_provider
from app.llm.prompt_registry import get_prompt
from app.services.smtp_client import send_email
from app.services.connector_service import decrypt_value

import re
import bleach
import markdown as md
from html.parser import HTMLParser

# Safe HTML tags allowed in LLM-generated content
_LLM_SAFE_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s", "del",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code", "hr",
    "table", "thead", "tbody", "tr", "td", "th",
    "a", "span", "div", "sub", "sup",
]
_LLM_SAFE_ATTRS = {"a": ["href"], "*": ["class"]}


def _safe_llm_html(text: str) -> str:
    """Convert LLM output (Markdown or HTML) to safe HTML for digest emails."""
    # Convert Markdown to HTML first
    html = md.markdown(text, extensions=["tables", "fenced_code"])
    # Sanitize — allow formatting tags, strip dangerous ones
    return bleach.clean(html, tags=_LLM_SAFE_TAGS, attributes=_LLM_SAFE_ATTRS, strip=True)

logger = logging.getLogger(__name__)


def _html_to_text(html: str) -> str:
    """Simple HTML to text conversion without external dependencies."""
    # Remove style and script blocks
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Replace br and p/div/tr/li with newlines
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode common entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

DIGEST_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1729; color: #d4dae4; margin: 0; padding: 0; }}
  .container {{ max-width: 640px; margin: 0 auto; padding: 24px; }}
  .header {{ background: linear-gradient(135deg, #1a2744 0%, #1e3a5f 100%); border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center; }}
  .header h1 {{ color: #5b9cf6; margin: 0 0 4px 0; font-size: 22px; }}
  .header p {{ color: #7a8ba8; margin: 0; font-size: 13px; }}
  .section {{ background: #151d30; border: 1px solid #1e2d4a; border-radius: 10px; margin-bottom: 16px; overflow: hidden; }}
  .section-header {{ padding: 14px 18px; border-bottom: 1px solid #1e2d4a; }}
  .section-header h2 {{ margin: 0; font-size: 15px; color: #e2e8f0; }}
  .section-badge {{ background: #1e3a5f; color: #5b9cf6; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }}
  .section-body {{ padding: 14px 18px; }}
  .mail-item {{ padding: 10px 0; border-bottom: 1px solid #1a2540; }}
  .mail-item:last-child {{ border-bottom: none; }}
  .mail-from {{ font-size: 13px; font-weight: 600; color: #e2e8f0; }}
  .mail-subject {{ font-size: 13px; color: #a0aec0; margin-top: 2px; }}
  .mail-summary {{ font-size: 12px; color: #7a8ba8; margin-top: 4px; line-height: 1.5; }}
  .mail-meta {{ font-size: 11px; color: #5a6a85; margin-top: 4px; }}
  .action-badge {{ display: inline-block; background: #3b2f1a; color: #f6ad55; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }}
  .priority-badge {{ display: inline-block; background: #3b1a1a; color: #fc8181; font-size: 11px; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }}
  .ai-summary {{ background: #1a2540; border-left: 3px solid #5b9cf6; padding: 12px 16px; margin: 12px 0; border-radius: 0 8px 8px 0; font-size: 13px; line-height: 1.6; color: #a0aec0; }}
  .footer {{ text-align: center; padding: 16px; color: #5a6a85; font-size: 11px; }}
  .weather-data {{ font-size: 13px; color: #a0aec0; line-height: 1.6; }}
  .feed-item {{ padding: 8px 0; border-bottom: 1px solid #1a2540; }}
  .feed-item:last-child {{ border-bottom: none; }}
  .feed-title {{ font-size: 13px; color: #5b9cf6; text-decoration: none; }}
  .feed-source {{ font-size: 11px; color: #5a6a85; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>You Digest</h1>
    <p>{date} &middot; {item_count} items</p>
  </div>

  {weather_section}

  {ai_summary_section}

  {sections}

  <div class="footer">
    Generated by You Digest &middot; {date}
  </div>
</div>
</body>
</html>"""


async def collect_mail_items(
    db: AsyncSession, policy: DigestPolicy, since: datetime
) -> list[dict]:
    """Collect mail items based on policy filters."""
    query = (
        select(MailMessage)
        .options(selectinload(MailMessage.links))
        .where(MailMessage.date >= since)
        .order_by(desc(MailMessage.date))
    )

    result = await db.execute(query)
    messages = result.scalars().all()

    items = []
    for msg in messages:
        cls_result = await db.execute(
            select(MailClassification).where(MailClassification.message_id == msg.id)
        )
        classification = cls_result.scalars().first()
        category = classification.category if classification else "uncategorized"

        if policy.include_categories:
            if category not in policy.include_categories:
                continue
        if policy.exclude_categories:
            if category in policy.exclude_categories:
                continue

        # Extract unsubscribe links from mail links
        unsubscribe_links = []
        for link in msg.links:
            link_text = (link.text or "").lower()
            link_url = (link.url or "").lower()
            if any(kw in link_text or kw in link_url for kw in ["unsubscribe", "abmelden", "abbestellen", "opt-out", "optout"]):
                unsubscribe_links.append(link.url)

        # Get body text for LLM context (up to 2000 chars for content depth)
        body_snippet = None
        if msg.body_text:
            body_snippet = msg.body_text[:2000].strip()
        elif msg.body_html:
            # Fallback: extract text from HTML
            body_snippet = _html_to_text(msg.body_html)[:2000].strip()

        items.append({
            "id": str(msg.id),
            "from": msg.from_address,
            "subject": msg.subject or "(no subject)",
            "date": str(msg.date),
            "category": category,
            "priority": classification.priority if classification else 0,
            "summary": classification.summary if classification else None,
            "action_required": classification.action_required if classification else False,
            "is_read": msg.is_read,
            "body_snippet": body_snippet,
            "unsubscribe_link": unsubscribe_links[0] if unsubscribe_links else None,
            "due_date": classification.due_date if classification and classification.due_date else None,
        })

    return items


async def collect_weather_data(db: AsyncSession) -> dict | None:
    """Get latest weather snapshot."""
    result = await db.execute(
        select(WeatherSnapshot).order_by(desc(WeatherSnapshot.created_at)).limit(1)
    )
    snapshot = result.scalars().first()
    if not snapshot:
        return None
    return {"data": snapshot.data, "summary": snapshot.summary, "fetched_at": str(snapshot.created_at)}


async def collect_feed_items(db: AsyncSession, since: datetime, limit: int = 50) -> list[dict]:
    """Collect recent RSS feed items."""
    from app.models.feed import RssFeed
    result = await db.execute(
        select(RssItem, RssFeed.title.label("feed_title"))
        .join(RssFeed, RssItem.feed_id == RssFeed.id)
        .where(RssItem.published_at >= since)
        .order_by(desc(RssItem.published_at))
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "title": item.title,
            "link": item.link,
            "summary": item.summary[:200] if item.summary else None,
            "published": str(item.published_at),
            "source": feed_title or "RSS",
        }
        for item, feed_title in rows
    ]


async def get_digest_thresholds(db: AsyncSession) -> tuple[int, int]:
    """Get detail and compact thresholds from settings."""
    from app.models.audit import AppSetting
    detail = 50
    compact = 200
    for key, default in [("digest_detail_threshold", 50), ("digest_compact_threshold", 200)]:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalars().first()
        if setting and setting.value:
            try:
                val = int(setting.value)
                if key == "digest_detail_threshold":
                    detail = val
                else:
                    compact = val
            except ValueError:
                pass
    return detail, compact


INBOX_BASE_URL = "https://assistant.curaos.de"


def _inbox_link(item: dict) -> str:
    """Generate a link to the mail in the inbox."""
    return f'{INBOX_BASE_URL}/?msg={item["id"]}'


def _unsub_link_html(item: dict) -> str:
    """Render a small unsubscribe link if available."""
    if item.get("unsubscribe_link"):
        return f' <a href="{item["unsubscribe_link"]}" style="font-size:10px;color:#7a8ba8;text-decoration:none;margin-left:6px">abmelden</a>'
    return ""


def render_mail_section(items: list[dict], detail_threshold: int = 50, compact_threshold: int = 200) -> str:
    """Render mail items as HTML grouped by category.

    Tiered display:
    - Up to detail_threshold: full detail (sender, subject, summary, badges)
    - Up to compact_threshold: compact (sender + subject, one line)
    - Beyond: only category counts with a note
    """
    if not items:
        return ""

    total = len(items)
    categories: dict[str, list[dict]] = {}
    for item in items:
        categories.setdefault(item["category"], []).append(item)

    # Beyond compact threshold: counts only
    if total > compact_threshold:
        rows = ""
        for category, cat_items in sorted(categories.items()):
            action_count = sum(1 for i in cat_items if i.get("action_required"))
            high_pri = sum(1 for i in cat_items if i.get("priority", 0) >= 4)
            extras = ""
            if action_count:
                extras += f' <span class="action-badge">{action_count} action required</span>'
            if high_pri:
                extras += f' <span class="priority-badge">{high_pri} high priority</span>'
            rows += f"""
      <div class="mail-item" style="padding:6px 0">
        <span class="mail-from">{category.title()}</span>
        <span class="section-badge">{len(cat_items)}</span>{extras}
      </div>"""

        return f"""
  <div class="section">
    <div class="section-header">
      <h2>📧 Email Overview<span class="section-badge">{total}</span></h2>
    </div>
    <div class="section-body">
      <div class="mail-summary" style="margin-bottom:12px">
        {total} emails — showing category breakdown only.
      </div>{rows}
    </div>
  </div>"""

    # Compact mode: sender + subject + inbox link + unsubscribe
    if total > detail_threshold:
        html_parts = []
        for category, cat_items in sorted(categories.items()):
            rows = ""
            for item in cat_items:
                badges = ""
                if item.get("action_required"):
                    badges += '<span class="action-badge">!</span>'
                if item.get("priority", 0) >= 4:
                    badges += '<span class="priority-badge">▲</span>'
                inbox = _inbox_link(item)
                unsub = _unsub_link_html(item)
                rows += f"""
      <div class="mail-item" style="padding:4px 0">
        <a href="{inbox}" style="font-size:12px;color:#e2e8f0;text-decoration:none;font-weight:600">{item['from']}</a>{badges}
        <span class="mail-subject" style="display:inline;margin-left:8px;font-size:12px">{item['subject']}</span>{unsub}
      </div>"""

            html_parts.append(f"""
  <div class="section">
    <div class="section-header">
      <h2>📧 {category.title()}<span class="section-badge">{len(cat_items)}</span></h2>
    </div>
    <div class="section-body">{rows}
    </div>
  </div>""")

        return "\n".join(html_parts)

    # Full detail mode
    html_parts = []
    for category, cat_items in sorted(categories.items()):
        rows = ""
        for item in cat_items:
            badges = ""
            if item.get("action_required"):
                badges += '<span class="action-badge">Action Required</span>'
            if item.get("priority", 0) >= 4:
                badges += '<span class="priority-badge">High Priority</span>'
            inbox = _inbox_link(item)
            unsub = _unsub_link_html(item)

            rows += f"""
      <div class="mail-item">
        <div class="mail-from"><a href="{inbox}" style="color:#e2e8f0;text-decoration:none">{item['from']}</a>{badges}{unsub}</div>
        <div class="mail-subject"><a href="{inbox}" style="color:#a0aec0;text-decoration:none">{item['subject']}</a></div>
        {f'<div class="mail-summary">{item["summary"]}</div>' if item.get("summary") else ""}
        <div class="mail-meta">{item['date']}</div>
      </div>"""

        html_parts.append(f"""
  <div class="section">
    <div class="section-header">
      <h2>📧 {category.title()}<span class="section-badge">{len(cat_items)}</span></h2>
    </div>
    <div class="section-body">{rows}
    </div>
  </div>""")

    return "\n".join(html_parts)


def render_unsubscribe_section(items: list[dict]) -> str:
    """Render a complete list of all unsubscribe links."""
    unsub_items = [(item["from"], item["unsubscribe_link"]) for item in items if item.get("unsubscribe_link")]
    if not unsub_items:
        return ""

    rows = ""
    for sender, link in unsub_items:
        rows += f"""
      <tr>
        <td style="padding:4px 8px;font-size:12px;color:#a0aec0;border-bottom:1px solid #1a2540">{sender}</td>
        <td style="padding:4px 8px;border-bottom:1px solid #1a2540"><a href="{link}" style="font-size:12px;color:#5b9cf6;text-decoration:none">Abmelden</a></td>
      </tr>"""

    return f"""
  <div class="section">
    <div class="section-header">
      <h2>🔕 Abmeldelinks<span class="section-badge">{len(unsub_items)}</span></h2>
    </div>
    <div class="section-body">
      <table style="width:100%;border-collapse:collapse">
        <tr>
          <th style="text-align:left;padding:4px 8px;font-size:11px;color:#7a8ba8;border-bottom:1px solid #1e2d4a">Absender</th>
          <th style="text-align:left;padding:4px 8px;font-size:11px;color:#7a8ba8;border-bottom:1px solid #1e2d4a">Link</th>
        </tr>{rows}
      </table>
    </div>
  </div>"""


def _google_calendar_url(title: str, due_date: str, all_day: bool = True) -> str:
    """Build a Google Calendar 'add event' URL."""
    from urllib.parse import quote
    try:
        dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""

    if all_day:
        start = dt.strftime("%Y%m%d")
        end = (dt + timedelta(days=1)).strftime("%Y%m%d")
    else:
        start = dt.strftime("%Y%m%dT%H%M%SZ")
        end = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")

    return f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(title)}&dates={start}/{end}"


def render_events_section(items: list[dict]) -> str:
    """Render a section with all detected dates/deadlines and Google Calendar links."""
    events = []
    for item in items:
        if item.get("due_date"):
            events.append(item)
    if not events:
        return ""

    rows = ""
    for item in events:
        try:
            dt = datetime.fromisoformat(item["due_date"].replace("Z", "+00:00"))
            date_str = dt.strftime("%d.%m.%Y")
            has_time = dt.hour != 0 or dt.minute != 0
            if has_time:
                date_str += dt.strftime(" %H:%M")
        except (ValueError, AttributeError):
            date_str = str(item["due_date"])
            has_time = False

        title = item["subject"]
        cal_url = _google_calendar_url(title, item["due_date"], all_day=not has_time)
        inbox_url = f'{INBOX_BASE_URL}/?msg={item["id"]}'

        rows += f"""
      <tr>
        <td style="padding:6px 8px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1a2540">
          <a href="{inbox_url}" style="color:#e2e8f0;text-decoration:none">{title}</a>
        </td>
        <td style="padding:6px 8px;font-size:12px;color:#a0aec0;border-bottom:1px solid #1a2540;white-space:nowrap">{date_str}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a2540">
          <a href="{cal_url}" style="font-size:11px;color:#5b9cf6;text-decoration:none;white-space:nowrap">📅 Kalender</a>
        </td>
      </tr>"""

    return f"""
  <div class="section">
    <div class="section-header">
      <h2>📅 Termine &amp; Fristen<span class="section-badge">{len(events)}</span></h2>
    </div>
    <div class="section-body">
      <table style="width:100%;border-collapse:collapse">
        <tr>
          <th style="text-align:left;padding:4px 8px;font-size:11px;color:#7a8ba8;border-bottom:1px solid #1e2d4a">Betreff</th>
          <th style="text-align:left;padding:4px 8px;font-size:11px;color:#7a8ba8;border-bottom:1px solid #1e2d4a">Datum</th>
          <th style="text-align:left;padding:4px 8px;font-size:11px;color:#7a8ba8;border-bottom:1px solid #1e2d4a"></th>
        </tr>{rows}
      </table>
    </div>
  </div>"""


WEATHER_ICONS = {
    "clear": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="14" fill="#FBBF24"/><g stroke="#FBBF24" stroke-width="3" stroke-linecap="round"><line x1="32" y1="4" x2="32" y2="12"/><line x1="32" y1="52" x2="32" y2="60"/><line x1="4" y1="32" x2="12" y2="32"/><line x1="52" y1="32" x2="60" y2="32"/><line x1="12.2" y1="12.2" x2="17.9" y2="17.9"/><line x1="46.1" y1="46.1" x2="51.8" y2="51.8"/><line x1="12.2" y1="51.8" x2="17.9" y2="46.1"/><line x1="46.1" y1="17.9" x2="51.8" y2="12.2"/></g></svg>',
    "mostly_clear": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><circle cx="26" cy="24" r="11" fill="#FBBF24"/><g stroke="#FBBF24" stroke-width="2.5" stroke-linecap="round"><line x1="26" y1="5" x2="26" y2="11"/><line x1="26" y1="37" x2="26" y2="43"/><line x1="7" y1="24" x2="13" y2="24"/><line x1="39" y1="24" x2="45" y2="24"/></g><path d="M20 38 Q20 30 28 30 Q30 24 38 24 Q46 24 48 30 Q54 30 54 38 Q54 44 48 44 L22 44 Q16 44 16 38 Q16 34 20 38Z" fill="#94A3B8" opacity="0.7"/></svg>',
    "partly_cloudy": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><circle cx="24" cy="22" r="10" fill="#FBBF24"/><g stroke="#FBBF24" stroke-width="2" stroke-linecap="round"><line x1="24" y1="5" x2="24" y2="10"/><line x1="24" y1="34" x2="24" y2="39"/><line x1="7" y1="22" x2="12" y2="22"/><line x1="36" y1="22" x2="41" y2="22"/></g><path d="M18 40 Q18 32 26 32 Q28 26 36 26 Q44 26 46 32 Q52 32 52 40 Q52 46 46 46 L20 46 Q14 46 14 40 Q14 36 18 40Z" fill="#94A3B8"/></svg>',
    "cloudy": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M14 44 Q14 34 24 34 Q26 26 36 26 Q46 26 48 34 Q56 34 56 44 Q56 50 48 50 L18 50 Q10 50 10 44 Q10 38 14 44Z" fill="#94A3B8"/><path d="M24 36 Q24 28 32 28 Q34 22 42 22 Q50 22 52 28 Q58 28 58 36 Q58 40 52 40 L28 40 Q22 40 22 36Z" fill="#CBD5E1" opacity="0.6"/></svg>',
    "fog": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><g stroke="#94A3B8" stroke-width="3" stroke-linecap="round" opacity="0.7"><line x1="10" y1="24" x2="54" y2="24"/><line x1="14" y1="32" x2="50" y2="32"/><line x1="10" y1="40" x2="54" y2="40"/><line x1="18" y1="48" x2="46" y2="48"/></g></svg>',
    "drizzle": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M14 32 Q14 24 22 24 Q24 18 32 18 Q40 18 42 24 Q48 24 48 32 Q48 36 42 36 L16 36 Q10 36 10 32Z" fill="#94A3B8"/><g stroke="#60A5FA" stroke-width="2" stroke-linecap="round" opacity="0.7"><line x1="20" y1="42" x2="18" y2="48"/><line x1="32" y1="42" x2="30" y2="48"/><line x1="44" y1="42" x2="42" y2="48"/></g></svg>',
    "rain": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M14 30 Q14 22 22 22 Q24 16 32 16 Q40 16 42 22 Q48 22 48 30 Q48 34 42 34 L16 34 Q10 34 10 30Z" fill="#64748B"/><g stroke="#3B82F6" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="40" x2="14" y2="50"/><line x1="28" y1="40" x2="24" y2="50"/><line x1="38" y1="40" x2="34" y2="50"/><line x1="48" y1="40" x2="44" y2="50"/></g></svg>',
    "heavy_rain": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M12 28 Q12 20 20 20 Q22 14 32 14 Q42 14 44 20 Q50 20 50 28 Q50 32 44 32 L16 32 Q8 32 8 28Z" fill="#475569"/><g stroke="#2563EB" stroke-width="3" stroke-linecap="round"><line x1="16" y1="38" x2="10" y2="52"/><line x1="26" y1="38" x2="20" y2="52"/><line x1="36" y1="38" x2="30" y2="52"/><line x1="46" y1="38" x2="40" y2="52"/><line x1="56" y1="38" x2="50" y2="52"/></g></svg>',
    "snow": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M14 30 Q14 22 22 22 Q24 16 32 16 Q40 16 42 22 Q48 22 48 30 Q48 34 42 34 L16 34 Q10 34 10 30Z" fill="#94A3B8"/><g fill="#E2E8F0"><circle cx="18" cy="42" r="3"/><circle cx="32" cy="44" r="3"/><circle cx="46" cy="42" r="3"/><circle cx="24" cy="52" r="2.5"/><circle cx="40" cy="52" r="2.5"/></g></svg>',
    "thunderstorm": '<svg viewBox="0 0 64 64" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg"><path d="M12 28 Q12 20 20 20 Q22 14 32 14 Q42 14 44 20 Q50 20 50 28 Q50 32 44 32 L16 32 Q8 32 8 28Z" fill="#475569"/><polygon points="30,36 24,48 32,48 26,60 42,44 34,44 38,36" fill="#FBBF24"/><g stroke="#3B82F6" stroke-width="2" stroke-linecap="round" opacity="0.6"><line x1="16" y1="38" x2="14" y2="46"/><line x1="48" y1="38" x2="46" y2="46"/></g></svg>',
}


def _weather_icon_svg(icon_type: str, size: int = 40) -> str:
    """Get inline SVG for a weather icon type."""
    template = WEATHER_ICONS.get(icon_type, WEATHER_ICONS["clear"])
    return template.format(size=size)


DEFAULT_WEATHER_PROMPT = """Du bist ein freundlicher Wetter-Berater. Schreibe eine kurze, praktische Wetterzusammenfassung auf Deutsch.

Regeln:
- Maximal 3-4 kurze Sätze
- Sag wie der Tag wird und was man anziehen sollte
- Erwähne ob Regenschirm/Jacke/Sonnencreme nötig ist
- Kurzer Ausblick auf die nächsten Tage
- Lockerer, freundlicher Ton
- Nur reinen Text, kein HTML, kein Markdown"""


async def generate_weather_summary(db: AsyncSession, weather_data: dict, custom_prompt: str | None = None) -> str | None:
    """Generate a short, actionable weather summary via LLM."""
    try:
        provider = get_llm_provider()

        current = weather_data.get("current", {})
        periods = weather_data.get("today_periods", [])
        forecast = weather_data.get("forecast", [])
        location = weather_data.get("location", "")

        weather_text = f"Standort: {location}\n"
        weather_text += f"Aktuell: {current.get('temp')}°C (gefühlt {current.get('feels_like')}°C), {current.get('weather_desc')}\n"
        weather_text += f"Wind: {current.get('wind')} km/h, Luftfeuchtigkeit: {current.get('humidity')}%\n\n"
        weather_text += "Tagesverlauf heute:\n"
        for p in periods:
            weather_text += f"  {p['name']}: {p['temp_avg']}°C ({p['temp_min']}–{p['temp_max']}°C), {p['weather_desc']}"
            if p.get('precip_probability', 0) > 0:
                weather_text += f", Regenwahrscheinlichkeit {p['precip_probability']}%"
            if p.get('precipitation', 0) > 0:
                weather_text += f", {p['precipitation']}mm Niederschlag"
            weather_text += f", Wind {p['wind_avg']} km/h\n"

        weather_text += "\nVorhersage:\n"
        for d in forecast:
            weather_text += f"  {d['date']}: {d['temp_min']}–{d['temp_max']}°C, {d['weather_desc']}"
            if d.get('precipitation_sum', 0) > 0:
                weather_text += f", {d['precipitation_sum']}mm"
            if d.get('precip_probability', 0) > 0:
                weather_text += f", {d['precip_probability']}% Regen"
            weather_text += f", UV {d.get('uv_index', 0)}\n"

        system_prompt = custom_prompt or DEFAULT_WEATHER_PROMPT

        result = await provider.chat_and_log(
            db, "weather_summary",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": weather_text},
            ],
            max_tokens=300,
        )
        return result.get("content", "").strip()
    except Exception as e:
        logger.error(f"Weather LLM summary failed: {e}")
        return None


def render_weather_section(weather: dict | None, ai_summary: str | None = None) -> str:
    """Render a visual weather banner with icons."""
    if not weather:
        return ""

    data = weather.get("data")
    if not data or not isinstance(data, dict):
        # Legacy format fallback
        summary = weather.get("summary", "")
        if not summary:
            return ""
        return f"""
  <div class="section">
    <div class="section-header"><h2>🌤 Wetter</h2></div>
    <div class="section-body" style="font-size:13px;color:#a0aec0">{summary}</div>
  </div>"""

    current = data.get("current", {})
    periods = data.get("today_periods", [])
    forecast = data.get("forecast", [])
    location = data.get("location", "")

    # Current weather hero
    current_icon = _weather_icon_svg(current.get("icon_type", "clear"), 56)
    current_temp = current.get("temp", "?")
    current_desc = current.get("weather_desc", "")
    feels_like = current.get("feels_like", "?")

    # AI summary
    ai_html = ""
    if ai_summary:
        ai_html = f'<div style="font-size:13px;color:#d4dae4;line-height:1.6;margin-top:12px;padding:10px 14px;background:#1a2540;border-radius:8px">{_safe_llm_html(ai_summary)}</div>'

    # Today periods with icons (4 columns)
    periods_html = ""
    if periods:
        cols = ""
        for p in periods:
            icon = _weather_icon_svg(p.get("icon_type", "clear"), 36)
            precip = f'<div style="font-size:10px;color:#60A5FA">💧 {p["precip_probability"]}%</div>' if p.get("precip_probability", 0) > 20 else ""
            cols += f"""
        <td style="text-align:center;padding:8px 4px;width:25%">
          <div style="font-size:11px;color:#7a8ba8;margin-bottom:4px">{p['name']}</div>
          <div style="margin:0 auto;width:36px">{icon}</div>
          <div style="font-size:15px;font-weight:600;color:#e2e8f0;margin-top:4px">{p['temp_avg']}°</div>
          <div style="font-size:10px;color:#7a8ba8">{p['temp_min']}–{p['temp_max']}°</div>
          {precip}
        </td>"""

        periods_html = f"""
      <div style="margin-top:16px;border-top:1px solid #1e2d4a;padding-top:12px">
        <div style="font-size:11px;color:#7a8ba8;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px">Tagesverlauf</div>
        <table style="width:100%;border-collapse:collapse"><tr>{cols}</tr></table>
      </div>"""

    # Forecast days
    forecast_html = ""
    if forecast:
        fcols = ""
        day_names = {"Monday": "Mo", "Tuesday": "Di", "Wednesday": "Mi", "Thursday": "Do", "Friday": "Fr", "Saturday": "Sa", "Sunday": "So"}
        for d in forecast:
            icon = _weather_icon_svg(d.get("icon_type", "clear"), 32)
            try:
                dt = datetime.fromisoformat(d["date"])
                day_label = day_names.get(dt.strftime("%A"), dt.strftime("%a"))
                date_label = dt.strftime("%d.%m.")
            except (ValueError, KeyError):
                day_label = d.get("date", "?")
                date_label = ""
            precip = f'<div style="font-size:10px;color:#60A5FA">💧 {d["precip_probability"]}%</div>' if d.get("precip_probability", 0) > 20 else ""
            fcols += f"""
        <td style="text-align:center;padding:8px 4px">
          <div style="font-size:12px;font-weight:600;color:#a0aec0">{day_label}</div>
          <div style="font-size:10px;color:#5a6a85">{date_label}</div>
          <div style="margin:4px auto;width:32px">{icon}</div>
          <div style="font-size:13px;color:#e2e8f0">{d['temp_min']}–{d['temp_max']}°</div>
          {precip}
        </td>"""

        forecast_html = f"""
      <div style="margin-top:12px;border-top:1px solid #1e2d4a;padding-top:12px">
        <div style="font-size:11px;color:#7a8ba8;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px">Nächste Tage</div>
        <table style="width:100%;border-collapse:collapse"><tr>{fcols}</tr></table>
      </div>"""

    return f"""
  <div class="section" style="background:linear-gradient(135deg, #151d30 0%, #1a2744 100%)">
    <div class="section-body" style="padding:20px">
      <table style="width:100%;border-collapse:collapse">
        <tr>
          <td style="width:64px;vertical-align:middle">{current_icon}</td>
          <td style="vertical-align:middle;padding-left:14px">
            <div style="font-size:28px;font-weight:700;color:#e2e8f0">{current_temp}°C</div>
            <div style="font-size:13px;color:#a0aec0">{current_desc} · Gefühlt {feels_like}°C</div>
            <div style="font-size:11px;color:#7a8ba8">{location} · Wind {current.get('wind', '?')} km/h · Luftfeuchtigkeit {current.get('humidity', '?')}%</div>
          </td>
        </tr>
      </table>
      {ai_html}
      {periods_html}
      {forecast_html}
    </div>
  </div>"""


def render_feed_section(feed_items: list[dict]) -> str:
    """Render RSS feed items as HTML, grouped by source feed."""
    if not feed_items:
        return ""

    # Group by source
    by_source: dict[str, list[dict]] = {}
    for item in feed_items:
        source = item.get("source") or "RSS"
        by_source.setdefault(source, []).append(item)

    sections = ""
    for source, items in by_source.items():
        rows = ""
        for item in items:
            rows += f"""
      <div class="feed-item">
        <a href="{item['link']}" class="feed-title">{item['title']}</a>
        {f'<div class="feed-source">{item["summary"]}</div>' if item.get("summary") else ""}
      </div>"""

        sections += f"""
  <div class="section">
    <div class="section-header">
      <h2>📰 {source}<span class="section-badge">{len(items)}</span></h2>
    </div>
    <div class="section-body">{rows}
    </div>
  </div>"""

    return sections


HTML_OUTPUT_INSTRUCTION = """

CRITICAL FORMATTING RULES:
1. Your output MUST be valid HTML, NOT Markdown. Use <h3>, <p>, <ul>, <li>, <table>, <tr>, <td>, <strong>, <a> tags.
2. Do NOT use # headings, * bullets, or **bold** markdown syntax.
3. Use inline styles compatible with email clients. Use colors that work on a dark background (#0f1729).
4. Text color: #d4dae4, headings: #e2e8f0, links: #5b9cf6, muted: #7a8ba8.

CRITICAL CONTENT RULES:
1. Provide SUBSTANTIVE content, not just summaries. Include the actual key points, arguments, insights, and information from each email.
2. Do NOT just say "discusses topic X" — explain WHAT is discussed, what the key takeaways are.
3. For newsletter content: reproduce the core message, key arguments, data points, and actionable insights.
4. For alerts/monitoring: include the FULL content of the alerts.
5. The reader should NOT need to open the original email to understand what it says.
6. For each mail you mention, include a link to the inbox using the provided "Inbox Link" URL as an <a> tag so the reader can open the original.
7. Do NOT include unsubscribe links in your output — they are handled separately below your summary.
8. EVENTS/DATES: If you find dates, deadlines, appointments or events in any email, add a "Termine & Fristen" section. For EACH event, include a Google Calendar link using this exact format:
   <a href="https://calendar.google.com/calendar/render?action=TEMPLATE&text=TITLE&dates=YYYYMMDD/YYYYMMDD">📅 Kalender</a>
   For timed events use: dates=YYYYMMDDTHHMMSSZ/YYYYMMDDTHHMMSSZ (UTC).
   For all-day events use: dates=YYYYMMDD/NEXT_DAY_YYYYMMDD.
   URL-encode the title (spaces as %20). Include ALL detected events, not just those with due_date set."""


async def generate_ai_summary(
    db: AsyncSession, mail_items: list[dict],
    custom_prompt: str | None = None, max_tokens: int = 4000,
) -> str | None:
    """Generate an AI summary of the digest items.

    If custom_prompt is set (from the policy), it's used as the system prompt.
    Otherwise falls back to the global digest prompt.
    """
    if not mail_items:
        return None

    try:
        provider = get_llm_provider()

        if custom_prompt:
            system_prompt = custom_prompt + HTML_OUTPUT_INSTRUCTION
            _, user_template = await get_prompt(db, "digest")
        else:
            system_prompt, user_template = await get_prompt(db, "digest")
            system_prompt += HTML_OUTPUT_INSTRUCTION

        # Build detailed items text with all available info
        items_text = f"Total emails: {len(mail_items)}\n"
        for i, item in enumerate(mail_items, 1):
            items_text += f"\n{'='*60}\n"
            items_text += f"EMAIL {i}/{len(mail_items)}\n"
            items_text += f"Category: {item['category']}\n"
            items_text += f"From: {item['from']}\n"
            items_text += f"Subject: {item['subject']}\n"
            items_text += f"Date: {item['date']}\n"
            items_text += f"Inbox Link: {INBOX_BASE_URL}/?msg={item['id']}\n"
            if item.get("action_required"):
                items_text += "⚠ ACTION REQUIRED\n"
            if item.get("priority", 0) >= 3:
                items_text += f"Priority: {item['priority']}/5\n"
            if item.get("summary"):
                items_text += f"AI Summary: {item['summary']}\n"
            if item.get("body_snippet"):
                items_text += f"--- Email Content ---\n{item['body_snippet']}\n--- End Content ---\n"
            # unsubscribe links are rendered separately, not by the LLM

        user_msg = user_template.format(items=items_text)

        result = await provider.chat_and_log(
            db, "digest",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
        )
        content = result.get("content", "")

        # Strip markdown code fences if LLM wraps in ```html
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return content
    except Exception as e:
        logger.error(f"AI summary generation failed: {e}")
        return None


DEFAULT_HEALTH_PROMPT = (
    "Du bist ein Gesundheitsberater. Analysiere die folgenden Garmin-Gesundheitsdaten "
    "und gib eine kurze, praktische Zusammenfassung auf Deutsch (3-5 Sätze). "
    "Erwähne Trends, Auffälligkeiten und Empfehlungen. Sei motivierend aber ehrlich."
)

# Chart IDs to human-readable labels and their required data types
HEALTH_CHART_CONFIG = {
    "body-battery": {"label": "Body Battery", "types": ["body_battery"]},
    "heart-rate": {"label": "Heart Rate", "types": ["heart_rate"]},
    "sleep": {"label": "Sleep", "types": ["sleep"]},
    "steps": {"label": "Steps", "types": ["stats"]},
    "stress": {"label": "Stress", "types": ["stress"]},
    "sleep-stress": {"label": "Sleep Stress", "types": ["stress", "sleep"]},
    "hrv": {"label": "HRV", "types": ["hrv"]},
    "spo2": {"label": "SpO2", "types": ["spo2"]},
    "weight": {"label": "Weight", "types": ["weight"]},
    "floors": {"label": "Floors", "types": ["stats"]},
    "training-load": {"label": "Training Load", "types": ["activities", "maxmet"]},
    "fitness-age": {"label": "Fitness Age", "types": ["fitnessage"]},
    "vo2max": {"label": "VO2max", "types": ["maxmet"]},
    "intensity": {"label": "Intensity Minutes", "types": ["intensity_minutes"]},
    "activities": {"label": "Activities", "types": ["activities"]},
}

# Data types available for LLM health summary
HEALTH_DATA_TYPE_LABELS = {
    "stats": "Daily Stats (Steps, Floors, Calories)",
    "sleep": "Sleep (Duration, Stages)",
    "heart_rate": "Heart Rate (Resting, Max)",
    "body_battery": "Body Battery",
    "stress": "Stress Levels",
    "hrv": "HRV (Heart Rate Variability)",
    "spo2": "SpO2 (Blood Oxygen)",
    "weight": "Weight",
    "activities": "Activities (Training Load)",
    "intensity_minutes": "Intensity Minutes",
    "fitnessage": "Fitness Age",
    "maxmet": "VO2max",
}


async def collect_health_data(
    db: AsyncSession, data_types: list[str], days: int = 7
) -> dict[str, list[dict]]:
    """Collect Garmin health snapshots for selected data types."""
    from datetime import date as date_type
    end = date_type.today()
    start = end - timedelta(days=days - 1)

    result = await db.execute(
        select(GarminSnapshot).where(
            GarminSnapshot.data_type.in_(data_types),
            GarminSnapshot.date >= start,
            GarminSnapshot.date <= end,
        ).order_by(GarminSnapshot.date.asc())
    )
    snapshots = result.scalars().all()

    grouped: dict[str, list[dict]] = {}
    for s in snapshots:
        if s.data_type not in grouped:
            grouped[s.data_type] = []
        grouped[s.data_type].append({"date": s.date.isoformat(), "data": s.data})
    return grouped


def _extract_health_text(health_data: dict[str, list[dict]]) -> str:
    """Convert health data into readable text for LLM."""
    lines = []
    for dtype, snapshots in health_data.items():
        lines.append(f"\n=== {HEALTH_DATA_TYPE_LABELS.get(dtype, dtype)} ===")
        for s in snapshots[-7:]:  # Last 7 entries max
            d = s["data"] or {}
            date_str = s["date"]
            if dtype == "stats":
                lines.append(f"  {date_str}: Steps={d.get('totalSteps',0)}, Floors={d.get('floorsAscended',0)}, Calories={d.get('totalKilocalories',0)}")
            elif dtype == "sleep":
                dto = d.get("dailySleepDTO", d)
                deep = round((dto.get("deepSleepSeconds", 0)) / 3600, 1)
                light = round((dto.get("lightSleepSeconds", 0)) / 3600, 1)
                rem = round((dto.get("remSleepSeconds", 0)) / 3600, 1)
                total = round(deep + light + rem, 1)
                lines.append(f"  {date_str}: Total={total}h (Deep={deep}h, Light={light}h, REM={rem}h)")
            elif dtype == "heart_rate":
                lines.append(f"  {date_str}: Resting={d.get('restingHeartRate','-')}, Max={d.get('maxHeartRate','-')}")
            elif dtype == "body_battery":
                bb = d if not isinstance(d, list) else (d[0] if d else {})
                lines.append(f"  {date_str}: Charged={bb.get('charged','-')}, Drained={bb.get('drained','-')}")
            elif dtype == "stress":
                lines.append(f"  {date_str}: Avg={d.get('avgStressLevel','-')}, Max={d.get('maxStressLevel','-')}")
            elif dtype == "hrv":
                summary = d.get("hrvSummary", {})
                baseline = summary.get("baseline", {})
                lines.append(f"  {date_str}: LastNightAvg={summary.get('lastNightAvg','-')}, WeeklyAvg={summary.get('weeklyAvg','-')}, Status={summary.get('status','-')}, Baseline={baseline.get('balancedLow','-')}-{baseline.get('balancedUpper','-')}")
            elif dtype == "spo2":
                lines.append(f"  {date_str}: Avg={d.get('averageSpO2', d.get('latestSpO2','-'))}%")
            elif dtype == "weight":
                wl = d.get("dateWeightList", [])
                w = (wl[0].get("weight", 0) if wl else 0)
                if w > 1000:
                    w = w / 1000
                lines.append(f"  {date_str}: {round(w, 1)} kg")
            elif dtype == "activities":
                acts = d if isinstance(d, list) else d.get("ActivitiesForDay", {}).get("payload", [])
                for a in (acts if isinstance(acts, list) else []):
                    atype = a.get("activityType", {})
                    name = atype.get("typeKey", atype) if isinstance(atype, dict) else atype
                    lines.append(f"  {date_str}: {name}, Duration={round(a.get('duration',0)/60)}min, Load={a.get('activityTrainingLoad',0)}")
            elif dtype == "intensity_minutes":
                mod = d.get("moderateMinutes", 0)
                vig = d.get("vigorousMinutes", 0)
                lines.append(f"  {date_str}: Moderate={mod}min, Vigorous={vig}min (x2={vig*2}min), Total={d.get('endDayMinutes',0)}min")
            elif dtype == "fitnessage":
                lines.append(f"  {date_str}: FitnessAge={d.get('fitnessAge','-')}, ChronAge={d.get('chronologicalAge','-')}")
            elif dtype == "maxmet":
                entries = d if isinstance(d, list) else [d]
                for e in entries:
                    if not e:
                        continue
                    run_v = (e.get("generic", {}) or {}).get("vo2MaxPreciseValue", "-")
                    cyc_v = (e.get("cycling", {}) or {}).get("vo2MaxPreciseValue", "-")
                    lines.append(f"  {date_str}: Running={run_v}, Cycling={cyc_v}")
            else:
                lines.append(f"  {date_str}: {str(d)[:200]}")
    return "\n".join(lines)


def _fmt_date_short(date_str: str) -> str:
    """Format ISO date to DD.MM."""
    parts = date_str.split("-")
    return f"{parts[2]}.{parts[1]}" if len(parts) == 3 else date_str


def _bar_html(pct: float, color: str = "#3b82f6", label: str = "") -> str:
    """Render an inline horizontal bar for email."""
    pct = max(0, min(100, pct))
    return (
        f'<td style="padding:3px 0;width:60%;">'
        f'<div style="background:#1a2540;border-radius:4px;height:18px;position:relative;">'
        f'<div style="background:{color};border-radius:4px;height:18px;width:{pct}%;min-width:2px;"></div>'
        f'</div></td>'
        f'<td style="padding:3px 6px;color:#d4dae4;font-size:11px;white-space:nowrap;">{label}</td>'
    )


def _stacked_bar_html(segments: list[tuple[float, str]], labels: str = "") -> str:
    """Render stacked bar segments."""
    bar_parts = ""
    for pct, color in segments:
        if pct > 0:
            bar_parts += f'<div style="background:{color};height:18px;width:{pct}%;display:inline-block;"></div>'
    return (
        f'<td style="padding:3px 0;width:55%;">'
        f'<div style="background:#1a2540;border-radius:4px;height:18px;overflow:hidden;font-size:0;line-height:0;">{bar_parts}</div></td>'
        f'<td style="padding:3px 6px;color:#d4dae4;font-size:11px;white-space:nowrap;">{labels}</td>'
    )


def _render_health_chart_html(chart_id: str, health_data: dict[str, list[dict]]) -> str:
    """Render a single health chart as visual HTML bars for email digest."""
    import html as html_mod
    config = HEALTH_CHART_CONFIG.get(chart_id)
    if not config:
        return ""

    label = config["label"]
    row_html = ""

    if chart_id == "body-battery":
        for s in health_data.get("body_battery", []):
            d = s["data"]
            if isinstance(d, list):
                d = d[0] if d else {}
            vals = d.get("bodyBatteryValuesArray", [])
            mx = 0
            for v in (vals or []):
                val = v[1] if isinstance(v, list) else v
                if isinstance(val, (int, float)) and val > mx:
                    mx = val
            if mx == 0:
                mx = d.get("charged", 0) or 0
            color = "#22c55e" if mx >= 60 else "#f97316" if mx >= 30 else "#ef4444"
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(mx, color, f"{mx}%")}</tr>'

    elif chart_id == "heart-rate":
        entries = health_data.get("heart_rate", [])
        max_hr = max((s["data"].get("maxHeartRate", 0) or 0) for s in entries) if entries else 200
        max_hr = max(max_hr, 100)
        for s in entries:
            d = s["data"] or {}
            resting = d.get("restingHeartRate", 0) or 0
            mx = d.get("maxHeartRate", 0) or 0
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>'
            row_html += _stacked_bar_html([
                (resting / max_hr * 100, "#ef4444"),
                ((mx - resting) / max_hr * 100, "#f9731640"),
            ], f"Rest {resting} / Max {mx}")
            row_html += '</tr>'

    elif chart_id == "sleep":
        for s in health_data.get("sleep", []):
            d = s["data"] or {}
            dto = d.get("dailySleepDTO", d)
            deep = dto.get("deepSleepSeconds", 0) / 3600
            light = dto.get("lightSleepSeconds", 0) / 3600
            rem = dto.get("remSleepSeconds", 0) / 3600
            awake = dto.get("awakeSleepSeconds", 0) / 3600
            total = deep + light + rem + awake
            scale = 10  # 10h = 100%
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>'
            row_html += _stacked_bar_html([
                (deep / scale * 100, "#6366f1"),
                (light / scale * 100, "#3b82f6"),
                (rem / scale * 100, "#a855f7"),
                (awake / scale * 100, "#f97316"),
            ], f"{round(total, 1)}h")
            row_html += '</tr>'

    elif chart_id == "steps":
        entries = health_data.get("stats", [])
        max_steps = max((s["data"].get("totalSteps", 0) or 0) for s in entries) if entries else 10000
        max_steps = max(max_steps, 1000)
        for s in entries:
            d = s["data"] or {}
            steps = d.get("totalSteps", 0) or 0
            goal = d.get("dailyStepGoal", 10000) or 10000
            color = "#22c55e" if steps >= goal else "#3b82f6"
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(steps / max_steps * 100, color, f"{steps:,}")}</tr>'

    elif chart_id == "stress":
        for s in health_data.get("stress", []):
            d = s["data"] or {}
            avg = d.get("avgStressLevel", 0) or 0
            color = "#22c55e" if avg <= 25 else "#f97316" if avg <= 50 else "#ef4444"
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(avg, color, str(avg))}</tr>'

    elif chart_id == "sleep-stress":
        sleep_times = {}
        for s in health_data.get("sleep", []):
            dto = (s["data"] or {}).get("dailySleepDTO", s["data"] or {})
            start, end = dto.get("sleepStartTimestampGMT"), dto.get("sleepEndTimestampGMT")
            if start and end:
                sleep_times[s["date"]] = (start, end)
        for s in health_data.get("stress", []):
            d = s["data"] or {}
            window = sleep_times.get(s["date"])
            vals = d.get("stressValuesArray", [])
            if window and vals:
                sv = [v[1] for v in vals if v[0] >= window[0] and v[0] <= window[1] and v[1] > 0]
                if sv:
                    avg = round(sum(sv) / len(sv))
                    color = "#a855f7" if avg <= 25 else "#f97316" if avg <= 40 else "#ef4444"
                    row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(avg, color, str(avg))}</tr>'

    elif chart_id == "hrv":
        entries = health_data.get("hrv", [])
        all_vals = []
        for s in entries:
            summary = (s["data"] or {}).get("hrvSummary", {})
            v = summary.get("lastNightAvg", 0) or 0
            bl = summary.get("baseline", {})
            if bl.get("balancedUpper"):
                all_vals.append(bl["balancedUpper"])
            all_vals.append(v)
        max_val = max(all_vals) * 1.2 if all_vals else 80
        for s in entries:
            summary = (s["data"] or {}).get("hrvSummary", {})
            v = summary.get("lastNightAvg", 0) or 0
            status = summary.get("status", "")
            bl = summary.get("baseline", {})
            color = "#22c55e" if status == "BALANCED" else "#f97316" if status == "UNBALANCED" else "#ef4444"
            bl_text = f" [{bl.get('balancedLow', '')}-{bl.get('balancedUpper', '')}]" if bl.get("balancedLow") else ""
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(v / max_val * 100, color, f"{v}ms{bl_text}")}</tr>'

    elif chart_id == "spo2":
        for s in health_data.get("spo2", []):
            d = s["data"] or {}
            val = d.get("averageSpO2", d.get("latestSpO2", 0)) or 0
            if val > 0:
                color = "#22c55e" if val >= 95 else "#f97316" if val >= 90 else "#ef4444"
                row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(val, color, f"{val}%")}</tr>'

    elif chart_id == "weight":
        entries = health_data.get("weight", [])
        weights = []
        for s in entries:
            d = s["data"] or {}
            wl = d.get("dateWeightList", [])
            w = (wl[0].get("weight", 0) if wl else d.get("totalAverage", {}).get("weight", 0)) or 0
            if w > 1000:
                w = w / 1000
            weights.append((s["date"], round(w, 1)))
        vals = [w for _, w in weights if w > 0]
        if vals:
            mn, mx = min(vals), max(vals)
            rng = max(mx - mn, 1)
            for dt, w in weights:
                if w > 0:
                    pct = (w - mn + rng * 0.1) / (rng * 1.2) * 100
                    row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(dt)}</td>{_bar_html(pct, "#9ca3af", f"{w}kg")}</tr>'

    elif chart_id == "floors":
        entries = health_data.get("stats", [])
        max_fl = max((s["data"].get("floorsAscended", 0) or 0) for s in entries) if entries else 10
        max_fl = max(max_fl, 1)
        for s in entries:
            d = s["data"] or {}
            fl = d.get("floorsAscended", 0) or 0
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>{_bar_html(fl / max_fl * 100, "#14b8a6", str(fl))}</tr>'

    elif chart_id == "intensity":
        for s in health_data.get("intensity_minutes", []):
            d = s["data"] or {}
            mod = d.get("moderateMinutes", 0) or 0
            vig = (d.get("vigorousMinutes", 0) or 0) * 2
            total = mod + vig
            goal = d.get("weekGoal", 150) or 150
            row_html += f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>'
            row_html += _stacked_bar_html([
                (mod / goal * 100, "#eab308"),
                (vig / goal * 100, "#ef4444"),
            ], f"{total}/{d.get('endDayMinutes', total)}min")
            row_html += '</tr>'

    elif chart_id == "activities":
        for s in health_data.get("activities", []):
            d = s["data"] or {}
            acts = d if isinstance(d, list) else d.get("ActivitiesForDay", {}).get("payload", [])
            for a in (acts if isinstance(acts, list) else []):
                atype = a.get("activityType", {})
                name = (atype.get("typeKey", atype) if isinstance(atype, dict) else str(atype))[:20]
                dur = round(a.get("duration", 0) / 60)
                dist = a.get("distance", 0) or 0
                dist_str = f"{round(dist/1000,1)}km" if dist >= 1000 else f"{round(dist)}m"
                hr = a.get("averageHR", a.get("averageHeartRate", "-"))
                row_html += (
                    f'<tr><td style="padding:3px 6px;color:#7a8ba8;font-size:11px;white-space:nowrap;width:50px;">{_fmt_date_short(s["date"])}</td>'
                    f'<td colspan="2" style="padding:3px 6px;color:#d4dae4;font-size:11px;">'
                    f'{html_mod.escape(name)} · {dur}min · {dist_str} · HR {hr}</td></tr>'
                )

    elif chart_id == "fitness-age":
        entries = health_data.get("fitnessage", [])
        if entries:
            latest = entries[-1]["data"] or {}
            fa = latest.get("fitnessAge", 0)
            ca = latest.get("chronologicalAge", 0)
            diff = ca - fa
            color = "#22c55e" if diff > 0 else "#f97316" if diff == 0 else "#ef4444"
            row_html = (
                f'<tr><td colspan="3" style="padding:6px;text-align:center;">'
                f'<span style="font-size:28px;font-weight:700;color:{color};">{fa}</span>'
                f'<span style="font-size:12px;color:#7a8ba8;margin-left:6px;">vs {ca} ({("+" if diff < 0 else "-")}{abs(diff)} Jahre)</span>'
                f'</td></tr>'
            )

    elif chart_id == "vo2max":
        entries = health_data.get("maxmet", [])
        if entries:
            latest_data = entries[-1]["data"]
            latest = latest_data[0] if isinstance(latest_data, list) else latest_data
            if latest:
                rv = (latest.get("generic", {}) or {}).get("vo2MaxPreciseValue", 0) or 0
                cv = (latest.get("cycling", {}) or {}).get("vo2MaxPreciseValue", 0) or 0
                parts = []
                if rv:
                    parts.append(f'<span style="color:#22c55e;font-size:20px;font-weight:700;">{rv}</span><span style="color:#7a8ba8;font-size:11px;margin:0 8px;">Running</span>')
                if cv:
                    parts.append(f'<span style="color:#3b82f6;font-size:20px;font-weight:700;">{cv}</span><span style="color:#7a8ba8;font-size:11px;margin:0 8px;">Cycling</span>')
                row_html = f'<tr><td colspan="3" style="padding:6px;text-align:center;">{"".join(parts)}</td></tr>'

    elif chart_id == "training-load":
        # Calculate VO2max-based optimal zone (same logic as frontend)
        vo2max = 50
        for s in health_data.get("maxmet", []):
            entries_list = s["data"] if isinstance(s["data"], list) else [s["data"]]
            for e in entries_list:
                if not e:
                    continue
                for src in [e.get("generic"), e.get("cycling")]:
                    if src:
                        v = src.get("vo2MaxPreciseValue") or src.get("vo2MaxValue") or 0
                        if v > vo2max:
                            vo2max = round(v)
        opt_center = vo2max * 5
        opt_low = round(opt_center * 0.7)
        opt_high = round(opt_center * 1.3)

        # Calculate EWMA-based acute load
        activity_entries = health_data.get("activities", [])
        daily_loads: dict[str, float] = {}
        for s in activity_entries:
            d = s["data"] or {}
            acts = d if isinstance(d, list) else d.get("ActivitiesForDay", {}).get("payload", [])
            daily_loads[s["date"]] = sum(a.get("activityTrainingLoad", 0) for a in (acts if isinstance(acts, list) else []))

        # Fill gaps and compute EWMA
        if daily_loads:
            all_dates = sorted(daily_loads.keys())
            from datetime import date as date_cls
            start_d = date_cls.fromisoformat(all_dates[0])
            end_d = date_cls.fromisoformat(all_dates[-1])
            alpha7 = 2 / (7 + 1)
            ewma7 = 0.0
            d = start_d
            while d <= end_d:
                iso = d.isoformat()
                v = daily_loads.get(iso, 0)
                ewma7 = alpha7 * v + (1 - alpha7) * ewma7
                d += timedelta(days=1)
            acute = round(ewma7 * 7.5)
        else:
            acute = 0

        # Render as single zone bar
        bar_max = max(opt_high * 1.3, acute * 1.15, opt_high + 50)
        acute_pct = acute / bar_max * 100
        zone_left = opt_low / bar_max * 100
        zone_width = (opt_high - opt_low) / bar_max * 100

        if acute < opt_low:
            color = "#3b82f6"
            status = "Low"
        elif acute <= opt_high:
            color = "#22c55e"
            status = "Optimal"
        elif acute <= opt_high * 1.3:
            color = "#f97316"
            status = "High"
        else:
            color = "#ef4444"
            status = "Very High"

        row_html = f"""
        <tr><td colspan="3" style="padding:8px 6px;">
          <div style="position:relative;background:#1a2540;border-radius:6px;height:28px;overflow:visible;">
            <div style="position:absolute;left:{zone_left}%;width:{zone_width}%;top:0;height:28px;background:#22c55e20;border-left:2px solid #22c55e40;border-right:2px solid #22c55e40;border-radius:4px;"></div>
            <div style="position:absolute;left:0;width:{acute_pct}%;top:4px;height:20px;background:{color};border-radius:4px;min-width:4px;"></div>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:4px;">
            <span style="font-size:11px;color:#7a8ba8;">0</span>
            <span style="font-size:11px;color:#22c55e;">{opt_low}–{opt_high}</span>
            <span style="font-size:11px;color:#7a8ba8;">{round(bar_max)}</span>
          </div>
          <div style="text-align:center;margin-top:2px;">
            <span style="font-size:18px;font-weight:700;color:{color};">{acute}</span>
            <span style="font-size:12px;color:#7a8ba8;margin-left:6px;">{status}</span>
          </div>
        </td></tr>"""

    if not row_html:
        return ""

    return f"""
    <div style="margin-bottom:14px;">
      <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:6px;padding-left:6px;">{html_mod.escape(label)}</div>
      <table style="width:100%;border-collapse:collapse;">{row_html}</table>
    </div>"""


def render_health_section(health_data: dict[str, list[dict]], chart_ids: list[str], ai_summary: str | None = None) -> str:
    """Render the full health section for digest email."""
    if not health_data:
        return ""

    charts_html = ""
    for cid in chart_ids:
        charts_html += _render_health_chart_html(cid, health_data)

    summary_html = ""
    if ai_summary:
        summary_html = f"""
      <div style="background:#1a2540;border-left:3px solid #22c55e;padding:12px 16px;margin:0 0 12px 0;border-radius:0 8px 8px 0;font-size:13px;line-height:1.6;color:#a0aec0;">
        {_safe_llm_html(ai_summary)}
      </div>"""

    return f"""
  <div class="section">
    <div class="section-header" style="background:linear-gradient(135deg,#1a2744,#1a3a2a);"><h2>💚 Health</h2></div>
    <div class="section-body">
      {summary_html}
      {charts_html}
    </div>
  </div>"""


async def generate_health_summary(
    db: AsyncSession, health_data: dict[str, list[dict]], custom_prompt: str | None = None
) -> str | None:
    """Generate a health summary via LLM."""
    try:
        provider = get_llm_provider()
        health_text = _extract_health_text(health_data)
        if not health_text.strip():
            return None

        system_prompt = custom_prompt or DEFAULT_HEALTH_PROMPT
        result = await provider.chat_and_log(
            db, "health_summary",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": health_text},
            ],
            max_tokens=500,
        )
        return result.get("content", "").strip()
    except Exception as e:
        logger.error(f"Health LLM summary failed: {e}")
        return None


async def compose_digest(
    db: AsyncSession, policy: DigestPolicy, override_since: datetime | None = None
) -> DigestRun:
    """Compose and optionally send a digest based on a policy.

    If override_since is set (e.g. from manual "Run Now"), it overrides
    the default "since last successful run" calculation.
    """
    now = datetime.now(timezone.utc)
    run = DigestRun(
        policy_id=policy.id,
        status="running",
        started_at=now,
        item_count=0,
    )
    db.add(run)
    await db.flush()

    try:
        if override_since is not None:
            since = override_since
        else:
            if policy.since_last_any_digest:
                # Cross-policy: find last successful run of ANY policy
                last_run_result = await db.execute(
                    select(DigestRun.completed_at)
                    .where(
                        DigestRun.status == "completed",
                        DigestRun.id != run.id,
                    )
                    .order_by(desc(DigestRun.completed_at))
                    .limit(1)
                )
            else:
                # Default: find last successful run of THIS policy
                last_run_result = await db.execute(
                    select(DigestRun.completed_at)
                    .where(
                        DigestRun.policy_id == policy.id,
                        DigestRun.status == "completed",
                        DigestRun.id != run.id,
                    )
                    .order_by(desc(DigestRun.completed_at))
                    .limit(1)
                )
            last_completed = last_run_result.scalar_one_or_none()
            since = last_completed if last_completed else now - timedelta(hours=24)

        mail_items = await collect_mail_items(db, policy, since)
        weather_data = None
        weather_ai_summary = None
        if policy.include_weather:
            weather_data = await collect_weather_data(db)
            if weather_data and weather_data.get("data") and isinstance(weather_data["data"], dict):
                weather_ai_summary = await generate_weather_summary(db, weather_data["data"], policy.weather_prompt)
        feed_items = []
        if policy.include_feeds:
            feed_items = await collect_feed_items(db, since, limit=200)

        # Collect health data
        health_data = {}
        health_ai_summary = None
        if policy.include_health:
            chart_ids = policy.health_charts or []
            llm_data_types = policy.health_data_types or []
            # Collect data types needed for charts + LLM
            needed_types = set(llm_data_types)
            for cid in chart_ids:
                cfg = HEALTH_CHART_CONFIG.get(cid)
                if cfg:
                    needed_types.update(cfg["types"])
            if needed_types:
                health_data = await collect_health_data(db, list(needed_types), days=policy.health_days or 7)
            # Generate LLM health summary if data types selected for LLM
            if llm_data_types and health_data:
                llm_health_data = {k: v for k, v in health_data.items() if k in llm_data_types}
                if llm_health_data:
                    health_ai_summary = await generate_health_summary(db, llm_health_data, policy.health_prompt)

        total_items = len(mail_items) + len(feed_items) + (1 if weather_data else 0) + (1 if health_data else 0)
        run.item_count = total_items

        # Load display thresholds
        detail_threshold, compact_threshold = await get_digest_thresholds(db)

        # Generate AI summary (use policy-specific prompt if set)
        ai_summary = await generate_ai_summary(
            db, mail_items, policy.digest_prompt, policy.max_tokens or 4000
        )

        # Build sections
        order = 0

        if weather_data:
            db.add(DigestSection(
                run_id=run.id, section_type="weather", title="Wetter",
                content=render_weather_section(weather_data, weather_ai_summary), order=order,
            ))
            order += 1

        if ai_summary:
            db.add(DigestSection(
                run_id=run.id, section_type="ai_summary", title="AI Overview",
                content=ai_summary, order=order,
            ))
            order += 1

        if mail_items:
            db.add(DigestSection(
                run_id=run.id, section_type="mail", title="Email Summary",
                content=render_mail_section(mail_items, detail_threshold, compact_threshold), order=order,
                metadata_json={"count": len(mail_items)},
            ))
            order += 1

        if feed_items:
            db.add(DigestSection(
                run_id=run.id, section_type="feed", title="RSS Feeds",
                content=render_feed_section(feed_items), order=order,
                metadata_json={"count": len(feed_items)},
            ))
            order += 1

        if health_data and policy.health_charts:
            db.add(DigestSection(
                run_id=run.id, section_type="health", title="Health",
                content=render_health_section(health_data, policy.health_charts, health_ai_summary), order=order,
            ))
            order += 1

        # Build section blocks
        section_blocks = {
            "weather": render_weather_section(weather_data, weather_ai_summary) if weather_data else "",
            "ai_overview": "",
            "health": render_health_section(health_data, policy.health_charts or [], health_ai_summary) if health_data and policy.health_charts else "",
            "mail": render_mail_section(mail_items, detail_threshold, compact_threshold),
            "feeds": render_feed_section(feed_items) if feed_items else "",
            "unsubscribe": render_unsubscribe_section(mail_items),
        }
        if ai_summary:
            section_blocks["ai_overview"] = f"""
  <div class="section">
    <div class="section-header"><h2>✨ AI Overview</h2></div>
    <div class="section-body">
      <div class="ai-summary">{_safe_llm_html(ai_summary)}</div>
    </div>
  </div>"""

        # Determine section order from policy
        import json as _json
        default_order = ["weather", "health", "ai_overview", "mail", "feeds", "unsubscribe"]
        try:
            order_list = _json.loads(policy.section_order) if policy.section_order else default_order
        except (ValueError, TypeError):
            order_list = default_order

        # All sections go through the configured order
        ordered_sections = ""
        for key in order_list:
            block = section_blocks.get(key, "")
            if block:
                ordered_sections += block

        run.html_content = DIGEST_HTML_TEMPLATE.format(
            date=now.strftime("%A, %B %d, %Y"),
            item_count=total_items,
            weather_section="",
            ai_summary_section="",
            sections=ordered_sections,
        )

        # Send via email if target configured
        if policy.target_email:
            await send_digest_email(db, policy, run.html_content, now)

        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        logger.info(f"Digest completed for policy '{policy.name}': {total_items} items")

    except Exception as e:
        run.status = "failed"
        run.error = str(e)[:1000]
        run.completed_at = datetime.now(timezone.utc)
        logger.error(f"Digest failed for policy '{policy.name}': {e}")

    await db.flush()
    return run


async def send_digest_email(
    db: AsyncSession, policy: DigestPolicy, html: str, now: datetime
):
    """Send digest HTML via SMTP using the first available mail account."""
    result = await db.execute(
        select(MailAccount).where(MailAccount.enabled == True).limit(1)
    )
    account = result.scalars().first()
    if not account:
        raise ValueError("No mail account configured for sending digest")
    if not account.smtp_host:
        raise ValueError(f"No SMTP config on account {account.email}")

    password = decrypt_value(account.password_encrypted)

    await send_email(
        host=account.smtp_host,
        port=account.smtp_port or 587,
        username=account.username,
        password=password,
        use_tls=account.smtp_use_tls if account.smtp_use_tls is not None else True,
        from_addr=account.email,
        to_addr=policy.target_email,
        subject=f"You Digest — {now.strftime('%d.%m.%Y')}",
        body_text=f"Your daily digest with {policy.name}. View the HTML version for full content.",
        body_html=html,
    )
    logger.info(f"Digest email sent to {policy.target_email}")

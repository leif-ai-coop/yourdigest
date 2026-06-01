import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailMessage
from app.models.classification import MailClassification
from app.llm.provider import get_llm_provider
from app.llm.sanitizer import sanitize_email_for_llm
from app.llm.prompt_registry import get_prompt

logger = logging.getLogger(__name__)


def _parse_categories(data: dict) -> list[tuple[str, float]]:
    """Normalize the LLM response into an ordered list of (category, confidence).

    Accepts the new ``categories`` array (list of dicts or strings) and falls
    back to the legacy single ``category`` field. Dedups case-insensitively
    while preserving the (relevance) order, dropping empty names.
    """
    raw = data.get("categories")
    pairs: list[tuple[str, float]] = []
    top_conf = float(data.get("confidence", 0.0) or 0.0)
    if isinstance(raw, list) and raw:
        for entry in raw:
            if isinstance(entry, dict):
                cat = (entry.get("category") or "").strip()
                conf = entry.get("confidence", top_conf)
            elif isinstance(entry, str):
                cat, conf = entry.strip(), top_conf
            else:
                continue
            if cat:
                try:
                    pairs.append((cat, float(conf)))
                except (TypeError, ValueError):
                    pairs.append((cat, top_conf))
    if not pairs:
        cat = (data.get("category") or "unknown").strip() or "unknown"
        pairs.append((cat, top_conf))

    seen: set[str] = set()
    deduped: list[tuple[str, float]] = []
    for cat, conf in pairs:
        key = cat.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((cat, conf))
    return deduped


async def classify_with_llm(db: AsyncSession, message: MailMessage) -> list[MailClassification]:
    """Classify an email message using LLM. Returns one row per category."""
    provider = get_llm_provider()
    system_prompt, user_template = await get_prompt(db, "classify")

    sanitized = sanitize_email_for_llm(message.subject, message.body_text or message.body_html, message.from_address)

    user_content = user_template.format(**sanitized)

    result = await provider.chat_and_log(
        db=db,
        task_type="classify",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(result["content"])
    except (json.JSONDecodeError, TypeError):
        data = {"category": "unknown", "confidence": 0.0, "priority": 0, "summary": result.get("content", "")}

    # Extract tracking codes from LLM response and save on message
    raw_tracking = data.get("tracking_codes", [])
    if raw_tracking and isinstance(raw_tracking, list):
        from app.services.tracking_extractor import _build_tracking_url
        tracking = []
        for tc in raw_tracking:
            if isinstance(tc, dict) and tc.get("code"):
                carrier = tc.get("carrier", "Unknown")
                code = tc["code"]
                tracking.append({"carrier": carrier, "code": code, "url": _build_tracking_url(carrier, code)})
        if tracking:
            message.tracking_codes = tracking
            logger.info(f"LLM found {len(tracking)} tracking codes in message {message.id}")

    # A mail can have multiple categories -> one row per category. Replace all
    # existing rows for this message (re-classify is idempotent). Mail-level
    # fields (priority, summary, ...) are duplicated onto each row so any
    # consumer reading a single row gets sensible data.
    from sqlalchemy import delete
    categories = _parse_categories(data)
    await db.execute(
        delete(MailClassification).where(MailClassification.message_id == message.id)
    )

    shared = dict(
        priority=data.get("priority", 0),
        summary=data.get("summary"),
        action_required=data.get("action_required", False),
        due_date=data.get("due_date"),
        tags=data.get("tags"),
        classified_by="llm",
        llm_model=result.get("model"),
        raw_llm_response=result.get("content"),
    )
    classifications = []
    for category, confidence in categories:
        obj = MailClassification(
            message_id=message.id,
            category=category,
            confidence=confidence,
            **shared,
        )
        db.add(obj)
        classifications.append(obj)
    await db.flush()
    for obj in classifications:
        await db.refresh(obj)
    return classifications

import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailMessage
from app.models.classification import MailClassification
from app.llm.provider import get_llm_provider
from app.llm.sanitizer import sanitize_email_for_llm
from app.llm.prompt_registry import get_prompt

logger = logging.getLogger(__name__)


async def classify_with_llm(db: AsyncSession, message: MailMessage) -> MailClassification:
    """Classify an email message using LLM."""
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

    classification = MailClassification(
        message_id=message.id,
        category=data.get("category", "unknown"),
        confidence=data.get("confidence", 0.0),
        priority=data.get("priority", 0),
        summary=data.get("summary"),
        action_required=data.get("action_required", False),
        due_date=data.get("due_date"),
        tags=data.get("tags"),
        classified_by="llm",
        llm_model=result.get("model"),
        raw_llm_response=result.get("content"),
    )
    db.add(classification)
    await db.flush()
    await db.refresh(classification)
    return classification

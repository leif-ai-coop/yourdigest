import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailMessage
from app.llm.provider import get_llm_provider
from app.llm.sanitizer import sanitize_email_for_llm
from app.llm.prompt_registry import get_prompt
from app.exceptions import NotFoundError

logger = logging.getLogger(__name__)


async def generate_draft_reply(
    db: AsyncSession,
    message_id: uuid.UUID,
    instructions: str | None = None,
    tone: str = "professional",
) -> dict:
    """Generate a draft reply for an email message."""
    message = await db.get(MailMessage, message_id)
    if not message:
        raise NotFoundError("Message not found")

    provider = get_llm_provider()
    system_prompt, user_template = await get_prompt(db, "draft_reply")

    system_prompt = system_prompt.format(
        tone=tone,
        instructions=instructions or "No special instructions",
    )

    sanitized = sanitize_email_for_llm(message.subject, message.body_text or message.body_html, message.from_address)
    user_content = user_template.format(**sanitized)

    result = await provider.chat_and_log(
        db=db,
        task_type="draft_reply",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )

    return {
        "draft": result.get("content", ""),
        "model": result.get("model", ""),
        "tokens_used": result.get("total_tokens", 0),
    }

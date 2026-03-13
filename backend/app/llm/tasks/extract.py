import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailMessage
from app.llm.provider import get_llm_provider
from app.llm.sanitizer import sanitize_email_for_llm
from app.llm.prompt_registry import get_prompt

logger = logging.getLogger(__name__)


async def extract_info(db: AsyncSession, message: MailMessage) -> dict:
    """Extract structured information from an email."""
    provider = get_llm_provider()
    system_prompt, user_template = await get_prompt(db, "extract")

    sanitized = sanitize_email_for_llm(message.subject, message.body_text or message.body_html, message.from_address)
    user_content = user_template.format(**sanitized)

    result = await provider.chat_and_log(
        db=db,
        task_type="extract",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )

    try:
        return json.loads(result["content"])
    except (json.JSONDecodeError, TypeError):
        return {"raw": result.get("content", "")}

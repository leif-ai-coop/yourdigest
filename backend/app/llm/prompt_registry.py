import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LlmPromptVersion

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = {
    "important": "Personal emails, urgent business, requires action",
    "newsletter": "Newsletters, subscriptions, regular updates",
    "notification": "Automated notifications, alerts, system messages",
    "spam": "Unwanted, promotional, suspicious emails",
    "social": "Social media notifications, community updates",
    "finance": "Banking, invoices, payments, receipts",
    "shipping": "Order confirmations, shipping updates, delivery notices",
}


def build_classify_prompt(categories: dict[str, str] | None = None) -> str:
    """Build classification system prompt from category definitions."""
    cats = categories or DEFAULT_CATEGORIES
    cat_lines = "\n".join(f"- {k}: {v}" for k, v in cats.items())
    return f"""You are an email classification assistant. Classify the given email into one of these categories:
{cat_lines}

Respond in JSON format with these fields:
- category: one of the categories above
- confidence: float 0-1
- priority: int 0-5 (5 = highest)
- summary: brief 1-2 sentence summary
- action_required: boolean
- due_date: ISO date string if applicable, null otherwise
- tags: list of relevant tags
- tracking_codes: array of package tracking codes found in the email. Each entry: {{"carrier": "DHL/UPS/DPD/Hermes/GLS/FedEx/Amazon/other", "code": "the tracking number"}}. Look for tracking numbers in URLs (e.g. ?piececode=..., ?tracknum=...), in the email text, and in shipping notifications. Return empty array [] if no tracking codes found."""


DEFAULT_PROMPTS = {
    "classify": {
        "system": build_classify_prompt(),
        "user": "Classify this email:\n\nFrom: {from}\nSubject: {subject}\n\nBody:\n{body}",
    },
    "extract": {
        "system": """You are an information extraction assistant. Extract key information from the email.
Respond in JSON with: dates, amounts, action_items, contacts, links_of_interest.""",
        "user": "Extract information from:\n\nFrom: {from}\nSubject: {subject}\n\nBody:\n{body}",
    },
    "draft_reply": {
        "system": """You are an email assistant. Draft a reply to the given email.
Tone: {tone}
Additional instructions: {instructions}

Write only the reply body, no subject line or headers.""",
        "user": "Draft a reply to:\n\nFrom: {from}\nSubject: {subject}\n\nBody:\n{body}",
    },
    "digest": {
        "system": """You are a digest composition assistant. Create a concise summary of the provided emails and content.
Group by category, highlight action items, and provide a brief overview.""",
        "user": "Create a digest from the following items:\n\n{items}",
    },
}


async def get_categories(db: AsyncSession) -> dict[str, str]:
    """Get configured categories from app settings, or defaults."""
    from app.models.audit import AppSetting
    import json
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "categories")
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value:
        try:
            return json.loads(setting.value)
        except (json.JSONDecodeError, TypeError):
            pass
    return DEFAULT_CATEGORIES


async def get_prompt(db: AsyncSession, task_type: str) -> tuple[str, str]:
    """Get active prompt for a task type. Falls back to defaults."""
    result = await db.execute(
        select(LlmPromptVersion)
        .where(LlmPromptVersion.task_type == task_type, LlmPromptVersion.is_active == True)
        .limit(1)
    )
    prompt = result.scalar_one_or_none()

    if prompt:
        return prompt.system_prompt, prompt.user_prompt_template

    # For classify, build prompt dynamically from configured categories
    if task_type == "classify":
        categories = await get_categories(db)
        system = build_classify_prompt(categories)
        return system, DEFAULT_PROMPTS["classify"]["user"]

    default = DEFAULT_PROMPTS.get(task_type)
    if default:
        return default["system"], default["user"]

    raise ValueError(f"No prompt found for task type: {task_type}")

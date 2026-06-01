import uuid
import logging
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.mail import MailMessage
from app.models.classification import ClassificationRule, MailClassification
from app.exceptions import NotFoundError

logger = logging.getLogger(__name__)


def _rule_matches(rule: ClassificationRule, message: MailMessage) -> bool:
    if not rule.enabled or not rule.conditions:
        return False
    conditions = rule.conditions
    if "from_contains" in conditions:
        if conditions["from_contains"].lower() not in (message.from_address or "").lower():
            return False
    if "subject_contains" in conditions:
        if conditions["subject_contains"].lower() not in (message.subject or "").lower():
            return False
    if "to_contains" in conditions:
        if conditions["to_contains"].lower() not in (message.to_addresses or "").lower():
            return False
    return True


def matching_rule_categories(
    message: MailMessage, rules: list[ClassificationRule]
) -> list[tuple[str, int]]:
    """All categories from matching rules, deduped (case-insensitive), keeping
    the highest priority per category. Rules are pre-sorted by priority desc."""
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for rule in rules:
        if not _rule_matches(rule, message):
            continue
        key = rule.category.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((rule.category, rule.priority))
    return out


async def classify_message(db: AsyncSession, message_id: uuid.UUID) -> list[MailClassification]:
    """Classify a single message using rules first, then LLM. A mail can get
    multiple categories -> returns one MailClassification row per category."""
    message = await db.get(MailMessage, message_id)
    if not message:
        raise NotFoundError("Message not found")

    # Try rule-based first
    result = await db.execute(
        select(ClassificationRule).order_by(ClassificationRule.priority.desc())
    )
    rules = result.scalars().all()

    rule_cats = matching_rule_categories(message, rules)
    if rule_cats:
        # Rules matched -> replace all existing rows with the rule categories.
        await db.execute(
            delete(MailClassification).where(MailClassification.message_id == message.id)
        )
        classifications = []
        for category, priority in rule_cats:
            obj = MailClassification(
                message_id=message.id,
                category=category,
                confidence=1.0,
                priority=priority,
                classified_by="rule",
            )
            db.add(obj)
            classifications.append(obj)
        await db.flush()
        for obj in classifications:
            await db.refresh(obj)
        return classifications

    # Fall back to LLM classification
    from app.llm.tasks.classify import classify_with_llm
    return await classify_with_llm(db, message)

import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.mail import MailMessage
from app.models.classification import ClassificationRule, MailClassification
from app.exceptions import NotFoundError

logger = logging.getLogger(__name__)


def apply_rules(message: MailMessage, rules: list[ClassificationRule]) -> MailClassification | None:
    """Apply rule-based pre-filter. Returns classification if a rule matches."""
    for rule in rules:
        if not rule.enabled or not rule.conditions:
            continue
        conditions = rule.conditions
        matched = True

        if "from_contains" in conditions:
            if conditions["from_contains"].lower() not in (message.from_address or "").lower():
                matched = False

        if "subject_contains" in conditions:
            if conditions["subject_contains"].lower() not in (message.subject or "").lower():
                matched = False

        if "to_contains" in conditions:
            if conditions["to_contains"].lower() not in (message.to_addresses or "").lower():
                matched = False

        if matched:
            return MailClassification(
                message_id=message.id,
                category=rule.category,
                confidence=1.0,
                priority=rule.priority,
                classified_by="rule",
            )
    return None


async def classify_message(db: AsyncSession, message_id: uuid.UUID) -> MailClassification:
    """Classify a single message using rules first, then LLM."""
    message = await db.get(MailMessage, message_id)
    if not message:
        raise NotFoundError("Message not found")

    # Check for existing classification
    existing_result = await db.execute(
        select(MailClassification).where(MailClassification.message_id == message.id).limit(1)
    )
    existing = existing_result.scalar_one_or_none()

    # Try rule-based first
    result = await db.execute(
        select(ClassificationRule).order_by(ClassificationRule.priority.desc())
    )
    rules = result.scalars().all()

    rule_match = apply_rules(message, rules)
    if rule_match:
        if existing:
            existing.category = rule_match.category
            existing.confidence = rule_match.confidence
            existing.priority = rule_match.priority
            existing.classified_by = "rule"
            await db.flush()
            await db.refresh(existing)
            return existing
        db.add(rule_match)
        await db.flush()
        await db.refresh(rule_match)
        return rule_match

    # Fall back to LLM classification
    from app.llm.tasks.classify import classify_with_llm
    classification = await classify_with_llm(db, message)
    return classification

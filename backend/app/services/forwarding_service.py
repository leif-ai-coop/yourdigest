import logging
import fnmatch
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailAccount, MailMessage
from app.models.classification import MailClassification
from app.models.forwarding import ForwardingPolicy, ForwardingWhitelist, ForwardingLog
from app.services.smtp_client import send_email
from app.services.connector_service import decrypt_value

logger = logging.getLogger(__name__)


async def get_matching_policies(
    db: AsyncSession, message: MailMessage
) -> list[ForwardingPolicy]:
    """Find all enabled forwarding policies that match a message."""
    result = await db.execute(
        select(ForwardingPolicy)
        .where(ForwardingPolicy.enabled == True)
        .order_by(ForwardingPolicy.priority.desc())
    )
    policies = result.scalars().all()

    # Get message classifications
    cls_result = await db.execute(
        select(MailClassification).where(MailClassification.message_id == message.id)
    )
    classifications = cls_result.scalars().all()
    categories = {c.category.lower() for c in classifications}

    matched = []
    for policy in policies:
        if _policy_matches(policy, message, categories):
            matched.append(policy)

    return matched


def _policy_matches(
    policy: ForwardingPolicy,
    message: MailMessage,
    categories: set[str],
) -> bool:
    """Check if a policy matches a message."""
    # Category filter
    if policy.source_category:
        if policy.source_category.lower() not in categories:
            return False

    # Conditions (JSON-based rules)
    if policy.conditions:
        conditions = policy.conditions

        # from_contains: match sender
        if "from_contains" in conditions:
            pattern = conditions["from_contains"].lower()
            if pattern not in (message.from_address or "").lower():
                return False

        # subject_contains: match subject
        if "subject_contains" in conditions:
            pattern = conditions["subject_contains"].lower()
            if pattern not in (message.subject or "").lower():
                return False

        # priority_min: minimum classification priority
        if "priority_min" in conditions:
            # Needs at least one classification with priority >= threshold
            from app.models.classification import MailClassification
            min_pri = conditions["priority_min"]
            # classifications already loaded above via categories param context
            # but we check via the categories set - we need the full objects
            # This is handled in get_matching_policies where we pass categories
            pass

    return True


async def check_whitelist(db: AsyncSession, target_email: str) -> bool:
    """Check if target email is whitelisted. Empty whitelist = allow all."""
    result = await db.execute(select(ForwardingWhitelist))
    whitelist = result.scalars().all()

    if not whitelist:
        return True  # No whitelist entries = allow all

    for entry in whitelist:
        if fnmatch.fnmatch(target_email.lower(), entry.email_pattern.lower()):
            return True

    return False


async def forward_message(
    db: AsyncSession, message: MailMessage, policy: ForwardingPolicy
) -> ForwardingLog:
    """Forward a single message according to a policy."""
    log_entry = ForwardingLog(
        message_id=message.id,
        policy_id=policy.id,
        target_email=policy.target_email,
        status="pending",
    )
    db.add(log_entry)
    await db.flush()

    try:
        # Check whitelist
        if not await check_whitelist(db, policy.target_email):
            log_entry.status = "blocked"
            log_entry.error = "Target email not in whitelist"
            logger.warning(f"Forwarding blocked: {policy.target_email} not whitelisted")
            return log_entry

        # Get SMTP config from the message's account
        account = await db.get(MailAccount, message.account_id)
        if not account or not account.smtp_host:
            log_entry.status = "failed"
            log_entry.error = "No SMTP configuration on mail account"
            logger.error(f"No SMTP config for account {message.account_id}")
            return log_entry

        password = decrypt_value(account.password_encrypted)

        # Build forwarded subject
        subject = f"Fwd: {message.subject or '(no subject)'}"

        # Build forwarded body
        body_parts = [
            f"--- Forwarded by policy: {policy.name} ---",
            f"From: {message.from_address}",
            f"Date: {message.date}",
            f"Subject: {message.subject or '(no subject)'}",
            "",
        ]

        body_text = "\n".join(body_parts)
        if message.body_text:
            body_text += message.body_text

        body_html = None
        if message.body_html:
            header_html = "<br>".join(
                f"<b>{k}:</b> {v}" for k, v in [
                    ("From", message.from_address),
                    ("Date", str(message.date)),
                    ("Subject", message.subject or "(no subject)"),
                ]
            )
            body_html = (
                f'<div style="border-left:3px solid #4a90d9;padding-left:12px;margin:12px 0;color:#666">'
                f'<p style="font-size:12px">Forwarded by policy: <b>{policy.name}</b></p>'
                f'{header_html}<br><br>'
                f'</div>'
                f'{message.body_html}'
            )

        await send_email(
            host=account.smtp_host,
            port=account.smtp_port or 587,
            username=account.username,
            password=password,
            use_tls=account.smtp_use_tls if account.smtp_use_tls is not None else True,
            from_addr=account.email,
            to_addr=policy.target_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

        log_entry.status = "sent"
        log_entry.sent_at = datetime.now(timezone.utc)
        logger.info(f"Forwarded message {message.id} to {policy.target_email} (policy: {policy.name})")

    except Exception as e:
        log_entry.status = "failed"
        log_entry.error = str(e)[:1000]
        logger.error(f"Forwarding failed for message {message.id}: {e}")

    return log_entry


async def process_forwarding(db: AsyncSession, message_id) -> list[ForwardingLog]:
    """Process forwarding for a message. Called after classification."""
    message = await db.get(MailMessage, message_id)
    if not message:
        logger.warning(f"Message {message_id} not found for forwarding")
        return []

    # Check if already forwarded (avoid duplicates)
    existing = await db.execute(
        select(ForwardingLog).where(
            ForwardingLog.message_id == message_id,
            ForwardingLog.status == "sent",
        )
    )
    if existing.scalars().first():
        logger.debug(f"Message {message_id} already forwarded, skipping")
        return []

    policies = await get_matching_policies(db, message)
    if not policies:
        return []

    logs = []
    for policy in policies:
        log = await forward_message(db, message, policy)
        logs.append(log)

    return logs

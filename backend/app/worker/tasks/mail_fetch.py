import logging
from sqlalchemy import select
from app.database import async_session
from app.models.mail import MailAccount
from app.services.mail_service import sync_account
from app.services.classification_service import classify_message
from app.services.forwarding_service import process_forwarding

logger = logging.getLogger(__name__)


async def mail_fetch_job():
    """Periodic job: fetch new mail from all enabled accounts, classify, and forward."""
    async with async_session() as db:
        try:
            result = await db.execute(
                select(MailAccount).where(MailAccount.enabled == True)
            )
            accounts = result.scalars().all()

            for account in accounts:
                try:
                    count = await sync_account(db, account)
                    if count > 0:
                        logger.info(f"Fetched {count} new messages from {account.email}")
                        # Auto-classify new messages
                        from sqlalchemy import select as sel, desc
                        from app.models.mail import MailMessage
                        # Only classify/forward INBOX messages
                        new_msgs = await db.execute(
                            sel(MailMessage)
                            .where(
                                MailMessage.account_id == account.id,
                                MailMessage.folder == "INBOX",
                            )
                            .order_by(desc(MailMessage.created_at))
                            .limit(count)
                        )
                        for msg in new_msgs.scalars():
                            try:
                                await classify_message(db, msg.id)
                            except Exception as e:
                                logger.error(f"Classification failed for {msg.id}: {e}")

                            # Process forwarding after classification
                            try:
                                logs = await process_forwarding(db, msg.id)
                                if logs:
                                    sent = sum(1 for l in logs if l.status == "sent")
                                    logger.info(f"Forwarded message {msg.id} to {sent} targets")
                            except Exception as e:
                                logger.error(f"Forwarding failed for {msg.id}: {e}")

                except Exception as e:
                    account.last_error = str(e)[:1000]
                    logger.error(f"Mail fetch failed for {account.email}: {e}")

            await db.commit()
        except Exception as e:
            logger.error(f"Mail fetch job error: {e}")
            await db.rollback()

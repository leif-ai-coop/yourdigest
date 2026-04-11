"""
Worker task: Send podcast summary mails according to mail policies.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.database import async_session
from app.models.podcast import PodcastMailPolicy, PodcastDeliveryRun
from app.services.podcast_delivery_service import send_podcast_mail

logger = logging.getLogger(__name__)


async def podcast_mail_job(policy_id: str):
    """Send podcast mail for a specific policy."""
    async with async_session() as db:
        try:
            from uuid import UUID
            policy = await db.get(PodcastMailPolicy, UUID(policy_id))
            if not policy:
                logger.error(f"Podcast mail policy {policy_id} not found")
                return

            # Find last successful delivery for this policy
            result = await db.execute(
                select(PodcastDeliveryRun)
                .where(
                    PodcastDeliveryRun.policy_id == policy.id,
                    PodcastDeliveryRun.delivery_channel == "podcast_mail",
                    PodcastDeliveryRun.status == "completed",
                )
                .order_by(PodcastDeliveryRun.completed_at.desc())
                .limit(1)
            )
            last_run = result.scalars().first()
            since = last_run.completed_at if last_run else datetime.now(timezone.utc) - timedelta(days=7)

            run = await send_podcast_mail(db, policy, since=since)
            await db.commit()
            logger.info(f"Podcast mail job for '{policy.name}': {run.episode_count} episodes, status={run.status}")

        except Exception as e:
            logger.error(f"Podcast mail job error for {policy_id}: {e}")
            await db.rollback()

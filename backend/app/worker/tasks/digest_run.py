import logging
import uuid
from app.database import async_session
from app.models.digest import DigestPolicy
from app.services.digest_service import compose_digest

logger = logging.getLogger(__name__)


async def digest_run_job(policy_id: str):
    """Run a specific digest policy by ID. Called by APScheduler per-policy cron."""
    async with async_session() as db:
        try:
            policy = await db.get(DigestPolicy, uuid.UUID(policy_id))
            if not policy or not policy.enabled:
                return

            run = await compose_digest(db, policy)
            logger.info(
                f"Digest run for '{policy.name}': status={run.status}, "
                f"items={run.item_count}"
            )
            await db.commit()
        except Exception as e:
            logger.error(f"Digest run job error for {policy_id}: {e}")
            await db.rollback()

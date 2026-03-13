import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def start_scheduler():
    from app.worker.tasks.mail_fetch import mail_fetch_job
    scheduler.add_job(mail_fetch_job, "interval", minutes=5, id="mail_fetch", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


async def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")

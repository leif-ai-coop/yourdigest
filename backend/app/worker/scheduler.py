import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sqlalchemy import select
from app.database import async_session

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def start_scheduler():
    from app.worker.tasks.mail_fetch import mail_fetch_job
    from app.worker.tasks.feed_fetch import feed_fetch_job
    from app.worker.tasks.weather_fetch import weather_fetch_job
    from app.worker.tasks.garmin_fetch import garmin_fetch_job
    from app.worker.tasks.podcast_fetch import podcast_fetch_job
    from app.worker.tasks.podcast_download import podcast_download_job
    from app.worker.tasks.podcast_transcribe import podcast_transcribe_job
    from app.worker.tasks.podcast_summarize import podcast_summarize_job

    scheduler.add_job(mail_fetch_job, "interval", minutes=5, id="mail_fetch", replace_existing=True)
    scheduler.add_job(feed_fetch_job, "interval", minutes=30, id="feed_fetch", replace_existing=True)
    scheduler.add_job(weather_fetch_job, "interval", minutes=60, id="weather_fetch", replace_existing=True)
    scheduler.add_job(garmin_fetch_job, "interval", minutes=60, id="garmin_fetch", replace_existing=True)

    # Podcast pipeline jobs
    scheduler.add_job(podcast_fetch_job, "interval", minutes=30, id="podcast_fetch", replace_existing=True)
    scheduler.add_job(podcast_download_job, "interval", minutes=10, id="podcast_download", replace_existing=True)
    scheduler.add_job(podcast_transcribe_job, "interval", minutes=5, id="podcast_transcribe", replace_existing=True)
    scheduler.add_job(podcast_summarize_job, "interval", minutes=5, id="podcast_summarize", replace_existing=True)

    # Schedule digest policies
    await schedule_digest_policies()

    # Schedule podcast mail policies
    await schedule_podcast_mail_policies()

    scheduler.start()
    logger.info("Scheduler started (mail: 5min, feeds: 30min, weather: 60min, garmin: 60min, podcast: fetch 30min, download 10min, transcribe 5min, summarize 5min)")


async def schedule_digest_policies():
    """Load enabled digest policies and schedule each one."""
    from app.worker.tasks.digest_run import digest_run_job
    from app.models.digest import DigestPolicy

    try:
        async with async_session() as db:
            result = await db.execute(
                select(DigestPolicy).where(DigestPolicy.enabled == True)
            )
            policies = result.scalars().all()

            for policy in policies:
                job_id = f"digest_{policy.id}"
                try:
                    trigger = CronTrigger.from_crontab(policy.schedule_cron)
                    scheduler.add_job(
                        digest_run_job,
                        trigger,
                        args=[str(policy.id)],
                        id=job_id,
                        replace_existing=True,
                    )
                    logger.info(f"Scheduled digest '{policy.name}' with cron '{policy.schedule_cron}'")
                except Exception as e:
                    logger.error(f"Failed to schedule digest '{policy.name}': {e}")

    except Exception as e:
        logger.error(f"Failed to load digest policies: {e}")


async def schedule_podcast_mail_policies():
    """Load enabled podcast mail policies and schedule each one."""
    from app.worker.tasks.podcast_mail import podcast_mail_job
    from app.models.podcast import PodcastMailPolicy

    try:
        async with async_session() as db:
            result = await db.execute(
                select(PodcastMailPolicy).where(PodcastMailPolicy.enabled == True)
            )
            policies = result.scalars().all()

            for policy in policies:
                job_id = f"podcast_mail_{policy.id}"
                try:
                    trigger = CronTrigger.from_crontab(policy.schedule_cron)
                    scheduler.add_job(
                        podcast_mail_job,
                        trigger,
                        args=[str(policy.id)],
                        id=job_id,
                        replace_existing=True,
                    )
                    logger.info(f"Scheduled podcast mail '{policy.name}' with cron '{policy.schedule_cron}'")
                except Exception as e:
                    logger.error(f"Failed to schedule podcast mail '{policy.name}': {e}")

    except Exception as e:
        logger.error(f"Failed to load podcast mail policies: {e}")


async def reload_digest_schedules():
    """Reload digest schedules (call after policy changes)."""
    # Remove existing digest jobs
    for job in scheduler.get_jobs():
        if job.id.startswith("digest_"):
            scheduler.remove_job(job.id)

    await schedule_digest_policies()
    logger.info("Digest schedules reloaded")


async def reload_podcast_mail_schedules():
    """Reload podcast mail schedules (call after policy changes)."""
    for job in scheduler.get_jobs():
        if job.id.startswith("podcast_mail_"):
            scheduler.remove_job(job.id)

    await schedule_podcast_mail_policies()
    logger.info("Podcast mail schedules reloaded")


async def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")

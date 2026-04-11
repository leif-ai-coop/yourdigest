"""
Podcast Delivery Service — Mail-Rendering und Delivery-Run-Logging.
"""
import html
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.podcast import (
    PodcastEpisode, PodcastArtifact, PodcastFeed, PodcastMailPolicy,
    PodcastDeliveryRun, PodcastDeliveryRunEpisode, PodcastPrompt,
)
from app.models.mail import MailAccount
from app.services.smtp_client import send_email
from app.services.connector_service import decrypt_value

logger = logging.getLogger(__name__)


async def get_ready_episodes(
    db: AsyncSession,
    since: datetime | None = None,
    feed_ids: list | None = None,
) -> list[tuple[PodcastEpisode, PodcastArtifact, str | None]]:
    """Get episodes with active summaries ready for delivery.
    Returns list of (episode, summary_artifact, feed_title) tuples.
    """
    query = (
        select(PodcastEpisode, PodcastArtifact, PodcastFeed.title)
        .join(PodcastArtifact, and_(
            PodcastArtifact.episode_id == PodcastEpisode.id,
            PodcastArtifact.artifact_type == "summary",
            PodcastArtifact.is_active == True,
        ))
        .join(PodcastFeed, PodcastFeed.id == PodcastEpisode.feed_id)
        .where(PodcastEpisode.processing_status == "done")
        .order_by(PodcastEpisode.published_at.desc())
    )

    if since:
        query = query.where(PodcastArtifact.created_at >= since)
    if feed_ids:
        query = query.where(PodcastEpisode.feed_id.in_(feed_ids))

    result = await db.execute(query)
    return result.all()


def render_podcast_mail_html(
    episodes: list[tuple[PodcastEpisode, PodcastArtifact, str | None]],
    title: str = "Podcast-Zusammenfassungen",
) -> str:
    """Render podcast summaries as HTML email."""
    sections = []

    # Group by feed
    by_feed: dict[str, list] = {}
    for episode, artifact, feed_title in episodes:
        key = feed_title or "Unbekannt"
        by_feed.setdefault(key, []).append((episode, artifact))

    for feed_title, items in by_feed.items():
        feed_html = f'<h2 style="color:#6366f1;margin:24px 0 12px 0;font-size:18px;">{html.escape(feed_title)}</h2>'

        for episode, artifact in items:
            ep_title = html.escape(episode.title or "Ohne Titel")
            date_str = episode.published_at.strftime("%d.%m.%Y") if episode.published_at else ""
            duration_str = ""
            if episode.duration_seconds:
                mins = episode.duration_seconds // 60
                duration_str = f" &middot; {mins} min"

            summary_html = html.escape(artifact.content or "").replace("\n", "<br>")

            feed_html += f'''
            <div style="margin:0 0 20px 0;padding:16px;background:#1e1e2e;border-radius:8px;border-left:3px solid #6366f1;">
                <h3 style="margin:0 0 4px 0;font-size:15px;color:#e2e8f0;">{ep_title}</h3>
                <div style="font-size:12px;color:#94a3b8;margin-bottom:10px;">{date_str}{duration_str}</div>
                <div style="font-size:14px;color:#cbd5e1;line-height:1.6;">{summary_html}</div>
                {"<a href='" + html.escape(episode.link) + "' style='color:#818cf8;font-size:13px;text-decoration:none;'>Zur Episode &rarr;</a>" if episode.link else ""}
            </div>
            '''

        sections.append(feed_html)

    body = "\n".join(sections) if sections else '<p style="color:#94a3b8;">Keine neuen Podcast-Zusammenfassungen.</p>'

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:640px;margin:0 auto;padding:24px;">
    <h1 style="color:#e2e8f0;font-size:22px;margin-bottom:24px;">{html.escape(title)}</h1>
    {body}
    <div style="margin-top:32px;padding-top:16px;border-top:1px solid #2d2d3f;font-size:12px;color:#64748b;">
        You Digest &mdash; Podcast-Zusammenfassungen
    </div>
</div>
</body>
</html>'''


async def send_podcast_mail(
    db: AsyncSession,
    policy: PodcastMailPolicy,
    since: datetime | None = None,
) -> PodcastDeliveryRun:
    """Execute a podcast mail policy: find ready episodes, render, send, log."""
    run = PodcastDeliveryRun(
        delivery_channel="podcast_mail",
        policy_id=policy.id,
        started_at=datetime.now(timezone.utc),
        status="running",
        prompt_id=policy.prompt_id,
    )
    db.add(run)
    await db.flush()

    try:
        # Parse feed filter
        feed_ids = None
        if policy.feed_filter:
            feed_ids = policy.feed_filter if isinstance(policy.feed_filter, list) else None

        episodes = await get_ready_episodes(db, since=since, feed_ids=feed_ids)

        if not episodes:
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.episode_count = 0
            logger.info(f"Podcast mail policy '{policy.name}': no new episodes")
            return run

        # Render HTML
        mail_html = render_podcast_mail_html(episodes, title=f"Podcast: {policy.name}")

        # Get SMTP account
        result = await db.execute(
            select(MailAccount).where(MailAccount.enabled == True).limit(1)
        )
        account = result.scalars().first()
        if not account or not account.smtp_host:
            raise ValueError("No mail account configured for sending")

        password = decrypt_value(account.password_encrypted)

        # Send
        await send_email(
            host=account.smtp_host,
            port=account.smtp_port or 587,
            username=account.username,
            password=password,
            use_tls=account.smtp_use_tls if account.smtp_use_tls is not None else True,
            from_addr=account.email,
            to_addr=policy.target_email,
            subject=f"Podcast-Zusammenfassungen — {policy.name}",
            body_text=f"{len(episodes)} neue Podcast-Zusammenfassungen",
            body_html=mail_html,
        )

        # Log delivery
        for episode, artifact, feed_title in episodes:
            run_episode = PodcastDeliveryRunEpisode(
                run_id=run.id,
                episode_id=episode.id,
                artifact_id=artifact.id,
            )
            db.add(run_episode)

            # Update convenience cache
            now = datetime.now(timezone.utc)
            if not episode.first_delivery_at:
                episode.first_delivery_at = now
            episode.last_delivery_at = now

        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        run.episode_count = len(episodes)
        logger.info(f"Podcast mail sent for policy '{policy.name}': {len(episodes)} episodes to {policy.target_email}")
        return run

    except Exception as e:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        run.error = str(e)[:2000]
        logger.error(f"Podcast mail failed for policy '{policy.name}': {e}")
        return run


def render_podcast_digest_section(
    episodes: list[tuple[PodcastEpisode, PodcastArtifact, str | None]],
) -> str:
    """Render podcast summaries as a digest section (compact format)."""
    if not episodes:
        return ""

    items_html = []
    for episode, artifact, feed_title in episodes[:10]:  # Max 10 in digest
        ep_title = html.escape(episode.title or "Ohne Titel")
        feed_name = html.escape(feed_title or "")
        date_str = episode.published_at.strftime("%d.%m.") if episode.published_at else ""

        # Truncate summary for digest
        summary = artifact.content or ""
        if len(summary) > 500:
            summary = summary[:497] + "..."
        summary_html = html.escape(summary).replace("\n", "<br>")

        items_html.append(f'''
        <div style="margin:0 0 16px 0;padding:12px;background:#1e1e2e;border-radius:6px;">
            <div style="font-size:11px;color:#818cf8;margin-bottom:2px;">{feed_name}</div>
            <div style="font-size:14px;color:#e2e8f0;font-weight:500;margin-bottom:4px;">
                {"<a href='" + html.escape(episode.link) + "' style='color:#e2e8f0;text-decoration:none;'>" + ep_title + "</a>" if episode.link else ep_title}
            </div>
            <div style="font-size:12px;color:#94a3b8;margin-bottom:8px;">{date_str}</div>
            <div style="font-size:13px;color:#cbd5e1;line-height:1.5;">{summary_html}</div>
        </div>
        ''')

    return f'''
    <div style="margin:24px 0;">
        <h2 style="color:#e2e8f0;font-size:18px;margin-bottom:16px;">
            <span style="color:#818cf8;">&#127911;</span> Podcast-Zusammenfassungen
        </h2>
        {"".join(items_html)}
    </div>
    '''

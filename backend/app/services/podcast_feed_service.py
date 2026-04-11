"""
Podcast Feed Service — Feed-Fetch, Episode-Erkennung, Dedup-Kaskade.
"""
import hashlib
import logging
import re
from datetime import datetime, timezone

import bleach
import feedparser
import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.podcast import PodcastFeed, PodcastEpisode

logger = logging.getLogger(__name__)


_SAFE_TAGS = list(bleach.ALLOWED_TAGS) + [
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "div", "span",
    "ul", "ol", "li", "hr", "pre", "code", "blockquote",
    "sup", "sub", "small", "del", "ins", "mark",
]
_SAFE_ATTRS = {"a": ["href", "title", "target", "rel"], "*": ["class"]}


def _sanitize_description(html: str | None) -> str | None:
    if not html:
        return html
    return bleach.clean(html, tags=_SAFE_TAGS, attributes=_SAFE_ATTRS, strip=True)[:5000]


def _normalize_title(title: str) -> str:
    """Normalize title for hashing: lowercase, strip whitespace, collapse spaces."""
    return re.sub(r'\s+', ' ', title.strip().lower())


def _compute_content_hash(feed_id, title: str | None, published_at: datetime | None) -> str:
    """Fallback dedup hash from feed_id + normalized title + published date."""
    parts = [
        str(feed_id),
        _normalize_title(title or ""),
        published_at.isoformat() if published_at else "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _parse_duration(raw: str | None) -> int | None:
    """Parse podcast duration from 'HH:MM:SS', 'MM:SS', or seconds string."""
    if not raw:
        return None
    raw = raw.strip()
    # Pure number = seconds
    if raw.isdigit():
        return int(raw)
    parts = raw.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, TypeError):
        pass
    return None


def _should_skip_episode(feed: PodcastFeed, episode_title: str | None, duration: int | None, audio_size: int | None) -> str | None:
    """Check feed rules and return skip reason, or None if episode should be accepted."""
    # Min duration filter
    if feed.min_episode_duration_seconds and duration is not None:
        if duration < feed.min_episode_duration_seconds:
            return f"duration {duration}s < min {feed.min_episode_duration_seconds}s"

    # Max duration filter
    if feed.max_episode_duration_seconds and duration is not None:
        if duration > feed.max_episode_duration_seconds:
            return f"duration {duration}s > max {feed.max_episode_duration_seconds}s"

    # Max size filter
    if feed.max_audio_size_mb and audio_size is not None:
        max_bytes = feed.max_audio_size_mb * 1024 * 1024
        if audio_size > max_bytes:
            return f"size {audio_size} > max {feed.max_audio_size_mb}MB"

    # Title pattern filter
    if feed.ignore_title_patterns and episode_title:
        patterns = feed.ignore_title_patterns
        if isinstance(patterns, list):
            for pattern in patterns:
                try:
                    if re.search(pattern, episode_title, re.IGNORECASE):
                        return f"title matches ignore pattern '{pattern}'"
                except re.error:
                    pass

    return None


async def _find_existing_episode(
    db: AsyncSession, feed_id, guid: str | None, audio_url: str | None, content_hash: str
) -> bool:
    """Dedup cascade: guid → audio_url → content_hash."""
    # 1. Check guid
    if guid:
        result = await db.execute(
            select(PodcastEpisode.id).where(
                PodcastEpisode.feed_id == feed_id,
                PodcastEpisode.guid == guid,
            )
        )
        if result.scalar_one_or_none():
            return True

    # 2. Check audio_url
    if audio_url:
        result = await db.execute(
            select(PodcastEpisode.id).where(
                PodcastEpisode.feed_id == feed_id,
                PodcastEpisode.audio_url == audio_url,
            )
        )
        if result.scalar_one_or_none():
            return True

    # 3. Check content_hash
    result = await db.execute(
        select(PodcastEpisode.id).where(
            PodcastEpisode.feed_id == feed_id,
            PodcastEpisode.content_hash == content_hash,
        )
    )
    if result.scalar_one_or_none():
        return True

    return False


async def fetch_podcast_feed(db: AsyncSession, feed: PodcastFeed) -> int:
    """Fetch a podcast RSS feed and create new episodes. Returns count of new episodes."""
    headers = {}
    if feed.etag:
        headers["If-None-Match"] = feed.etag
    if feed.last_modified:
        headers["If-Modified-Since"] = feed.last_modified

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(feed.url, headers=headers, follow_redirects=True)

            # 304 Not Modified
            if resp.status_code == 304:
                feed.last_fetched_at = datetime.now(timezone.utc)
                feed.consecutive_failures = 0
                return 0

            resp.raise_for_status()

        # Store conditional fetch headers
        if "etag" in resp.headers:
            feed.etag = resp.headers["etag"][:500]
        if "last-modified" in resp.headers:
            feed.last_modified = resp.headers["last-modified"][:500]

        parsed = feedparser.parse(resp.text)

        if parsed.bozo and not parsed.entries:
            error = str(parsed.bozo_exception) if parsed.bozo_exception else "Invalid feed"
            feed.last_error = error[:500]
            feed.last_fetched_at = datetime.now(timezone.utc)
            feed.consecutive_failures += 1
            return 0

        # Update feed metadata
        feed_info = parsed.feed
        if feed_info.get("title") and not feed.title:
            feed.title = feed_info["title"][:500]
        if feed_info.get("subtitle") and not feed.description:
            feed.description = feed_info["subtitle"][:2000]
        if feed_info.get("image") and not feed.image_url:
            img = feed_info["image"]
            if isinstance(img, dict):
                feed.image_url = img.get("href", "")[:2000]
            elif isinstance(img, str):
                feed.image_url = img[:2000]
        if feed_info.get("language") and not feed.language:
            feed.language = feed_info["language"][:10]

        # Determine if this is the initial fetch (no episodes exist yet)
        is_initial_fetch = feed.last_successful_fetch_at is None

        # Collect new episodes first, then decide which to accept
        new_episodes = []
        for entry in parsed.entries:
            # Extract enclosure (audio URL)
            audio_url = None
            audio_size = None
            mime_type = None
            for enc in entry.get("enclosures", []):
                enc_type = enc.get("type", "")
                if enc_type.startswith("audio/") or enc_type == "":
                    audio_url = enc.get("href") or enc.get("url")
                    try:
                        audio_size = int(enc.get("length", 0)) or None
                    except (ValueError, TypeError):
                        audio_size = None
                    mime_type = enc_type or None
                    break

            # If no enclosure, check for media content
            if not audio_url:
                for media in entry.get("media_content", []):
                    if media.get("type", "").startswith("audio/"):
                        audio_url = media.get("url")
                        mime_type = media.get("type")
                        break

            # Skip entries without audio
            if not audio_url:
                continue

            guid = entry.get("id") or entry.get("guid")
            title = entry.get("title", "")[:500] if entry.get("title") else None

            # Parse published date
            published = None
            for date_field in ("published_parsed", "updated_parsed"):
                if entry.get(date_field):
                    try:
                        published = datetime(*entry[date_field][:6], tzinfo=timezone.utc)
                        break
                    except (TypeError, ValueError):
                        pass

            # Parse duration
            duration = _parse_duration(
                entry.get("itunes_duration") or entry.get("duration")
            )

            # Parse episode/season number
            episode_number = None
            season_number = None
            if entry.get("itunes_episode"):
                try:
                    episode_number = int(entry["itunes_episode"])
                except (ValueError, TypeError):
                    pass
            if entry.get("itunes_season"):
                try:
                    season_number = int(entry["itunes_season"])
                except (ValueError, TypeError):
                    pass

            # Content hash for dedup fallback
            content_hash = _compute_content_hash(feed.id, title, published)

            # Dedup check
            if await _find_existing_episode(db, feed.id, guid, audio_url, content_hash):
                continue

            # Check skip rules
            skip_reason = _should_skip_episode(feed, title, duration, audio_size)

            description = None
            if entry.get("summary"):
                description = _sanitize_description(entry["summary"])
            elif entry.get("content"):
                description = _sanitize_description(entry["content"][0].get("value", ""))

            new_episodes.append({
                "guid": guid, "audio_url": audio_url, "content_hash": content_hash,
                "title": title, "description": description,
                "link": entry.get("link", "")[:2000] if entry.get("link") else None,
                "episode_number": episode_number, "season_number": season_number,
                "audio_size_bytes": audio_size, "mime_type": mime_type,
                "duration_seconds": duration, "published_at": published,
                "skip_reason": skip_reason,
            })

        # On initial fetch: only the most recent episode gets accepted,
        # all older ones are skipped as historical backlog.
        # On subsequent fetches: all new episodes are accepted (they are genuinely new).
        if is_initial_fetch and len(new_episodes) > 1:
            # Sort by published_at descending, newest first
            new_episodes.sort(key=lambda e: e["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            newest_index = 0  # Only the first (newest) one
        else:
            newest_index = None  # Accept all

        new_count = 0
        for i, ep_data in enumerate(new_episodes):
            skip_reason = ep_data.pop("skip_reason")

            # On initial fetch: skip all except the newest
            if is_initial_fetch and newest_index is not None and i != newest_index:
                skip_reason = skip_reason or "historical episode (initial feed import)"

            if skip_reason:
                discovery = "skipped"
                proc_status = "skipped"
                summarize = False
            elif feed.auto_process_new:
                discovery = "accepted"
                proc_status = "pending"
                summarize = True
            else:
                discovery = "new"
                proc_status = "new"
                summarize = True

            episode = PodcastEpisode(
                feed_id=feed.id,
                discovery_status=discovery,
                skipped_reason=skip_reason,
                processing_status=proc_status,
                summarize_enabled=summarize,
                **ep_data,
            )
            db.add(episode)
            new_count += 1

        feed.last_fetched_at = datetime.now(timezone.utc)
        feed.last_successful_fetch_at = datetime.now(timezone.utc)
        feed.consecutive_failures = 0
        feed.last_error = None
        return new_count

    except httpx.HTTPError as e:
        feed.last_error = f"HTTP error: {e}"[:500]
        feed.last_fetched_at = datetime.now(timezone.utc)
        feed.consecutive_failures += 1
        logger.error(f"Podcast feed fetch failed for {feed.url}: {e}")
        return 0
    except Exception as e:
        feed.last_error = str(e)[:500]
        feed.last_fetched_at = datetime.now(timezone.utc)
        feed.consecutive_failures += 1
        logger.error(f"Podcast feed fetch failed for {feed.url}: {e}")
        return 0


async def fetch_all_podcast_feeds(db: AsyncSession) -> int:
    """Fetch all enabled podcast feeds. Returns total new episodes."""
    result = await db.execute(
        select(PodcastFeed).where(PodcastFeed.enabled == True)
    )
    feeds = result.scalars().all()

    total = 0
    for feed in feeds:
        count = await fetch_podcast_feed(db, feed)
        if count > 0:
            logger.info(f"Discovered {count} new episodes from '{feed.title or feed.url}'")
        total += count

    return total

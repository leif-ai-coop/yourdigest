import uuid
import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, async_session
from app.models.assistant import AssistantConversation, AssistantMessage
from app.models.audit import AppSetting
from app.models.digest import DigestPolicy
from app.models.mail import MailMessage, MailAccount
from app.models.podcast import (
    PodcastFeed, PodcastEpisode, PodcastEpisodeChunk, PodcastArtifact,
    PodcastPrompt, PodcastProcessingRun,
)
from app.models.forwarding import ForwardingPolicy
from app.schemas.assistant import MessageSend, ConversationOut, ConversationDetail
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """Du bist der You Digest Assistant — ein hilfsbereiter, deutschsprachiger Assistent.
Du hilfst dem Benutzer bei der Verwaltung seiner E-Mails, Digests, RSS-Feeds, Gesundheitsdaten, Podcasts und Weiterleitungen.
Antworte praezise und freundlich. Halte deine Antworten kurz und relevant.

Wenn der Benutzer nach E-Mail-Inhalten fragt, gehe zweistufig vor:
1. Nutze browse_recent_mails um einen Ueberblick (Absender + Betreff) zu bekommen
2. Nutze read_mail nur fuer die relevanten Mails, deren Inhalt du wirklich brauchst

Wenn der Benutzer nach Podcast-Episoden fragt, gehe zweistufig vor:
1. Nutze list_podcast_episodes um einen Ueberblick zu bekommen
2. Nutze get_podcast_episode nur fuer die Episode, deren Summary/Transkript du wirklich brauchst

Wenn du eine Aktion ausfuehren sollst (z.B. Digest anlegen, Podcast-Feed hinzufuegen), nutze die verfuegbaren Tools.
Frage nach fehlenden Informationen bevor du ein Tool aufrufst.

Folgende Dinge kannst du NICHT ueber Tools erledigen — weise den Benutzer darauf hin, dass er das manuell im UI machen muss:
- Podcast-Prompts erstellen oder loeschen (unter Podcasts → Prompts)
- Podcast-Mail-Policies erstellen oder verwalten (unter Podcasts → Mail-Policies)
- Chunking-Konfiguration aendern
- Podcast-Prompts bearbeiten geht nur ueber update_podcast_prompt (Inhalt aendern), aber nicht anlegen/loeschen"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_digest_policies",
            "description": "Liste alle bestehenden Digest-Policies auf, um zu sehen welche Digests konfiguriert sind.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_digest_policy",
            "description": "Erstelle eine neue Digest-Policy. Der Digest sammelt E-Mails und optionale RSS/Wetter-Daten und sendet eine Zusammenfassung per E-Mail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name des Digests, z.B. 'Abend-Digest'"},
                    "schedule_cron": {"type": "string", "description": "Cron-Ausdruck fuer den Zeitplan, z.B. '0 18 * * *' fuer taeglich 18:00"},
                    "target_email": {"type": "string", "description": "Ziel-E-Mail-Adresse fuer den Digest (optional, leer = Standard)"},
                    "include_weather": {"type": "boolean", "description": "Wetter-Informationen einbeziehen", "default": True},
                    "include_feeds": {"type": "boolean", "description": "RSS-Feed-Inhalte einbeziehen", "default": True},
                    "weather_prompt": {"type": "string", "description": "Spezieller Prompt fuer die Wetter-Zusammenfassung (optional)"},
                    "digest_prompt": {"type": "string", "description": "Spezieller Prompt fuer die Digest-Zusammenfassung (optional)"},
                    "max_tokens": {"type": "integer", "description": "Maximale Token-Anzahl fuer die AI-Zusammenfassung", "default": 4000},
                    "since_last_any_digest": {"type": "boolean", "description": "Wenn true: Zeitraum beginnt beim letzten Lauf einer beliebigen Digest-Policy (cross-policy). Nützlich wenn mehrere Digests sich nicht ueberlappen sollen.", "default": False},
                },
                "required": ["name", "schedule_cron"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inbox_summary",
            "description": "Zeige eine Zusammenfassung des aktuellen Posteingangs: Anzahl Mails, ungelesene, geflaggte.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_mail_accounts",
            "description": "Liste alle konfigurierten Mail-Accounts auf.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browse_recent_mails",
            "description": "Zeige eine kompakte Liste der letzten E-Mails (Absender + Betreff + Datum + ID). Nutze dieses Tool als ERSTEN Schritt um einen Ueberblick zu bekommen. Danach kannst du mit read_mail gezielt einzelne Mails lesen. Optional nach Suchbegriff filtern (durchsucht Betreff und Absender).",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Zeitraum in Tagen (default: 7)", "default": 7},
                    "search": {"type": "string", "description": "Optionaler Suchbegriff (durchsucht Betreff und Absender)"},
                    "limit": {"type": "integer", "description": "Maximale Anzahl Ergebnisse (default: 50)", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_mail",
            "description": "Lese den vollstaendigen Inhalt einer einzelnen E-Mail anhand ihrer ID. Nutze browse_recent_mails zuerst um die richtige Mail zu finden, dann dieses Tool fuer den Inhalt. Der Body wird auf 3000 Zeichen gekuerzt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Die UUID der E-Mail (aus browse_recent_mails)"},
                },
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_digest_run",
            "description": "Fuehre einen Digest manuell aus. Optionaler Zeitraum in Stunden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_name": {"type": "string", "description": "Name der Digest-Policy die ausgefuehrt werden soll"},
                    "since_hours": {"type": "integer", "description": "Zeitraum in Stunden (optional, default = seit letztem Lauf)"},
                },
                "required": ["policy_name"],
            },
        },
    },
    # --- Podcast Tools ---
    {
        "type": "function",
        "function": {
            "name": "list_podcast_feeds",
            "description": "Liste alle Podcast-Feeds auf mit Status, Modellen und Episoden-Zahlen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_podcast_feed",
            "description": "Fuege einen neuen Podcast-Feed hinzu. Beim Hinzufuegen wird nur die neueste Episode automatisch verarbeitet, aeltere werden uebersprungen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "RSS-Feed-URL des Podcasts"},
                    "title": {"type": "string", "description": "Optionaler benutzerdefinierter Titel"},
                    "auto_process_new": {"type": "boolean", "description": "Neue Episoden automatisch verarbeiten (default: true)", "default": True},
                    "min_episode_duration_seconds": {"type": "integer", "description": "Minimale Episodendauer in Sekunden (filtert Trailer, z.B. 180)"},
                    "max_episode_duration_seconds": {"type": "integer", "description": "Maximale Episodendauer in Sekunden"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_podcast_feed",
            "description": "Aendere Einstellungen eines Podcast-Feeds: Modelle, Intervall, Limits, enabled, Prompts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "feed_name": {"type": "string", "description": "Name oder Teil des Feed-Titels"},
                    "enabled": {"type": "boolean", "description": "Feed aktivieren/deaktivieren"},
                    "auto_process_new": {"type": "boolean", "description": "Neue Episoden automatisch verarbeiten"},
                    "transcription_model": {"type": "string", "description": "Modell fuer Transkription (leer = global default)"},
                    "summary_model": {"type": "string", "description": "Modell fuer Zusammenfassung (leer = global default)"},
                    "fetch_interval_minutes": {"type": "integer", "description": "Fetch-Intervall in Minuten"},
                    "min_episode_duration_seconds": {"type": "integer", "description": "Minimale Episodendauer in Sekunden"},
                    "max_episode_duration_seconds": {"type": "integer", "description": "Maximale Episodendauer in Sekunden"},
                    "language": {"type": "string", "description": "Sprache des Podcasts (z.B. 'de', 'en')"},
                },
                "required": ["feed_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_podcast_feed",
            "description": "Loesche einen Podcast-Feed und alle zugehoerigen Episoden.",
            "parameters": {
                "type": "object",
                "properties": {
                    "feed_name": {"type": "string", "description": "Name oder Teil des Feed-Titels"},
                },
                "required": ["feed_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_podcast_episodes",
            "description": "Liste Episoden eines Podcast-Feeds auf. Zeigt Titel, Datum, Dauer, Status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "feed_name": {"type": "string", "description": "Name oder Teil des Feed-Titels (leer = alle Feeds)"},
                    "status": {"type": "string", "description": "Filter nach processing_status: done, error, pending, skipped"},
                    "search": {"type": "string", "description": "Suchbegriff (durchsucht Titel, Beschreibung, Summary, Transkript)"},
                    "limit": {"type": "integer", "description": "Maximale Anzahl (default: 20)", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_podcast_episode",
            "description": "Zeige Details einer Podcast-Episode: Summary, Transkript-Auszug, Status, Chunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "string", "description": "UUID der Episode (aus list_podcast_episodes)"},
                },
                "required": ["episode_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_podcast_episode",
            "description": "Starte die Verarbeitung einer Podcast-Episode (Download, Transkription, Zusammenfassung). Laeuft im Hintergrund.",
            "parameters": {
                "type": "object",
                "properties": {
                    "episode_id": {"type": "string", "description": "UUID der Episode"},
                },
                "required": ["episode_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_podcast_prompts",
            "description": "Liste alle Podcast-Zusammenfassungs-Prompts auf.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_podcast_prompt",
            "description": "Aendere den Inhalt eines bestehenden Podcast-Prompts. Zum Anlegen oder Loeschen von Prompts verwende das UI unter Podcasts → Prompts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt_name": {"type": "string", "description": "Name oder Teil des Prompt-Namens"},
                    "system_prompt": {"type": "string", "description": "Neuer Prompt-Text"},
                    "name": {"type": "string", "description": "Neuer Name (optional)"},
                    "description": {"type": "string", "description": "Neue Beschreibung (optional)"},
                },
                "required": ["prompt_name", "system_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_podcast_queue",
            "description": "Zeige den aktuellen Verarbeitungsstatus der Podcast-Pipeline: Pending, aktive Verarbeitungen, Fehler.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_podcast_settings",
            "description": "Setze die globalen Podcast-AI-Modelle (Transkription und Summary). Gilt fuer alle Feeds ohne individuelle Einstellung.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transcription_model": {"type": "string", "description": "Modell fuer Transkription (z.B. 'google/gemini-2.5-flash')"},
                    "summary_model": {"type": "string", "description": "Modell fuer Zusammenfassung"},
                },
                "required": [],
            },
        },
    },
]


async def _get_assistant_setting(db: AsyncSession, key: str, default: int) -> int:
    """Get an assistant setting from app_settings table."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == f"assistant_{key}"))
    setting = result.scalar_one_or_none()
    if setting and setting.value:
        try:
            return int(setting.value)
        except ValueError:
            pass
    return default


async def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool call and return the result as a string."""
    async with async_session() as db:
        try:
            if tool_name == "list_digest_policies":
                result = await db.execute(select(DigestPolicy))
                policies = result.scalars().all()
                if not policies:
                    return "Keine Digest-Policies konfiguriert."
                items = []
                for p in policies:
                    cross = ", cross-policy" if p.since_last_any_digest else ""
                    items.append(f"- **{p.name}**: Cron `{p.schedule_cron}`, Wetter: {'ja' if p.include_weather else 'nein'}, Feeds: {'ja' if p.include_feeds else 'nein'}, Ziel: {p.target_email or 'Standard'}, aktiv: {'ja' if p.enabled else 'nein'}{cross}")
                return "\n".join(items)

            elif tool_name == "create_digest_policy":
                policy = DigestPolicy(
                    name=args["name"],
                    schedule_cron=args["schedule_cron"],
                    target_email=args.get("target_email"),
                    include_weather=args.get("include_weather", True),
                    include_feeds=args.get("include_feeds", True),
                    weather_prompt=args.get("weather_prompt"),
                    digest_prompt=args.get("digest_prompt"),
                    max_tokens=args.get("max_tokens", 4000),
                    since_last_any_digest=args.get("since_last_any_digest", False),
                    enabled=True,
                )
                db.add(policy)
                await db.commit()
                await db.refresh(policy)
                # Reload scheduler
                try:
                    from app.worker.scheduler import reload_digest_schedules
                    await reload_digest_schedules()
                except Exception:
                    pass
                return f"Digest-Policy '{policy.name}' erfolgreich erstellt (ID: {policy.id}). Zeitplan: {policy.schedule_cron}. Wetter: {'ja' if policy.include_weather else 'nein'}, Feeds: {'ja' if policy.include_feeds else 'nein'}."

            elif tool_name == "get_inbox_summary":
                total = await db.scalar(select(func.count(MailMessage.id)))
                unread = await db.scalar(select(func.count(MailMessage.id)).where(MailMessage.is_read == False))
                flagged = await db.scalar(select(func.count(MailMessage.id)).where(MailMessage.is_flagged == True))
                archived = await db.scalar(select(func.count(MailMessage.id)).where(MailMessage.is_archived == True))
                return f"Posteingang: {total} Mails gesamt, {unread} ungelesen, {flagged} markiert, {archived} archiviert."

            elif tool_name == "list_mail_accounts":
                result = await db.execute(select(MailAccount))
                accounts = result.scalars().all()
                if not accounts:
                    return "Keine Mail-Accounts konfiguriert."
                items = []
                for a in accounts:
                    items.append(f"- **{a.email}** ({a.display_name or 'kein Name'}): IMAP {a.imap_host}, aktiv: {'ja' if a.enabled else 'nein'}")
                return "\n".join(items)

            elif tool_name == "browse_recent_mails":
                from datetime import datetime, timezone, timedelta
                default_days = await _get_assistant_setting(db, "browse_days", 7)
                default_limit = await _get_assistant_setting(db, "browse_limit", 50)
                days = args.get("days", default_days)
                search = args.get("search")
                limit = min(args.get("limit", default_limit), 200)

                since = datetime.now(timezone.utc) - timedelta(days=days)
                query = (
                    select(MailMessage)
                    .where(MailMessage.date >= since)
                    .order_by(MailMessage.date.desc())
                    .limit(limit)
                )
                if search:
                    query = query.where(
                        MailMessage.subject.ilike(f"%{search}%")
                        | MailMessage.from_address.ilike(f"%{search}%")
                    )

                result = await db.execute(query)
                mails = result.scalars().all()
                if not mails:
                    return f"Keine Mails in den letzten {days} Tagen gefunden" + (f" mit Suche '{search}'" if search else "") + "."

                lines = [f"**{len(mails)} Mails** (letzte {days} Tage)" + (f", Suche: '{search}'" if search else "") + ":\n"]
                for m in mails:
                    date_str = m.date.strftime("%d.%m. %H:%M") if m.date else "?"
                    read_marker = "" if m.is_read else " [NEU]"
                    flag_marker = " ⭐" if m.is_flagged else ""
                    lines.append(f"- `{m.id}` | {date_str} | **{m.from_address}** | {m.subject or '(kein Betreff)'}{read_marker}{flag_marker}")
                return "\n".join(lines)

            elif tool_name == "read_mail":
                msg_id = args["message_id"]
                try:
                    msg = await db.get(MailMessage, uuid.UUID(msg_id))
                except (ValueError, AttributeError):
                    return f"Ungueltige Mail-ID: {msg_id}"
                if not msg:
                    return f"Mail mit ID {msg_id} nicht gefunden."

                body = msg.body_text or ""
                if not body and msg.body_html:
                    # Strip HTML tags for a rough text version
                    import re
                    body = re.sub(r'<[^>]+>', ' ', msg.body_html)
                    body = re.sub(r'\s+', ' ', body).strip()

                # Truncate to keep context window manageable
                max_len = await _get_assistant_setting(db, "body_max_chars", 3000)
                if len(body) > max_len:
                    body = body[:max_len] + f"\n\n... (gekuerzt, {len(body)} Zeichen gesamt)"

                date_str = msg.date.strftime("%d.%m.%Y %H:%M") if msg.date else "unbekannt"
                return (
                    f"**Betreff:** {msg.subject or '(kein Betreff)'}\n"
                    f"**Von:** {msg.from_address}\n"
                    f"**An:** {msg.to_addresses or '?'}\n"
                    f"**Datum:** {date_str}\n"
                    f"**Status:** {'gelesen' if msg.is_read else 'ungelesen'}"
                    f"{', markiert' if msg.is_flagged else ''}"
                    f"{', archiviert' if msg.is_archived else ''}\n\n"
                    f"**Inhalt:**\n{body}"
                )

            elif tool_name == "trigger_digest_run":
                policy_name = args["policy_name"]
                result = await db.execute(
                    select(DigestPolicy).where(DigestPolicy.name.ilike(f"%{policy_name}%"))
                )
                policy = result.scalar_one_or_none()
                if not policy:
                    return f"Keine Policy mit dem Namen '{policy_name}' gefunden."

                from app.services.digest_service import compose_digest
                from datetime import datetime, timezone, timedelta

                override_since = None
                if "since_hours" in args and args["since_hours"]:
                    override_since = datetime.now(timezone.utc) - timedelta(hours=args["since_hours"])

                run = await compose_digest(db, policy, override_since=override_since)
                await db.commit()
                return f"Digest '{policy.name}' ausgefuehrt: Status={run.status}, {run.item_count} Items."

            # --- Podcast Tools ---

            elif tool_name == "list_podcast_feeds":
                result = await db.execute(select(PodcastFeed).order_by(PodcastFeed.created_at))
                feeds = result.scalars().all()
                if not feeds:
                    return "Keine Podcast-Feeds konfiguriert."
                items = []
                for f in feeds:
                    # Count episodes
                    ep_total = await db.scalar(select(func.count(PodcastEpisode.id)).where(PodcastEpisode.feed_id == f.id))
                    ep_done = await db.scalar(select(func.count(PodcastEpisode.id)).where(PodcastEpisode.feed_id == f.id, PodcastEpisode.processing_status == "done"))
                    ep_error = await db.scalar(select(func.count(PodcastEpisode.id)).where(PodcastEpisode.feed_id == f.id, PodcastEpisode.processing_status == "error"))
                    models_info = ""
                    if f.transcription_model or f.summary_model:
                        models_info = f", Transkription: {f.transcription_model or 'global'}, Summary: {f.summary_model or 'global'}"
                    items.append(
                        f"- **{f.title or f.url}** | {'aktiv' if f.enabled else 'inaktiv'} | "
                        f"{ep_done}/{ep_total} fertig"
                        f"{f', {ep_error} Fehler' if ep_error else ''}"
                        f"{models_info} | ID: `{f.id}`"
                    )
                return "\n".join(items)

            elif tool_name == "add_podcast_feed":
                from app.services.podcast_feed_service import fetch_podcast_feed
                feed = PodcastFeed(
                    url=args["url"],
                    title=args.get("title"),
                    auto_process_new=args.get("auto_process_new", True),
                    min_episode_duration_seconds=args.get("min_episode_duration_seconds"),
                    max_episode_duration_seconds=args.get("max_episode_duration_seconds"),
                    enabled=True,
                )
                db.add(feed)
                await db.flush()
                count = await fetch_podcast_feed(db, feed)
                await db.commit()
                await db.refresh(feed)
                return f"Podcast-Feed '{feed.title or feed.url}' hinzugefuegt. {count} Episoden erkannt (nur die neueste wird automatisch verarbeitet)."

            elif tool_name == "update_podcast_feed":
                feed_name = args.pop("feed_name")
                result = await db.execute(
                    select(PodcastFeed).where(PodcastFeed.title.ilike(f"%{feed_name}%"))
                )
                feed = result.scalar_one_or_none()
                if not feed:
                    return f"Kein Feed mit dem Namen '{feed_name}' gefunden."
                changes = []
                for key in ["enabled", "auto_process_new", "transcription_model", "summary_model",
                            "fetch_interval_minutes", "min_episode_duration_seconds",
                            "max_episode_duration_seconds", "language"]:
                    if key in args and args[key] is not None:
                        old_val = getattr(feed, key)
                        setattr(feed, key, args[key])
                        changes.append(f"{key}: {old_val} → {args[key]}")
                await db.commit()
                if not changes:
                    return f"Keine Aenderungen an '{feed.title}' vorgenommen."
                return f"Feed '{feed.title}' aktualisiert:\n" + "\n".join(f"- {c}" for c in changes)

            elif tool_name == "delete_podcast_feed":
                feed_name = args["feed_name"]
                result = await db.execute(
                    select(PodcastFeed).where(PodcastFeed.title.ilike(f"%{feed_name}%"))
                )
                feed = result.scalar_one_or_none()
                if not feed:
                    return f"Kein Feed mit dem Namen '{feed_name}' gefunden."
                title = feed.title or feed.url
                await db.delete(feed)
                await db.commit()
                return f"Feed '{title}' und alle zugehoerigen Episoden geloescht."

            elif tool_name == "list_podcast_episodes":
                from sqlalchemy import or_
                feed_name = args.get("feed_name")
                status = args.get("status")
                search = args.get("search")
                limit = min(args.get("limit", 20), 50)

                query = select(PodcastEpisode).order_by(PodcastEpisode.published_at.desc()).limit(limit)

                if feed_name:
                    feed_result = await db.execute(
                        select(PodcastFeed.id).where(PodcastFeed.title.ilike(f"%{feed_name}%"))
                    )
                    feed_ids = [r[0] for r in feed_result.all()]
                    if not feed_ids:
                        return f"Kein Feed mit dem Namen '{feed_name}' gefunden."
                    query = query.where(PodcastEpisode.feed_id.in_(feed_ids))

                if status:
                    query = query.where(PodcastEpisode.processing_status == status)

                if search:
                    term = f"%{search.lower()}%"
                    query = query.where(
                        or_(
                            PodcastEpisode.title.ilike(term),
                            PodcastEpisode.description.ilike(term),
                        )
                    )

                result = await db.execute(query)
                episodes = result.scalars().all()
                if not episodes:
                    return "Keine Episoden gefunden."

                lines = [f"**{len(episodes)} Episoden:**\n"]
                for ep in episodes:
                    date_str = ep.published_at.strftime("%d.%m.") if ep.published_at else "?"
                    dur = f" ({ep.duration_seconds // 60}min)" if ep.duration_seconds else ""
                    saved = " ⭐" if ep.is_saved else ""
                    lines.append(f"- `{ep.id}` | {date_str} | **{ep.title or 'Ohne Titel'}**{dur} | {ep.processing_status}{saved}")
                return "\n".join(lines)

            elif tool_name == "get_podcast_episode":
                ep_id = args["episode_id"]
                try:
                    episode = await db.get(PodcastEpisode, uuid.UUID(ep_id))
                except (ValueError, AttributeError):
                    return f"Ungueltige Episode-ID: {ep_id}"
                if not episode:
                    return f"Episode mit ID {ep_id} nicht gefunden."

                # Get feed title
                feed = await db.get(PodcastFeed, episode.feed_id)
                feed_title = feed.title if feed else "?"

                # Get active summary
                summary_result = await db.execute(
                    select(PodcastArtifact).where(
                        PodcastArtifact.episode_id == episode.id,
                        PodcastArtifact.artifact_type == "summary",
                        PodcastArtifact.is_active == True,
                    )
                )
                summary = summary_result.scalar_one_or_none()

                # Get active transcript (truncated)
                transcript_result = await db.execute(
                    select(PodcastArtifact).where(
                        PodcastArtifact.episode_id == episode.id,
                        PodcastArtifact.artifact_type == "transcript",
                        PodcastArtifact.is_active == True,
                    )
                )
                transcript = transcript_result.scalar_one_or_none()

                date_str = episode.published_at.strftime("%d.%m.%Y") if episode.published_at else "unbekannt"
                dur = f"{episode.duration_seconds // 60} Minuten" if episode.duration_seconds else "unbekannt"

                text = (
                    f"**{episode.title or 'Ohne Titel'}**\n"
                    f"**Feed:** {feed_title}\n"
                    f"**Datum:** {date_str} | **Dauer:** {dur}\n"
                    f"**Status:** {episode.processing_status} (Discovery: {episode.discovery_status})\n"
                )
                if episode.error_message:
                    text += f"**Fehler:** {episode.error_class}: {episode.error_message}\n"

                if summary:
                    text += f"\n**Zusammenfassung** ({summary.word_count} Woerter, Modell: {summary.model}):\n{summary.content}\n"
                else:
                    text += "\n*Keine Zusammenfassung vorhanden.*\n"

                if transcript:
                    max_len = await _get_assistant_setting(db, "body_max_chars", 3000)
                    t_content = transcript.content or ""
                    if len(t_content) > max_len:
                        t_content = t_content[:max_len] + f"\n\n... (gekuerzt, {transcript.word_count} Woerter gesamt)"
                    text += f"\n**Transkript-Auszug:**\n{t_content}\n"

                return text

            elif tool_name == "process_podcast_episode":
                ep_id = args["episode_id"]
                try:
                    episode = await db.get(PodcastEpisode, uuid.UUID(ep_id))
                except (ValueError, AttributeError):
                    return f"Ungueltige Episode-ID: {ep_id}"
                if not episode:
                    return f"Episode mit ID {ep_id} nicht gefunden."
                if episode.processing_status == "done":
                    return f"Episode '{episode.title}' ist bereits verarbeitet."
                if episode.locked_at is not None:
                    return f"Episode '{episode.title}' wird gerade verarbeitet."

                # Accept if skipped
                if episode.discovery_status == "skipped":
                    episode.discovery_status = "accepted"
                    episode.skipped_reason = None
                    episode.summarize_enabled = True

                episode.processing_status = "pending"
                episode.error_class = None
                episode.error_message = None
                await db.commit()

                # Fire background task
                import asyncio as _asyncio
                from app.api.podcasts import _process_episode_background
                _asyncio.create_task(_process_episode_background(ep_id))

                return f"Verarbeitung von '{episode.title}' gestartet. Laeuft im Hintergrund (Download → Transkription → Zusammenfassung)."

            elif tool_name == "list_podcast_prompts":
                result = await db.execute(select(PodcastPrompt).order_by(PodcastPrompt.created_at))
                prompts = result.scalars().all()
                if not prompts:
                    return "Keine Podcast-Prompts konfiguriert."
                items = []
                for p in prompts:
                    typ = "Chunk-Summary" if p.prompt_type == "map_summary" else "Gesamt-Summary"
                    default = " (Default)" if p.is_default else ""
                    items.append(f"- **{p.name}** | {typ}{default} | v{p.version} | ID: `{p.id}`\n  Auszug: {p.system_prompt[:100]}...")
                return "\n".join(items)

            elif tool_name == "update_podcast_prompt":
                prompt_name = args["prompt_name"]
                result = await db.execute(
                    select(PodcastPrompt).where(PodcastPrompt.name.ilike(f"%{prompt_name}%"))
                )
                prompt = result.scalar_one_or_none()
                if not prompt:
                    return f"Kein Prompt mit dem Namen '{prompt_name}' gefunden."
                old_version = prompt.version
                if args.get("system_prompt") and args["system_prompt"] != prompt.system_prompt:
                    prompt.system_prompt = args["system_prompt"]
                    prompt.version += 1
                if args.get("name"):
                    prompt.name = args["name"]
                if args.get("description"):
                    prompt.description = args["description"]
                await db.commit()
                return f"Prompt '{prompt.name}' aktualisiert (v{old_version} → v{prompt.version})."

            elif tool_name == "get_podcast_queue":
                from datetime import datetime, timezone
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

                status_counts = {}
                result = await db.execute(
                    select(PodcastEpisode.processing_status, func.count(PodcastEpisode.id))
                    .group_by(PodcastEpisode.processing_status)
                )
                for status, count in result.all():
                    status_counts[status] = count

                done_today = await db.scalar(
                    select(func.count(PodcastEpisode.id))
                    .where(PodcastEpisode.processing_status == "done", PodcastEpisode.last_processed_at >= today_start)
                ) or 0

                total = sum(status_counts.values())
                lines = [
                    f"**Podcast-Pipeline Status:**",
                    f"- Pending: {status_counts.get('pending', 0)}",
                    f"- Downloading: {status_counts.get('downloading', 0)}",
                    f"- Transcribing: {status_counts.get('transcribing', 0)}",
                    f"- Summarizing: {status_counts.get('summarizing_chunks', 0) + status_counts.get('reducing', 0)}",
                    f"- Fehler: {status_counts.get('error', 0)}",
                    f"- Fertig: {status_counts.get('done', 0)}",
                    f"- Uebersprungen: {status_counts.get('skipped', 0)}",
                    f"- Heute fertig: {done_today}",
                    f"- Gesamt: {total}",
                ]
                return "\n".join(lines)

            elif tool_name == "update_podcast_settings":
                changes = []
                for key in ["transcription_model", "summary_model"]:
                    if key in args and args[key] is not None:
                        db_key = f"podcast_{key}"
                        result = await db.execute(select(AppSetting).where(AppSetting.key == db_key))
                        setting = result.scalar_one_or_none()
                        if setting:
                            old = setting.value
                            setting.value = args[key]
                        else:
                            old = "(nicht gesetzt)"
                            db.add(AppSetting(key=db_key, value=args[key]))
                        changes.append(f"{key}: {old} → {args[key]}")
                await db.commit()
                if not changes:
                    return "Keine Aenderungen vorgenommen."
                return "Globale Podcast-Einstellungen aktualisiert:\n" + "\n".join(f"- {c}" for c in changes)

            else:
                return f"Unbekanntes Tool: {tool_name}"
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            return f"Fehler bei {tool_name}: {str(e)}"


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AssistantConversation)
        .order_by(AssistantConversation.updated_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AssistantConversation)
        .where(AssistantConversation.id == conversation_id)
        .options(selectinload(AssistantConversation.messages))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")
    return conv


@router.delete("/conversations/{conversation_id}", response_model=MessageResponse)
async def delete_conversation(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conv = await db.get(AssistantConversation, conversation_id)
    if not conv:
        raise NotFoundError("Conversation not found")
    await db.delete(conv)
    return MessageResponse(message="Conversation deleted")


@router.post("/chat")
async def chat(data: MessageSend, db: AsyncSession = Depends(get_db)):
    """Send a message and get a streaming SSE response with tool calling support."""

    # Get or create conversation
    if data.conversation_id:
        result = await db.execute(
            select(AssistantConversation)
            .where(AssistantConversation.id == data.conversation_id)
            .options(selectinload(AssistantConversation.messages))
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise NotFoundError("Conversation not found")
    else:
        conv = AssistantConversation(title=None, user_id="default")
        db.add(conv)
        await db.flush()
        await db.refresh(conv)

    # Save user message
    user_msg = AssistantMessage(
        conversation_id=conv.id,
        role="user",
        content=data.content,
    )
    db.add(user_msg)
    await db.flush()

    # Build message history for LLM
    result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conv.id)
        .order_by(AssistantMessage.created_at)
    )
    all_messages = result.scalars().all()

    llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in all_messages:
        llm_messages.append({"role": msg.role, "content": msg.content})

    # Generate title from first message
    if not conv.title and len(all_messages) == 1:
        title = data.content[:80]
        if len(data.content) > 80:
            title = title.rsplit(" ", 1)[0] + "..."
        conv.title = title

    await db.commit()

    conv_id = conv.id

    async def generate():
        """SSE stream generator with tool calling loop."""
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': str(conv_id)})}\n\n"

        provider = get_llm_provider()
        messages = list(llm_messages)
        full_content = ""

        try:
            # Tool-call loop: allow up to 5 rounds of tool calls
            for _ in range(5):
                response = await provider.client.chat.completions.create(
                    model=provider.default_model,
                    messages=messages,
                    tools=TOOLS,
                    temperature=0.5,
                    max_tokens=4000,
                )

                choice = response.choices[0]

                if not choice.message.tool_calls:
                    # No more tool calls — send the text response
                    full_content = choice.message.content or ""
                    chunk_size = 20
                    for i in range(0, len(full_content), chunk_size):
                        chunk = full_content[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                    break

                # Process tool calls
                messages.append(choice.message.model_dump())

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    fn_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}

                    yield f"data: {json.dumps({'type': 'tool', 'name': fn_name})}\n\n"

                    tool_result = await execute_tool(fn_name, fn_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    })
                # Loop continues — LLM gets tool results and can call more tools or respond

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.error(f"Chat error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        # Save assistant message
        async with async_session() as save_db:
            assistant_msg = AssistantMessage(
                conversation_id=conv_id,
                role="assistant",
                content=full_content,
                token_count=len(full_content.split()),
            )
            save_db.add(assistant_msg)
            await save_db.commit()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

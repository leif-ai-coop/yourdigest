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
from app.models.forwarding import ForwardingPolicy
from app.schemas.assistant import MessageSend, ConversationOut, ConversationDetail
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """Du bist der CuraOS Mail Assistant — ein hilfsbereiter, deutschsprachiger Assistent.
Du hilfst dem Benutzer bei der Verwaltung seiner E-Mails, Digests, RSS-Feeds und Weiterleitungen.
Antworte praezise und freundlich. Halte deine Antworten kurz und relevant.

Wenn der Benutzer nach E-Mail-Inhalten fragt, gehe zweistufig vor:
1. Nutze browse_recent_mails um einen Ueberblick (Absender + Betreff) zu bekommen
2. Nutze read_mail nur fuer die relevanten Mails, deren Inhalt du wirklich brauchst

Wenn du eine Aktion ausfuehren sollst (z.B. Digest anlegen), nutze die verfuegbaren Tools.
Frage nach fehlenden Informationen bevor du ein Tool aufrufst."""

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

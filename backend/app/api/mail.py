import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func, distinct, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, defer

from app.database import get_db
from app.models.mail import MailAccount, MailMessage
from app.schemas.mail import (
    MailAccountCreate, MailAccountUpdate, MailAccountOut,
    MailMessageOut, MailMessageDetail, MailActionRequest,
)
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.connector_service import encrypt_value, decrypt_value
import json

router = APIRouter()

import re
import bleach

ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "tr", "td", "th", "caption", "colgroup", "col",
    "img", "figure", "figcaption", "center", "font",
    "ul", "ol", "li", "dl", "dt", "dd",
    "pre", "code", "blockquote", "section", "article", "header", "footer", "nav", "main",
    "sup", "sub", "mark", "del", "ins", "small", "big",
]
ALLOWED_ATTRS = {
    "*": ["class", "id", "style", "dir", "lang", "align", "valign", "width", "height", "bgcolor", "color"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan", "width", "height", "align", "valign", "bgcolor"],
    "th": ["colspan", "rowspan", "width", "height", "align", "valign", "bgcolor"],
    "table": ["border", "cellpadding", "cellspacing", "width"],
    "font": ["color", "size", "face"],
    "col": ["span", "width"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "cid"]


def _sanitize_html(html: str | None) -> str | None:
    """Sanitize HTML to prevent XSS while keeping email formatting."""
    if not html:
        return html
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, protocols=ALLOWED_PROTOCOLS, strip=True)


def _extract_unsubscribe_url(raw_headers: str | None) -> str | None:
    """Extract HTTP unsubscribe URL from List-Unsubscribe header."""
    if not raw_headers:
        return None
    for line in raw_headers.splitlines():
        if line.lower().startswith("list-unsubscribe:"):
            # Find HTTP(S) URLs in angle brackets or bare
            urls = re.findall(r'<(https?://[^>]+)>', line)
            if urls:
                return urls[0]
            urls = re.findall(r'(https?://\S+)', line)
            if urls:
                return urls[0]
    return None


_UNSUB_KEYWORDS = ("unsubscribe", "abmelden", "abbestellen", "opt-out", "optout", "newsletter")


def _unsubscribe_from_links(links) -> str | None:
    """Fallback: derive an unsubscribe URL from the mail's body links.

    Some senders only provide an in-body unsubscribe link (no List-Unsubscribe
    header). Mirrors the keyword match the digest used to do.
    """
    for link in links or []:
        text = (link.text or "").lower()
        url = (link.url or "").lower()
        if any(kw in text or kw in url for kw in _UNSUB_KEYWORDS):
            return link.url
    return None


def _add_unsubscribe(msg) -> dict:
    """Convert a MailMessage ORM object to dict with unsubscribe_url."""
    data = MailMessageOut.model_validate(msg).model_dump()
    data["unsubscribe_url"] = _extract_unsubscribe_url(msg.raw_headers)
    return data


@router.get("/accounts", response_model=list[MailAccountOut])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MailAccount))
    return result.scalars().all()


@router.post("/accounts", response_model=MailAccountOut, status_code=201)
async def create_account(data: MailAccountCreate, db: AsyncSession = Depends(get_db)):
    account = MailAccount(
        email=data.email,
        display_name=data.display_name,
        imap_host=data.imap_host,
        imap_port=data.imap_port,
        imap_use_ssl=data.imap_use_ssl,
        smtp_host=data.smtp_host,
        smtp_port=data.smtp_port,
        smtp_use_tls=data.smtp_use_tls,
        username=data.username,
        password_encrypted=encrypt_value(data.password),
        enabled=data.enabled,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


@router.get("/accounts/{account_id}", response_model=MailAccountOut)
async def get_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    return account


@router.patch("/accounts/{account_id}", response_model=MailAccountOut)
async def update_account(account_id: uuid.UUID, data: MailAccountUpdate, db: AsyncSession = Depends(get_db)):
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "password" and value is not None:
            account.password_encrypted = encrypt_value(value)
        else:
            setattr(account, field, value)
    await db.flush()
    await db.refresh(account)
    return account


@router.delete("/accounts/{account_id}", response_model=MessageResponse)
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    await db.delete(account)
    return MessageResponse(message="Account deleted")


@router.post("/accounts/{account_id}/test", response_model=MessageResponse)
async def test_connection(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    from app.services.imap_client import test_imap_connection
    password = decrypt_value(account.password_encrypted)
    result = await test_imap_connection(
        host=account.imap_host,
        port=account.imap_port,
        username=account.username,
        password=password,
        use_ssl=account.imap_use_ssl,
    )
    return MessageResponse(message=result)


@router.post("/accounts/{account_id}/sync", response_model=MessageResponse)
async def trigger_sync(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    from app.services.mail_service import sync_account
    count = await sync_account(db, account)
    return MessageResponse(message=f"Synced {count} new messages")


@router.get("/accounts/{account_id}/folders")
async def list_folders(account_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List available IMAP folders for an account."""
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    from app.services.imap_client import list_imap_folders
    password = decrypt_value(account.password_encrypted)
    folders = list_imap_folders(
        host=account.imap_host, port=account.imap_port,
        username=account.username, password=password, use_ssl=account.imap_use_ssl,
    )
    sync_folders = json.loads(account.sync_folders or '["INBOX"]')
    return {"available": folders, "synced": sync_folders}


class SyncFoldersUpdate(BaseModel):
    folders: list[str]


@router.put("/accounts/{account_id}/folders", response_model=MessageResponse)
async def set_sync_folders(account_id: uuid.UUID, data: SyncFoldersUpdate, db: AsyncSession = Depends(get_db)):
    """Set which IMAP folders to sync for an account."""
    account = await db.get(MailAccount, account_id)
    if not account:
        raise NotFoundError("Mail account not found")
    account.sync_folders = json.dumps(data.folders)
    return MessageResponse(message=f"Sync folders updated: {', '.join(data.folders)}")


@router.get("/folders")
async def get_synced_folders(db: AsyncSession = Depends(get_db)):
    """Get all distinct folders that have synced messages."""
    result = await db.execute(
        select(MailMessage.folder, func.count(MailMessage.id).label("count"))
        .group_by(MailMessage.folder)
        .order_by(MailMessage.folder)
    )
    return [{"folder": row.folder, "count": row.count} for row in result.all()]


@router.get("/unsubscribes")
async def list_unsubscribes(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated unsubscribe links from the last `days` of mail.

    One row per sender (grouped by email address), sorted by how many mails
    that sender sent in the window (descending). Only senders that actually
    expose an unsubscribe link (List-Unsubscribe header, or an in-body
    unsubscribe link as fallback) are returned. This replaces the raw
    unsubscribe URL dump that used to sit in the digest mail body — those
    blacklisted URLs made Strato refuse the whole digest (550 B-URL).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # Defer the big body blobs; we only need headers (for List-Unsubscribe)
    # and the body links (fallback). raw_headers stays loaded.
    result = await db.execute(
        select(MailMessage)
        .options(
            defer(MailMessage.body_text),
            defer(MailMessage.body_html),
            selectinload(MailMessage.links),
        )
        .where(func.coalesce(MailMessage.date, MailMessage.created_at) >= since)
    )
    messages = result.scalars().all()

    agg: dict[str, dict] = {}
    for msg in messages:
        name, addr = parseaddr(msg.from_address or "")
        key = (addr or msg.from_address or "").lower()
        if not key:
            continue
        entry = agg.get(key)
        if entry is None:
            entry = {
                "from_address": addr or msg.from_address,
                "sender": name or addr or msg.from_address,
                "count": 0,
                "unsubscribe_url": None,
                "last_seen": None,
                "_url_dt": None,
            }
            agg[key] = entry
        entry["count"] += 1
        # Track the display name/date from the most recent mail.
        msg_dt = msg.date or msg.created_at
        if msg_dt is not None and (entry["last_seen"] is None or msg_dt > entry["last_seen"]):
            entry["last_seen"] = msg_dt
            if name:
                entry["sender"] = name
        # Prefer the unsubscribe URL from the most recent mail that has one.
        url = _extract_unsubscribe_url(msg.raw_headers) or _unsubscribe_from_links(msg.links)
        if url and (entry["_url_dt"] is None or (msg_dt is not None and msg_dt >= entry["_url_dt"])):
            entry["unsubscribe_url"] = url
            entry["_url_dt"] = msg_dt

    rows = [
        {
            "from_address": e["from_address"],
            "sender": e["sender"],
            "count": e["count"],
            "unsubscribe_url": e["unsubscribe_url"],
            "last_seen": e["last_seen"].isoformat() if e["last_seen"] else None,
        }
        for e in agg.values()
        if e["unsubscribe_url"]
    ]
    rows.sort(key=lambda r: (r["count"], r["last_seen"] or ""), reverse=True)
    return rows


@router.get("/messages")
async def list_messages(
    account_id: uuid.UUID | None = None,
    folder: str | None = None,
    is_read: bool | None = None,
    is_archived: bool | None = None,
    is_flagged: bool | None = None,
    category: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # The list view never renders the bodies — defer those heavy columns so a
    # 50-row page doesn't pull dozens of 50-500 KB HTML blobs into RAM.
    # raw_headers is NOT deferred: _add_unsubscribe() reads it (deferred access
    # would trigger a lazy load and fail in the async session).
    query = (
        select(MailMessage)
        .options(
            defer(MailMessage.body_text),
            defer(MailMessage.body_html),
        )
        .order_by(desc(MailMessage.date), desc(MailMessage.id))
    )
    if account_id:
        query = query.where(MailMessage.account_id == account_id)
    if folder:
        query = query.where(MailMessage.folder == folder)
    if is_read is not None:
        query = query.where(MailMessage.is_read == is_read)
    if is_archived is not None:
        query = query.where(MailMessage.is_archived == is_archived)
    if is_flagged is not None:
        query = query.where(MailMessage.is_flagged == is_flagged)
    if category:
        from app.models.classification import MailClassification
        query = query.where(MailMessage.id.in_(
            select(MailClassification.message_id).where(MailClassification.category == category)
        ))
    if q and q.strip():
        # Multi-word: each word must appear in at least one searched field
        # (AND over words, OR over fields) — same shape as the podcast search.
        # body_text stays deferred in the SELECT; referencing it in WHERE does
        # not load the blob into RAM. ILIKE '%term%' is accelerated by the
        # pg_trgm GIN indexes on these columns (>= 3-char terms).
        for word in q.split():
            like = f"%{word}%"
            query = query.where(or_(
                MailMessage.subject.ilike(like),
                MailMessage.from_address.ilike(like),
                MailMessage.to_addresses.ilike(like),
                MailMessage.body_text.ilike(like),
            ))
    if since is not None:
        # coalesce so mails without a parsed Date header (date NULL) aren't
        # silently dropped from the search window.
        query = query.where(
            func.coalesce(MailMessage.date, MailMessage.created_at) >= since
        )
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return [_add_unsubscribe(msg) for msg in result.scalars().all()]


@router.get("/messages/{message_id}")
async def get_message(message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MailMessage)
        .where(MailMessage.id == message_id)
        .options(
            selectinload(MailMessage.attachments),
            selectinload(MailMessage.links),
            selectinload(MailMessage.classifications),
        )
    )
    message = result.scalar_one_or_none()
    if not message:
        raise NotFoundError("Message not found")
    data = MailMessageDetail.model_validate(message).model_dump()
    data["unsubscribe_url"] = _extract_unsubscribe_url(message.raw_headers)
    if data.get("body_html"):
        data["body_html"] = _sanitize_html(data["body_html"])
    return data


@router.post("/messages/action", response_model=MessageResponse)
async def message_action(data: MailActionRequest, db: AsyncSession = Depends(get_db)):
    for mid in data.message_ids:
        msg = await db.get(MailMessage, mid)
        if not msg:
            continue
        match data.action:
            case "read":
                msg.is_read = True
            case "unread":
                msg.is_read = False
            case "flag":
                msg.is_flagged = True
            case "unflag":
                msg.is_flagged = False
            case "archive":
                msg.is_archived = True
            case "unarchive":
                msg.is_archived = False
            case "delete":
                await db.delete(msg)
    return MessageResponse(message=f"Applied '{data.action}' to {len(data.message_ids)} messages")


class SendReplyRequest(BaseModel):
    message_id: uuid.UUID
    to: str = Field(max_length=500)
    subject: str = Field(max_length=1000)
    body: str = Field(max_length=100000)


@router.post("/send-reply", response_model=MessageResponse)
async def send_reply(data: SendReplyRequest, db: AsyncSession = Depends(get_db)):
    """Send a reply to an email message via SMTP."""
    from app.services.smtp_client import send_email

    message = await db.get(MailMessage, data.message_id)
    if not message:
        raise NotFoundError("Message not found")

    account = await db.get(MailAccount, message.account_id)
    if not account or not account.smtp_host:
        raise NotFoundError("No SMTP configuration found for this account")

    password = decrypt_value(account.password_encrypted)

    await send_email(
        host=account.smtp_host,
        port=account.smtp_port or 587,
        username=account.username,
        password=password,
        use_tls=account.smtp_use_tls if account.smtp_use_tls is not None else True,
        from_addr=account.email,
        to_addr=data.to,
        subject=data.subject,
        body_text=data.body,
        in_reply_to=message.message_id,
        references=message.message_id,
    )

    return MessageResponse(message=f"Reply sent to {data.to}")

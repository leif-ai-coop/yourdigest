import uuid
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


@router.get("/messages")
async def list_messages(
    account_id: uuid.UUID | None = None,
    folder: str | None = None,
    is_read: bool | None = None,
    is_archived: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(MailMessage).order_by(desc(MailMessage.date))
    if account_id:
        query = query.where(MailMessage.account_id == account_id)
    if folder:
        query = query.where(MailMessage.folder == folder)
    if is_read is not None:
        query = query.where(MailMessage.is_read == is_read)
    if is_archived is not None:
        query = query.where(MailMessage.is_archived == is_archived)
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

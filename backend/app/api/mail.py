import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, func
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

router = APIRouter()


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


@router.get("/messages", response_model=list[MailMessageOut])
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
    return result.scalars().all()


@router.get("/messages/{message_id}", response_model=MailMessageDetail)
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
    return message


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
    return MessageResponse(message=f"Applied '{data.action}' to {len(data.message_ids)} messages")

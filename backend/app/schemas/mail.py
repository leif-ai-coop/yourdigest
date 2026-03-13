import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class MailAccountCreate(BaseModel):
    email: str
    display_name: str | None = None
    imap_host: str
    imap_port: int = 993
    imap_use_ssl: bool = True
    smtp_host: str
    smtp_port: int = 587
    smtp_use_tls: bool = True
    username: str
    password: str
    enabled: bool = True


class MailAccountUpdate(BaseModel):
    display_name: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool | None = None


class MailAccountOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    username: str
    enabled: bool
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MailAttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str | None
    content_type: str | None
    size_bytes: int | None

    model_config = {"from_attributes": True}


class MailLinkOut(BaseModel):
    id: uuid.UUID
    url: str
    text: str | None
    domain: str | None

    model_config = {"from_attributes": True}


class ClassificationBrief(BaseModel):
    category: str
    confidence: float
    priority: int
    summary: str | None
    action_required: bool

    model_config = {"from_attributes": True}


class MailMessageOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    message_id: str | None
    subject: str | None
    from_address: str
    to_addresses: str | None
    cc_addresses: str | None
    date: datetime | None
    is_read: bool
    is_flagged: bool
    is_archived: bool
    folder: str
    size_bytes: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MailMessageDetail(MailMessageOut):
    body_text: str | None
    body_html: str | None
    attachments: list[MailAttachmentOut] = []
    links: list[MailLinkOut] = []
    classifications: list[ClassificationBrief] = []


class MailActionRequest(BaseModel):
    action: str  # read, unread, flag, unflag, archive, unarchive
    message_ids: list[uuid.UUID]

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, Text, Integer, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, TimestampMixin


class MailAccount(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "mail_account"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=True)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_uid: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MailMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "mail_message"
    __table_args__ = (
        Index("ix_mail_message_account_uid", "account_id", "uid", unique=True),
        Index("ix_mail_message_date", "date"),
        Index("ix_mail_message_is_read", "is_read"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mail_account.id"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(500), nullable=True)
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=True)
    from_address: Mapped[str] = mapped_column(String(500), nullable=False)
    to_addresses: Mapped[str] = mapped_column(Text, nullable=True)
    cc_addresses: Mapped[str] = mapped_column(Text, nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    folder: Mapped[str] = mapped_column(String(200), default="INBOX")
    raw_headers: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    attachments: Mapped[list["MailAttachment"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    links: Mapped[list["MailLink"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    classifications: Mapped[list["MailClassification"]] = relationship(back_populates="message", cascade="all, delete-orphan")

    account: Mapped["MailAccount"] = relationship()


class MailAttachment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "mail_attachment"

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mail_message.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    message: Mapped["MailMessage"] = relationship(back_populates="attachments")


class MailLink(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "mail_link"

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mail_message.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    message: Mapped["MailMessage"] = relationship(back_populates="links")

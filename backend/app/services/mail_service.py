import json
import logging
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailAccount, MailMessage, MailAttachment, MailLink
from app.services.imap_client import fetch_new_messages
from app.services.connector_service import decrypt_value

logger = logging.getLogger(__name__)


def extract_links(html: str | None) -> list[dict]:
    """Extract links from HTML body."""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        url = a["href"].strip()
        if url in seen or url.startswith("mailto:") or url.startswith("#"):
            continue
        seen.add(url)
        domain = None
        try:
            domain = urlparse(url).netloc
        except Exception:
            pass
        links.append({"url": url, "text": a.get_text(strip=True)[:200], "domain": domain})
    return links


def _get_sync_folders(account: MailAccount) -> list[str]:
    """Get list of folders to sync for an account."""
    try:
        folders = json.loads(account.sync_folders or '["INBOX"]')
        if isinstance(folders, list) and folders:
            return folders
    except (json.JSONDecodeError, TypeError):
        pass
    return ["INBOX"]


async def _get_last_uid(db: AsyncSession, account_id, folder: str) -> int:
    """Get the highest synced UID for a specific folder."""
    result = await db.scalar(
        select(func.max(MailMessage.uid)).where(
            MailMessage.account_id == account_id,
            MailMessage.folder == folder,
        )
    )
    return result or 0


async def _sync_folder(db: AsyncSession, account: MailAccount, password: str, folder: str) -> int:
    """Sync new messages from a specific IMAP folder. Returns count."""
    last_uid = await _get_last_uid(db, account.id, folder)

    messages = fetch_new_messages(
        host=account.imap_host,
        port=account.imap_port,
        username=account.username,
        password=password,
        use_ssl=account.imap_use_ssl,
        last_uid=last_uid,
        folder=folder,
    )

    count = 0
    for uid, parsed in messages:
        # Skip if already exists
        exists = await db.execute(
            select(MailMessage.id).where(
                MailMessage.account_id == account.id,
                MailMessage.folder == folder,
                MailMessage.uid == uid,
            )
        )
        if exists.scalar_one_or_none():
            continue

        msg = MailMessage(
            account_id=account.id,
            uid=uid,
            message_id=parsed.get("message_id"),
            subject=parsed.get("subject"),
            from_address=parsed.get("from_address", ""),
            to_addresses=parsed.get("to_addresses"),
            cc_addresses=parsed.get("cc_addresses"),
            date=parsed.get("date"),
            body_text=parsed.get("body_text"),
            body_html=parsed.get("body_html"),
            is_read=parsed.get("is_read", False),
            is_flagged=parsed.get("is_flagged", False),
            folder=folder,
            raw_headers=parsed.get("raw_headers"),
            size_bytes=parsed.get("size_bytes"),
        )
        db.add(msg)
        await db.flush()

        # Add attachments
        for att_data in parsed.get("attachments", []):
            att = MailAttachment(
                message_id=msg.id,
                filename=att_data.get("filename"),
                content_type=att_data.get("content_type"),
                size_bytes=att_data.get("size_bytes"),
                content_id=att_data.get("content_id"),
            )
            db.add(att)

        # Extract and add links
        for link_data in extract_links(parsed.get("body_html")):
            link = MailLink(
                message_id=msg.id,
                url=link_data["url"],
                text=link_data.get("text"),
                domain=link_data.get("domain"),
            )
            db.add(link)

        count += 1

    return count


async def sync_account(db: AsyncSession, account: MailAccount) -> int:
    """Sync new messages from all configured folders. Returns total count."""
    password = decrypt_value(account.password_encrypted)
    folders = _get_sync_folders(account)

    total = 0
    for folder in folders:
        try:
            count = await _sync_folder(db, account, password, folder)
            total += count
            if count > 0:
                logger.info(f"Synced {count} messages from {folder} for {account.email}")
        except Exception as e:
            logger.error(f"Error syncing folder {folder} for {account.email}: {e}")

    from datetime import datetime, timezone
    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = None

    logger.info(f"Synced {total} total messages for {account.email} ({len(folders)} folders)")
    return total

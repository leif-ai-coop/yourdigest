import logging
from urllib.parse import urlparse
from bs4 import BeautifulSoup
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


async def sync_account(db: AsyncSession, account: MailAccount) -> int:
    """Sync new messages from an IMAP account. Returns count of new messages."""
    password = decrypt_value(account.password_encrypted)

    messages = fetch_new_messages(
        host=account.imap_host,
        port=account.imap_port,
        username=account.username,
        password=password,
        use_ssl=account.imap_use_ssl,
        last_uid=account.last_sync_uid or 0,
    )

    count = 0
    max_uid = account.last_sync_uid or 0

    for uid, parsed in messages:
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
            folder="INBOX",
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

        if uid > max_uid:
            max_uid = uid
        count += 1

    if max_uid > (account.last_sync_uid or 0):
        account.last_sync_uid = max_uid
        from datetime import datetime, timezone
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_error = None

    logger.info(f"Synced {count} messages for {account.email}")
    return count

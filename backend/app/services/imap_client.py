import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def test_imap_connection(host: str, port: int, username: str, password: str, use_ssl: bool = True) -> str:
    """Test IMAP connection. Returns success message or raises."""
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)
        conn.login(username, password)
        conn.select("INBOX")
        status, data = conn.status("INBOX", "(MESSAGES)")
        conn.logout()
        return f"Connection successful. {data[0].decode()}"
    except Exception as e:
        raise RuntimeError(f"IMAP connection failed: {e}")


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def parse_email_message(raw_bytes: bytes) -> dict:
    """Parse raw email bytes into a structured dict."""
    msg = email.message_from_bytes(raw_bytes)

    subject = decode_header_value(msg.get("Subject"))
    from_addr = decode_header_value(msg.get("From", ""))
    to_addr = decode_header_value(msg.get("To", ""))
    cc_addr = decode_header_value(msg.get("Cc", ""))
    message_id = msg.get("Message-ID", "")

    date_str = msg.get("Date", "")
    date = None
    if date_str:
        try:
            date = email.utils.parsedate_to_datetime(date_str)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    body_text = ""
    body_html = ""
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                attachments.append({
                    "filename": part.get_filename(),
                    "content_type": content_type,
                    "size_bytes": len(part.get_payload(decode=True) or b""),
                    "content_id": part.get("Content-ID"),
                })
                continue

            if content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")
            elif content_type == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_html = payload.decode(charset, errors="replace")
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                body_html = text
            else:
                body_text = text

    raw_headers = ""
    for key in ["From", "To", "Cc", "Subject", "Date", "Message-ID", "Reply-To", "List-Unsubscribe"]:
        val = msg.get(key)
        if val:
            raw_headers += f"{key}: {val}\n"

    return {
        "message_id": message_id,
        "subject": subject,
        "from_address": from_addr,
        "to_addresses": to_addr,
        "cc_addresses": cc_addr,
        "date": date,
        "body_text": body_text,
        "body_html": body_html,
        "raw_headers": raw_headers,
        "attachments": attachments,
        "size_bytes": len(raw_bytes),
    }


def fetch_new_messages(host: str, port: int, username: str, password: str, use_ssl: bool, last_uid: int = 0) -> list[tuple[int, dict]]:
    """Fetch messages with UID > last_uid. Returns list of (uid, parsed_message)."""
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)
        conn.login(username, password)
        conn.select("INBOX")

        # Search for messages with UID > last_uid
        if last_uid > 0:
            status, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
        else:
            status, data = conn.uid("search", None, "ALL")

        if status != "OK" or not data[0]:
            conn.logout()
            return []

        uids = data[0].split()
        messages = []

        for uid_bytes in uids:
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue
            status, msg_data = conn.uid("fetch", uid_bytes, "(RFC822 FLAGS)")
            if status != "OK" or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            flags_str = msg_data[0][0].decode() if msg_data[0][0] else ""
            parsed = parse_email_message(raw_email)
            parsed["is_read"] = "\\Seen" in flags_str
            parsed["is_flagged"] = "\\Flagged" in flags_str
            messages.append((uid, parsed))

        conn.logout()
        return messages
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise

import imaplib
import email
from email.header import decode_header
import html

IMAP_HOST = "imap.gmx.com"
IMAP_PORT = 993


def decode_str(s):
    """Decode encoded email header string."""
    if s is None:
        return ""
    parts = decode_header(s)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def get_body(msg):
    """Extract plain text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                charset = part.get_content_charset() or "utf-8"
                body = part.get_payload(decode=True).decode(charset, errors="replace")
                break
            elif content_type == "text/html" and "attachment" not in disposition and not body:
                charset = part.get_content_charset() or "utf-8"
                raw_html = part.get_payload(decode=True).decode(charset, errors="replace")
                body = html.unescape(raw_html)
    else:
        charset = msg.get_content_charset() or "utf-8"
        body = msg.get_payload(decode=True).decode(charset, errors="replace")
    return body.strip()


def read_emails(
    imap_host: str,
    email_address: str,
    password: str,
    mailbox: str = "INBOX",
    limit: int = 10,
    imap_port: int = 993,
    mark_seen: bool = False,
):
    """
    Connect to an IMAP server and read emails.

    Args:
        imap_host:     IMAP server hostname (e.g. 'imap.gmail.com')
        email_address: Full email address used to log in
        password:      Account password or app-specific password
        mailbox:       Mailbox/folder to read from (default 'INBOX')
        limit:         Maximum number of recent emails to fetch
        imap_port:     IMAP SSL port (default 993)
        mark_seen:     Whether to mark fetched emails as seen (default False)

    Returns:
        List of dicts with keys: id, subject, from, date, body
    """
    results = []

    with imaplib.IMAP4_SSL(imap_host, imap_port) as imap:
        imap.login(email_address, password)
        imap.select(mailbox, readonly=not mark_seen)

        status, data = imap.search(None, "ALL")
        if status != "OK":
            return results

        message_ids = data[0].split()
        # Take the most recent `limit` emails
        recent_ids = message_ids[-limit:][::-1]

        for msg_id in recent_ids:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            results.append({
                "id":      msg_id.decode(),
                "subject": decode_str(msg.get("Subject")),
                "from":    decode_str(msg.get("From")),
                "date":    decode_str(msg.get("Date")),
                "body":    get_body(msg),
            })

    return results


def imap_get_count(email_address: str, password: str) -> int:
    """Return the total number of messages in INBOX."""
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(email_address, password)
            imap.select("INBOX", readonly=True)
            status, data = imap.search(None, "ALL")
            if status == "OK" and data[0]:
                return len(data[0].split())
    except Exception:
        pass
    return 0


def imap_get_recent_mails(email_address: str, password: str, limit: int = 30) -> list:
    """
    Return up to `limit` most-recent messages as dicts with keys:
        sender, subject, body
    """
    return [
        {"sender": m["from"], "subject": m["subject"], "body": m["body"]}
        for m in read_emails(IMAP_HOST, email_address, password, limit=limit)
    ]


# ── Example usage ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    IMAP_HOST = "imap.gmx.com"
    EMAIL     = "ricktiw_paddsdrsels@gmx.com"
    PASSWORD  = "tYZ65djDssdfdsgHY2"

    emails = read_emails(
        imap_host=IMAP_HOST,
        email_address=EMAIL,
        password=PASSWORD,
        limit=5,
    )

    for i, em in enumerate(emails, 1):
        print(f"\n{'='*50}")
        print(f"#{i}  ID      : {em['id']}")
        print(f"    Subject : {em['subject']}")
        print(f"    From    : {em['from']}")
        print(f"    Date    : {em['date']}")
        print(f"    Body    :\n{em['body'][:500]}")

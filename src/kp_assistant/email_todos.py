from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import base64
from email import policy
from email.message import EmailMessage as ParsedEmailMessage
from email.parser import BytesParser
import argparse
import html
import imaplib
import json
import os
from pathlib import Path
import re
import shlex
from typing import Any, Callable, Iterable, Protocol

from kp_assistant.assistant import GeminiAssistant
from kp_assistant.memory import MemoryStore


DEFAULT_EMAIL_CONFIG_PATH = Path.home() / ".kp_assistant" / "email_accounts.json"
MAX_BODY_CHARS = 3000
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class EmailTodoError(RuntimeError):
    """Raised when email todo extraction cannot complete."""


class ImapConnection(Protocol):
    def login(self, user: str, password: str) -> object: ...

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> object: ...

    def search(self, charset: str | None, *criteria: str) -> tuple[str, list[bytes]]: ...

    def fetch(self, message_set: bytes | str, message_parts: str) -> tuple[str, list]: ...

    def close(self) -> object: ...

    def logout(self) -> object: ...


@dataclass(frozen=True)
class EmailAccount:
    type: str
    name: str
    host: str = ""
    username: str = ""
    password_env: str = ""
    client_secret_file: Path | None = None
    token_file: Path | None = None
    query: str = "in:inbox"
    port: int = 993
    mailbox: str = "INBOX"

    @classmethod
    def from_dict(cls, value: dict) -> "EmailAccount":
        account_type = str(value.get("type", "imap"))
        if account_type == "imap":
            return cls._imap_from_dict(value)
        if account_type == "gmail_oauth":
            return cls._gmail_oauth_from_dict(value)
        raise EmailTodoError(f"unknown email account type: {account_type}")

    @classmethod
    def _imap_from_dict(cls, value: dict) -> "EmailAccount":
        required = ["name", "host", "username", "password_env"]
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise EmailTodoError(
                f"email account is missing required field(s): {', '.join(missing)}"
            )
        return cls(
            type="imap",
            name=str(value["name"]),
            host=str(value["host"]),
            username=str(value["username"]),
            password_env=str(value["password_env"]),
            port=int(value.get("port", 993)),
            mailbox=str(value.get("mailbox", "INBOX")),
        )

    @classmethod
    def _gmail_oauth_from_dict(cls, value: dict) -> "EmailAccount":
        required = ["name", "client_secret_file", "token_file"]
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise EmailTodoError(
                f"gmail_oauth account is missing required field(s): {', '.join(missing)}"
            )
        return cls(
            type="gmail_oauth",
            name=str(value["name"]),
            client_secret_file=Path(str(value["client_secret_file"])).expanduser(),
            token_file=Path(str(value["token_file"])).expanduser(),
            query=str(value.get("query", "in:inbox")),
        )

    def password(self) -> str:
        password = os.getenv(self.password_env)
        if not password:
            raise EmailTodoError(
                f"environment variable {self.password_env} is not set for {self.name}"
            )
        return password


@dataclass(frozen=True)
class EmailRecord:
    account: str
    sender: str
    subject: str
    date: str
    body: str


def load_email_accounts(path: Path = DEFAULT_EMAIL_CONFIG_PATH) -> list[EmailAccount]:
    if not path.exists():
        raise EmailTodoError(
            f"email account config not found at {path}. "
            "Copy email_accounts.example.json and update it with your accounts."
        )

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise EmailTodoError("email account config must be a JSON list")
    return [EmailAccount.from_dict(item) for item in data]


def generate_email_todos(
    assistant: GeminiAssistant,
    memory: MemoryStore,
    *,
    config_path: Path = DEFAULT_EMAIL_CONFIG_PATH,
    command_args: str = "",
    imap_factory: Callable[[str, int], ImapConnection] = imaplib.IMAP4_SSL,
) -> str:
    args = _parse_email_todo_args(command_args)
    accounts = load_email_accounts(config_path)
    reader = ReadOnlyImapReader(imap_factory=imap_factory)
    records = reader.fetch_recent(
        [account for account in accounts if account.type == "imap"],
        days=args.days,
        limit_per_account=args.limit,
        unread_only=args.unread,
    )
    gmail_reader = GmailOAuthReader()
    records.extend(
        gmail_reader.fetch_recent(
            [account for account in accounts if account.type == "gmail_oauth"],
            days=args.days,
            limit_per_account=args.limit,
            unread_only=args.unread,
        )
    )
    if not records:
        return "No matching emails found."

    prompt = build_email_todo_prompt(records)
    response = assistant.ask(prompt, memory_context=memory.context())
    return response.text


def authorize_email_accounts(
    *,
    config_path: Path = DEFAULT_EMAIL_CONFIG_PATH,
) -> str:
    accounts = [account for account in load_email_accounts(config_path) if account.type == "gmail_oauth"]
    if not accounts:
        return "No gmail_oauth accounts are configured."

    reader = GmailOAuthReader()
    authorized = []
    for account in accounts:
        reader.credentials_for(account)
        authorized.append(account.name)
    return "Authorized Gmail account(s): " + ", ".join(authorized)


def build_email_todo_prompt(records: Iterable[EmailRecord]) -> str:
    sections = []
    for index, record in enumerate(records, start=1):
        sections.append(
            "\n".join(
                [
                    f"Email {index}",
                    f"Account: {record.account}",
                    f"From: {record.sender}",
                    f"Date: {record.date}",
                    f"Subject: {record.subject}",
                    "Body:",
                    record.body[:MAX_BODY_CHARS],
                ]
            )
        )

    joined = "\n\n---\n\n".join(sections)
    return f"""Extract a practical todo list from these emails.

Rules:
- Only include tasks, deadlines, follow-ups, decisions, or waiting-on items that are grounded in the emails.
- Include the source account and email subject for each item.
- Prefer concise Markdown checkboxes grouped by priority.
- If a deadline appears, include it exactly as written.
- Do not invent tasks.

Emails:

{joined}
"""


class ReadOnlyImapReader:
    def __init__(
        self,
        *,
        imap_factory: Callable[[str, int], ImapConnection] = imaplib.IMAP4_SSL,
    ) -> None:
        self._imap_factory = imap_factory

    def fetch_recent(
        self,
        accounts: Iterable[EmailAccount],
        *,
        days: int,
        limit_per_account: int,
        unread_only: bool = False,
    ) -> list[EmailRecord]:
        records: list[EmailRecord] = []
        since = _imap_since_date(days)
        criteria = ["SINCE", since]
        if unread_only:
            criteria.insert(0, "UNSEEN")

        for account in accounts:
            connection = self._imap_factory(account.host, account.port)
            selected = False
            try:
                connection.login(account.username, account.password())
                _assert_ok(connection.select(account.mailbox, readonly=True), "select")
                selected = True
                status, data = connection.search(None, *criteria)
                _assert_ok((status, data), "search")

                message_ids = data[0].split() if data and data[0] else []
                for message_id in message_ids[-limit_per_account:]:
                    record = self._fetch_message(connection, account, message_id)
                    if record:
                        records.append(record)
            finally:
                if selected:
                    _safe_close(connection)
                connection.logout()

        return records

    def _fetch_message(
        self,
        connection: ImapConnection,
        account: EmailAccount,
        message_id: bytes,
    ) -> EmailRecord | None:
        status, data = connection.fetch(message_id, "(BODY.PEEK[])")
        _assert_ok((status, data), "fetch")

        raw_message = _first_message_bytes(data)
        if not raw_message:
            return None

        parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
        body = _message_body(parsed).strip()
        if not body:
            return None

        return EmailRecord(
            account=account.name,
            sender=str(parsed.get("From", "")),
            subject=str(parsed.get("Subject", "")),
            date=str(parsed.get("Date", "")),
            body=_clean_body(body),
        )


class GmailOAuthReader:
    def fetch_recent(
        self,
        accounts: Iterable[EmailAccount],
        *,
        days: int,
        limit_per_account: int,
        unread_only: bool = False,
    ) -> list[EmailRecord]:
        records: list[EmailRecord] = []
        after = date.today() - timedelta(days=days)
        after_query = after.strftime("%Y/%m/%d")

        for account in accounts:
            service = self.service_for(account)
            query_parts = [account.query, f"after:{after_query}"]
            if unread_only:
                query_parts.append("is:unread")
            query = " ".join(part for part in query_parts if part).strip()

            response = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=limit_per_account)
                .execute()
            )
            for item in response.get("messages", []):
                message = (
                    service.users()
                    .messages()
                    .get(userId="me", id=item["id"], format="full")
                    .execute()
                )
                body = _gmail_message_body(message)
                if not body:
                    continue
                headers = _gmail_headers(message)
                records.append(
                    EmailRecord(
                        account=account.name,
                        sender=headers.get("from", ""),
                        subject=headers.get("subject", ""),
                        date=headers.get("date", ""),
                        body=_clean_body(body),
                    )
                )

        return records

    def service_for(self, account: EmailAccount) -> Any:
        credentials = self.credentials_for(account)
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise EmailTodoError(
                "Gmail OAuth dependencies are not installed. Run `pip install -e .` first."
            ) from exc

        return build("gmail", "v1", credentials=credentials)

    def credentials_for(self, account: EmailAccount) -> Any:
        if not account.client_secret_file or not account.token_file:
            raise EmailTodoError(f"{account.name} is missing OAuth credential paths")

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise EmailTodoError(
                "Gmail OAuth dependencies are not installed. Run `pip install -e .` first."
            ) from exc

        credentials = None
        if account.token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(account.token_file),
                [GMAIL_READONLY_SCOPE],
            )

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                if not account.client_secret_file.exists():
                    raise EmailTodoError(
                        f"Google OAuth client secret file not found at {account.client_secret_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(account.client_secret_file),
                    [GMAIL_READONLY_SCOPE],
                )
                credentials = flow.run_local_server(port=0)

            account.token_file.parent.mkdir(parents=True, exist_ok=True)
            account.token_file.write_text(credentials.to_json(), encoding="utf-8")

        return credentials


def _parse_email_todo_args(command_args: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="/email-todos", add_help=False)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--unread", action="store_true")

    try:
        args = parser.parse_args(shlex.split(command_args))
    except SystemExit as exc:
        raise EmailTodoError("usage: /email-todos [--days N] [--limit N] [--unread]") from exc

    if args.days < 1:
        raise EmailTodoError("--days must be at least 1")
    if args.limit < 1:
        raise EmailTodoError("--limit must be at least 1")
    return args


def _imap_since_date(days: int) -> str:
    since = date.today() - timedelta(days=days)
    return since.strftime("%d-%b-%Y")


def _assert_ok(result: tuple[str, object], action: str) -> None:
    status = result[0]
    if status != "OK":
        raise EmailTodoError(f"IMAP {action} failed with status {status}")


def _safe_close(connection: ImapConnection) -> None:
    try:
        connection.close()
    except Exception:
        pass


def _first_message_bytes(data: list) -> bytes | None:
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
        if isinstance(item, bytes):
            return item
    return None


def _message_body(message: ParsedEmailMessage) -> str:
    if message.is_multipart():
        plain_parts = []
        html_parts = []
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(_html_to_text(part.get_content()))
        return "\n".join(plain_parts or html_parts)

    if message.get_content_type() == "text/html":
        return _html_to_text(message.get_content())
    return str(message.get_content())


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(value)


def _clean_body(value: str) -> str:
    lines = []
    for line in value.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _gmail_headers(message: dict[str, Any]) -> dict[str, str]:
    headers = {}
    for header in message.get("payload", {}).get("headers", []):
        name = str(header.get("name", "")).lower()
        value = str(header.get("value", ""))
        if name:
            headers[name] = value
    return headers


def _gmail_message_body(message: dict[str, Any]) -> str:
    payload = message.get("payload", {})
    plain_parts = []
    html_parts = []

    for part in _gmail_payload_parts(payload):
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if not data:
            continue
        decoded = _base64url_decode(data)
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(_html_to_text(decoded))

    return "\n".join(plain_parts or html_parts)


def _gmail_payload_parts(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if payload.get("mimeType") in {"text/plain", "text/html"}:
        yield payload
    for part in payload.get("parts", []) or []:
        yield from _gmail_payload_parts(part)


def _base64url_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
        "utf-8",
        errors="replace",
    )

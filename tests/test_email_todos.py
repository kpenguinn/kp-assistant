from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kp_assistant.email_todos import (
    EmailAccount,
    EmailRecord,
    ReadOnlyImapReader,
    build_email_todo_prompt,
    _gmail_message_body,
    load_email_accounts,
)


RAW_EMAIL = b"""From: Pat <pat@example.com>
Subject: Please review the proposal
Date: Tue, 8 Sep 2026 09:30:00 -0400
Content-Type: text/plain; charset=utf-8

Can you review the proposal by Friday and send feedback?
"""


class FakeImap:
    instances: list["FakeImap"] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.selected_readonly: bool | None = None
        self.fetch_parts: list[str] = []
        self.logged_out = False
        FakeImap.instances.append(self)

    def login(self, user: str, password: str):
        self.user = user
        self.password = password
        return "OK", []

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self.mailbox = mailbox
        self.selected_readonly = readonly
        return "OK", [b"1"]

    def search(self, charset: str | None, *criteria: str):
        self.criteria = criteria
        return "OK", [b"42"]

    def fetch(self, message_set: bytes | str, message_parts: str):
        self.message_set = message_set
        self.fetch_parts.append(message_parts)
        return "OK", [(b"42 (BODY[] {128}", RAW_EMAIL)]

    def close(self):
        return "OK", []

    def logout(self):
        self.logged_out = True
        return "OK", []


class EmailTodoTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeImap.instances = []

    def test_load_email_accounts_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.json"
            path.write_text(
                """[
                  {
                    "type": "imap",
                    "name": "personal",
                    "host": "imap.example.com",
                    "username": "me@example.com",
                    "password_env": "EMAIL_PASSWORD"
                  }
                ]""",
                encoding="utf-8",
            )

            accounts = load_email_accounts(path)

        self.assertEqual(accounts[0].name, "personal")
        self.assertEqual(accounts[0].port, 993)
        self.assertEqual(accounts[0].mailbox, "INBOX")

    def test_reader_selects_readonly_and_peeks_body(self) -> None:
        account = EmailAccount(
            type="imap",
            name="personal",
            host="imap.example.com",
            username="me@example.com",
            password_env="EMAIL_PASSWORD",
        )
        reader = ReadOnlyImapReader(imap_factory=FakeImap)

        with patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}):
            records = reader.fetch_recent([account], days=2, limit_per_account=10)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].subject, "Please review the proposal")
        self.assertEqual(FakeImap.instances[0].selected_readonly, True)
        self.assertEqual(FakeImap.instances[0].fetch_parts, ["(BODY.PEEK[])"])
        self.assertEqual(FakeImap.instances[0].logged_out, True)

    def test_build_prompt_includes_sources(self) -> None:
        prompt = build_email_todo_prompt(
            [
                EmailRecord(
                    account="work",
                    sender="boss@example.com",
                    subject="Status update",
                    date="today",
                    body="Please send me the status update tomorrow.",
                )
            ]
        )

        self.assertIn("Account: work", prompt)
        self.assertIn("Subject: Status update", prompt)
        self.assertIn("Do not invent tasks.", prompt)

    def test_load_gmail_oauth_account_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.json"
            path.write_text(
                """[
                  {
                    "type": "gmail_oauth",
                    "name": "gmail",
                    "client_secret_file": "~/client-secret.json",
                    "token_file": "~/gmail-token.json"
                  }
                ]""",
                encoding="utf-8",
            )

            accounts = load_email_accounts(path)

        self.assertEqual(accounts[0].type, "gmail_oauth")
        self.assertEqual(accounts[0].query, "in:inbox")
        self.assertEqual(accounts[0].client_secret_file, Path("~/client-secret.json").expanduser())

    def test_gmail_message_body_decodes_plain_text(self) -> None:
        message = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": "UGxlYXNlIHJldmlldyB0aGUgZHJhZnQgdG9kYXku"
                        },
                    }
                ],
            }
        }

        self.assertEqual(_gmail_message_body(message), "Please review the draft today.")


if __name__ == "__main__":
    unittest.main()

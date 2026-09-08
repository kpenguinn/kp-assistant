# kp-assistant

A personal command-line AI assistant written in Python and powered by the Gemini API.

## Setup

1. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install the app:

   ```bash
   pip install -e .
   ```

3. Set your Gemini API key:

   ```bash
   export GEMINI_API_KEY="your_api_key_here"
   ```

   You can also copy `.env.example` to `.env`, but this app reads environment
   variables directly, so load that file with your shell or another env manager.

## Usage

Start an interactive chat:

```bash
kp-assistant
```

Ask a one-shot question:

```bash
kp-assistant "Plan my top three priorities for today"
```

Use a different model:

```bash
kp-assistant --model gemini-3.7-flash "Draft a short email"
```

## Chat commands

```text
/remember <text>   Save a personal fact or preference
/memories          List saved memories
/forget <number>   Delete a saved memory
/email-auth        Sign in to configured Gmail OAuth accounts
/email-todos       Scan configured email accounts and generate todos
/reset             Start a fresh Gemini conversation
/help              Show commands
/exit              Quit
```

Memories are stored locally in `~/.kp_assistant/memory.json` by default. You can
use another file with `--memory-file`.

## Email Todo Scanning

The assistant can scan multiple email inboxes in read-only mode and ask Gemini to
extract a todo list. For Gmail, use OAuth so your Google password is never stored
or entered into this app.

Read-only safeguards:

- It opens each IMAP mailbox with `readonly=True`.
- It fetches messages with `BODY.PEEK[]`, which avoids marking messages as read.
- It never sends IMAP `STORE`, `COPY`, `MOVE`, `DELETE`, or `EXPUNGE` commands.
- For Gmail OAuth accounts, it requests only the Gmail read-only OAuth scope.

Set up accounts:

```bash
mkdir -p ~/.kp_assistant
cp email_accounts.example.json ~/.kp_assistant/email_accounts.json
```

### Gmail OAuth

For Gmail or Google Workspace email:

1. Create or choose a Google Cloud project.
2. Enable the Gmail API.
3. Configure the Google Auth consent screen.
4. Create an OAuth client with application type `Desktop app`.
5. Download the client JSON and save it somewhere private, for example:

   ```text
   ~/.kp_assistant/google_client_secret.json
   ```

Configure an account:

```json
[
  {
    "type": "gmail_oauth",
    "name": "personal-gmail",
    "client_secret_file": "~/.kp_assistant/google_client_secret.json",
    "token_file": "~/.kp_assistant/google_personal_token.json",
    "query": "in:inbox"
  }
]
```

Then start the assistant and sign in:

```text
/email-auth
```

Your browser will open Google's consent flow. After that, the assistant stores an
OAuth token at the configured `token_file`; it does not store your Google
password.

### IMAP fallback

For non-Google providers, IMAP can still work. Store passwords in environment
variables rather than in the JSON file:

```json
[
  {
    "type": "imap",
    "name": "personal",
    "host": "imap.gmail.com",
    "port": 993,
    "username": "you@gmail.com",
    "password_env": "PERSONAL_EMAIL_APP_PASSWORD",
    "mailbox": "INBOX"
  }
]
```

Then run:

```bash
export PERSONAL_EMAIL_APP_PASSWORD="your_email_app_password"
kp-assistant
```

Inside chat:

```text
/email-auth
/email-todos
/email-todos --days 3 --limit 10
/email-todos --unread
```

For many providers, your normal account password will not work with IMAP. Use
OAuth where possible, or an app password/account-specific mail credential where
your provider requires it.

## Configuration

Environment variables:

```text
GEMINI_API_KEY                    Required for real Gemini requests
KP_ASSISTANT_MODEL                Optional, defaults to gemini-3.7-flash
KP_ASSISTANT_TEMPERATURE          Optional, defaults to 0.7
KP_ASSISTANT_SYSTEM_INSTRUCTION   Optional assistant behavior override
PERSONAL_EMAIL_APP_PASSWORD       Example password env for email account config
WORK_EMAIL_APP_PASSWORD           Example password env for email account config
```

## Development

Run the tests:

```bash
python -m unittest discover -s tests
```

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from kp_assistant.assistant import AssistantError, GeminiAssistant
from kp_assistant.config import AssistantConfig
from kp_assistant.email_todos import (
    DEFAULT_EMAIL_CONFIG_PATH,
    EmailTodoError,
    authorize_email_accounts,
    generate_email_todos,
)
from kp_assistant.memory import DEFAULT_MEMORY_PATH, MemoryStore


HELP_TEXT = """Commands:
  /help                Show this help
  /email-auth          Sign in to configured Gmail OAuth accounts
  /email-todos         Scan configured email accounts and generate todos
  /remember <text>     Save a personal fact or preference
  /memories            List saved memories
  /forget <number>     Delete a saved memory
  /reset               Start a fresh Gemini conversation
  /exit                Quit
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kp-assistant",
        description="Personal command-line AI assistant powered by Gemini.",
    )
    parser.add_argument("prompt", nargs="*", help="optional one-shot prompt")
    parser.add_argument("--model", help="Gemini model name")
    parser.add_argument(
        "--temperature",
        type=float,
        help="generation temperature, defaults to KP_ASSISTANT_TEMPERATURE or 0.7",
    )
    parser.add_argument(
        "--memory-file",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help=f"path to local memory JSON file, defaults to {DEFAULT_MEMORY_PATH}",
    )
    parser.add_argument(
        "--email-config",
        type=Path,
        default=DEFAULT_EMAIL_CONFIG_PATH,
        help=f"path to read-only email account config, defaults to {DEFAULT_EMAIL_CONFIG_PATH}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AssistantConfig.from_env(
        model=args.model,
        temperature=args.temperature,
    )
    memory = MemoryStore(args.memory_file)
    assistant = GeminiAssistant(config)

    if args.prompt:
        return _ask_once(assistant, memory, " ".join(args.prompt))

    return _chat_loop(assistant, memory, args.email_config)


def _ask_once(assistant: GeminiAssistant, memory: MemoryStore, prompt: str) -> int:
    try:
        response = assistant.ask(prompt, memory_context=memory.context())
    except (AssistantError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(response.text)
    return 0


def _chat_loop(
    assistant: GeminiAssistant,
    memory: MemoryStore,
    email_config: Path,
) -> int:
    print("kp-assistant. Type /help for commands, /exit to quit.")
    while True:
        try:
            prompt = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not prompt:
            continue
        if prompt.startswith("/"):
            should_continue = _handle_command(prompt, assistant, memory, email_config)
            if not should_continue:
                return 0
            continue

        try:
            response = assistant.ask(prompt, memory_context=memory.context())
        except (AssistantError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        print(f"\nAssistant: {response.text}")


def _handle_command(
    command: str,
    assistant: GeminiAssistant,
    memory: MemoryStore,
    email_config: Path = DEFAULT_EMAIL_CONFIG_PATH,
) -> bool:
    name, _, value = command.partition(" ")

    if name in {"/exit", "/quit"}:
        return False
    if name == "/help":
        print(HELP_TEXT)
        return True
    if name == "/reset":
        assistant.reset()
        print("Started a fresh conversation.")
        return True
    if name == "/email-todos":
        try:
            print("Scanning email accounts in read-only mode...")
            todos = generate_email_todos(
                assistant,
                memory,
                config_path=email_config,
                command_args=value,
            )
        except (EmailTodoError, AssistantError) as exc:
            print(f"error: {exc}", file=sys.stderr)
        else:
            print(f"\n{todos}")
        return True
    if name == "/email-auth":
        try:
            print("Opening browser sign-in for configured Gmail OAuth accounts...")
            result = authorize_email_accounts(config_path=email_config)
        except EmailTodoError as exc:
            print(f"error: {exc}", file=sys.stderr)
        else:
            print(result)
        return True
    if name == "/remember":
        try:
            memory.add(value)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
        else:
            print("Saved.")
        return True
    if name == "/memories":
        memories = memory.list()
        if not memories:
            print("No saved memories.")
        else:
            for index, item in enumerate(memories, start=1):
                print(f"{index}. {item}")
        return True
    if name == "/forget":
        try:
            removed = memory.forget(int(value))
        except ValueError:
            print("error: use /forget <number>", file=sys.stderr)
        except IndexError as exc:
            print(f"error: {exc}", file=sys.stderr)
        else:
            print(f"Forgot: {removed}")
        return True

    print("Unknown command. Type /help for commands.")
    return True

from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_MODEL = "gemini-3.7-flash"
DEFAULT_SYSTEM_INSTRUCTION = """You are a concise, practical personal assistant.
Help the user plan, remember, write, debug, and make decisions.
Ask clarifying questions only when the missing detail materially changes the answer.
When the user asks for an action plan, keep it concrete and ordered."""


@dataclass(frozen=True)
class AssistantConfig:
    model: str = DEFAULT_MODEL
    api_key: str | None = None
    system_instruction: str = DEFAULT_SYSTEM_INSTRUCTION
    temperature: float = 0.7

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        temperature: float | None = None,
        system_instruction: str | None = None,
    ) -> "AssistantConfig":
        return cls(
            model=model or os.getenv("KP_ASSISTANT_MODEL", DEFAULT_MODEL),
            api_key=os.getenv("GEMINI_API_KEY"),
            system_instruction=system_instruction
            or os.getenv("KP_ASSISTANT_SYSTEM_INSTRUCTION", DEFAULT_SYSTEM_INSTRUCTION),
            temperature=temperature
            if temperature is not None
            else float(os.getenv("KP_ASSISTANT_TEMPERATURE", "0.7")),
        )


from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from kp_assistant.config import AssistantConfig


class AssistantError(RuntimeError):
    """Raised when the assistant cannot complete an API request."""


@dataclass
class AssistantResponse:
    text: str
    interaction_id: str | None


class GeminiAssistant:
    def __init__(
        self,
        config: AssistantConfig,
        *,
        genai_module: Any | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._genai_module = genai_module
        self._client = client
        self._previous_interaction_id: str | None = None

    @property
    def previous_interaction_id(self) -> str | None:
        return self._previous_interaction_id

    def reset(self) -> None:
        self._previous_interaction_id = None

    def ask(self, prompt: str, *, memory_context: str = "") -> AssistantResponse:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        request: dict[str, Any] = {
            "model": self.config.model,
            "input": prompt,
            "system_instruction": self._system_instruction(memory_context),
            "generation_config": {"temperature": self.config.temperature},
        }
        if self._previous_interaction_id:
            request["previous_interaction_id"] = self._previous_interaction_id

        try:
            interaction = self._get_client().interactions.create(**request)
        except ImportError as exc:
            raise AssistantError(
                "google-genai is not installed. Run `pip install -e .` first."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - keep CLI errors readable.
            raise AssistantError(f"Gemini API request failed: {exc}") from exc

        interaction_id = getattr(interaction, "id", None)
        if interaction_id:
            self._previous_interaction_id = interaction_id

        text = getattr(interaction, "output_text", None)
        if not text:
            text = self._extract_text_from_steps(getattr(interaction, "steps", None))
        if not text:
            raise AssistantError("Gemini returned no text output.")

        return AssistantResponse(text=text, interaction_id=interaction_id)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        genai = self._genai_module
        if genai is None:
            genai = import_module("google.genai")

        kwargs = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key

        self._client = genai.Client(**kwargs)
        return self._client

    def _system_instruction(self, memory_context: str) -> str:
        parts = [self.config.system_instruction.strip()]
        if memory_context.strip():
            parts.append(memory_context.strip())
        return "\n\n".join(parts)

    @staticmethod
    def _extract_text_from_steps(steps: Any) -> str:
        if not steps:
            return ""

        chunks: list[str] = []
        for step in steps:
            content = getattr(step, "content", None)
            if content is None and isinstance(step, dict):
                content = step.get("content")
            if not content:
                continue
            for item in content:
                text = getattr(item, "text", None)
                if text is None and isinstance(item, dict):
                    text = item.get("text")
                if text:
                    chunks.append(text)
        return "".join(chunks).strip()


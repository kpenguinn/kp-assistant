from __future__ import annotations

from types import SimpleNamespace
import unittest

from kp_assistant.assistant import GeminiAssistant
from kp_assistant.config import AssistantConfig


class FakeInteractions:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            id=f"interaction-{len(self.requests)}",
            output_text=f"response {len(self.requests)}",
        )


class FakeClient:
    def __init__(self) -> None:
        self.interactions = FakeInteractions()


class GeminiAssistantTests(unittest.TestCase):
    def test_ask_sends_prompt_and_returns_text(self) -> None:
        client = FakeClient()
        assistant = GeminiAssistant(
            AssistantConfig(model="gemini-test", temperature=0.2),
            client=client,
        )

        response = assistant.ask("hello", memory_context="Known facts:\n- test")

        self.assertEqual(response.text, "response 1")
        self.assertEqual(response.interaction_id, "interaction-1")
        self.assertEqual(client.interactions.requests[0]["model"], "gemini-test")
        self.assertEqual(client.interactions.requests[0]["input"], "hello")
        self.assertIn(
            "Known facts",
            client.interactions.requests[0]["system_instruction"],
        )
        self.assertEqual(
            client.interactions.requests[0]["generation_config"]["temperature"],
            0.2,
        )

    def test_ask_continues_with_previous_interaction_id(self) -> None:
        client = FakeClient()
        assistant = GeminiAssistant(AssistantConfig(), client=client)

        assistant.ask("first")
        assistant.ask("second")

        self.assertNotIn("previous_interaction_id", client.interactions.requests[0])
        self.assertEqual(
            client.interactions.requests[1]["previous_interaction_id"],
            "interaction-1",
        )

    def test_reset_starts_new_conversation(self) -> None:
        client = FakeClient()
        assistant = GeminiAssistant(AssistantConfig(), client=client)

        assistant.ask("first")
        assistant.reset()
        assistant.ask("second")

        self.assertNotIn("previous_interaction_id", client.interactions.requests[1])


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from kp_assistant.memory import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_add_list_context_and_forget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.json")

            store.add("I prefer brief answers.")
            store.add("My timezone is Pacific.")

            self.assertEqual(
                store.list(),
                ["I prefer brief answers.", "My timezone is Pacific."],
            )
            self.assertIn("Known user facts", store.context())
            self.assertEqual(store.forget(1), "I prefer brief answers.")
            self.assertEqual(store.list(), ["My timezone is Pacific."])


if __name__ == "__main__":
    unittest.main()


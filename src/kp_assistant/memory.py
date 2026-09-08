from __future__ import annotations

import json
from pathlib import Path


DEFAULT_MEMORY_PATH = Path.home() / ".kp_assistant" / "memory.json"


class MemoryStore:
    def __init__(self, path: Path = DEFAULT_MEMORY_PATH) -> None:
        self.path = path

    def list(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        memories = data.get("memories", [])
        if not isinstance(memories, list):
            return []
        return [str(memory) for memory in memories if str(memory).strip()]

    def add(self, memory: str) -> None:
        memory = memory.strip()
        if not memory:
            raise ValueError("memory must not be empty")
        memories = self.list()
        memories.append(memory)
        self._write(memories)

    def forget(self, index: int) -> str:
        memories = self.list()
        if index < 1 or index > len(memories):
            raise IndexError("memory number is out of range")
        removed = memories.pop(index - 1)
        self._write(memories)
        return removed

    def context(self) -> str:
        memories = self.list()
        if not memories:
            return ""
        lines = ["Known user facts and preferences:"]
        lines.extend(f"- {memory}" for memory in memories)
        return "\n".join(lines)

    def _write(self, memories: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump({"memories": memories}, file, indent=2)
            file.write("\n")


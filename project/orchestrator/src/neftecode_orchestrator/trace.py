from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .contracts import ExecutionTrace


class TraceSink(Protocol):
    def write(self, trace: ExecutionTrace) -> None: ...


class NullTraceSink:
    def write(self, trace: ExecutionTrace) -> None:
        return None


class InMemoryTraceSink:
    def __init__(self) -> None:
        self.traces: list[ExecutionTrace] = []

    def write(self, trace: ExecutionTrace) -> None:
        self.traces.append(trace)


class JsonlTraceSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, trace: ExecutionTrace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(trace.model_dump_json() + "\n")

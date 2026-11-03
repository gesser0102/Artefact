import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from emporio_agent.domain.exceptions import TraceWriteError

TRACE_FILE_NAME = "turns.jsonl"


class JsonlTraceSink:
    def __init__(self, trace_dir: Path) -> None:
        self.path = trace_dir / TRACE_FILE_NAME

    def write(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as trace_file:
                trace_file.write(f"{line}\n")
        except OSError as error:
            raise TraceWriteError("Could not append the turn trace") from error

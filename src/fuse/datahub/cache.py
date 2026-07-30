"""Record/replay for every DataHub call.

Live runs write each response to ``fixtures/``. ``--replay`` reads from there and
treats a miss as a hard error, so an offline demo can never quietly fabricate data.
This is also what makes the end-to-end test deterministic.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ReplayMiss(RuntimeError):
    """Raised when replay mode needs a call that was never recorded."""


# Windows rejects : < > " | ? * in filenames, so a key like "llm:codegen" produces a
# repository that cannot be checked out there at all — git fails with "invalid path"
# before any code runs. Fixtures are committed and judges clone on every platform, so
# the filename has to be portable even though the key need not be.
UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def _key(tool: str, args: dict[str, Any]) -> str:
    canonical = json.dumps({"tool": tool, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def _safe_name(tool: str) -> str:
    return UNSAFE_IN_FILENAME.sub("-", tool)


class CallCache:
    def __init__(self, directory: Path, *, replay: bool = False, record: bool = True) -> None:
        self.dir = Path(directory)
        self.replay = replay
        self.record = record
        self.hits = 0
        self.misses = 0
        if record and not replay:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tool: str, args: dict[str, Any]) -> Path:
        # The hash is computed from the real tool name; only the readable prefix is
        # sanitised, so two tools that sanitise alike still get distinct files.
        return self.dir / f"{_safe_name(tool)}.{_key(tool, args)}.json"

    def get(self, tool: str, args: dict[str, Any]) -> Any | None:
        path = self._path(tool, args)
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        self.misses += 1
        if self.replay:
            raise ReplayMiss(
                f"No recorded response for {tool}"
                f"({json.dumps(args, sort_keys=True, default=str)}). "
                "Re-record with a live DataHub instance."
            )
        return None

    def put(self, tool: str, args: dict[str, Any], response: Any) -> None:
        if not self.record or self.replay:
            return
        payload = {"tool": tool, "args": args, "response": response}
        self._path(tool, args).write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class AuditChain:
    """Observability audit chain using append-only JSONL with chained SHA256 hashes."""

    def __init__(self, path: Path, max_bytes: int = 10_485_760) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        self._previous = "0" * 64
        self._load_tail()

    def append(self, event: str, payload: dict[str, Any]) -> str:
        with self._lock:
            self._rotate_if_needed()
            self._seq += 1
            record = {
                "seq": self._seq,
                "ts": time.time(),
                "event": event,
                "payload": payload,
                "previous_hash": self._previous,
            }
            line_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            record["hash"] = line_hash
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o640)
            try:
                os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            self._previous = line_hash
            return line_hash


    def verify(self) -> dict[str, Any]:
        previous = "0" * 64
        count = 0
        if not self.path.exists():
            return {"ok": True, "records": 0, "last_hash": previous}
        with self.path.open("r", encoding="utf-8") as handle:
            for count, line in enumerate(handle, start=1):
                record = json.loads(line)
                expected_hash = record.pop("hash")
                if record.get("previous_hash") != previous:
                    return {"ok": False, "records": count, "reason": "previous_hash_mismatch"}
                actual_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                if actual_hash != expected_hash:
                    return {"ok": False, "records": count, "reason": "line_hash_mismatch"}
                previous = expected_hash
        return {"ok": True, "records": count, "last_hash": previous}

    def _load_tail(self) -> None:
        if not self.path.exists():
            return
        try:
            last = None
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        last = json.loads(line)
            if last:
                self._seq = int(last.get("seq", 0))
                self._previous = str(last.get("hash", self._previous))
        except (OSError, json.JSONDecodeError, ValueError):
            # Fail closed for verification, but do not prevent service boot; the
            # next /admin/audit/verify call reports chain corruption.
            self._seq = 0
            self._previous = "0" * 64

    def _rotate_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return
        rotated = self.path.with_suffix(f".jsonl.{int(time.time())}")
        self.path.replace(rotated)
        self._seq = 0
        self._previous = "0" * 64

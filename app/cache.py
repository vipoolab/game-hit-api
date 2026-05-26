"""In-memory cache for the hit-games ranking, persisted as JSON on disk.

The cache is a single immutable dict — refresh swaps it atomically so reads
never see a partially-updated state.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class HitsCache:
    def __init__(self, persist_path: Path):
        self._persist_path = persist_path
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            return self._data

    def set(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._data = payload
        self._persist(payload)

    def load_from_disk(self) -> bool:
        if not self._persist_path.exists():
            return False
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Failed to load cache file %s: %s", self._persist_path, e)
            return False
        with self._lock:
            self._data = payload
        log.info("Loaded cache from %s (refreshed_at=%s)",
                 self._persist_path, payload.get("refreshed_at"))
        return True

    def _persist(self, payload: dict[str, Any]) -> None:
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp file + replace
        fd, tmp = tempfile.mkstemp(
            prefix=".hits.", suffix=".json", dir=self._persist_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, self._persist_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

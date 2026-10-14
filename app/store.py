# Copyright (C) 2026 devilc312
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lưu danh sách thread bot đã tham gia ra file JSON để restart không mất.

Ghi nguyên tử (file tạm + rename), giới hạn số lượng, chịu được file hỏng.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class ThreadStore:
    def __init__(self, path: str | os.PathLike, max_tracked: int = 500):
        self.path = Path(path)
        self.max_tracked = max_tracked
        self._lock = threading.Lock()
        self._ids: dict[int, None] = dict.fromkeys(self._load())

    def _load(self) -> list[int]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [int(x) for x in data if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".threads-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(list(self._ids), f)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def add(self, thread_id: int) -> None:
        with self._lock:
            if thread_id in self._ids:
                return
            self._ids[thread_id] = None
            while len(self._ids) > self.max_tracked:
                self._ids.pop(next(iter(self._ids)))
            self._save()

    def __contains__(self, thread_id: int) -> bool:
        with self._lock:
            return thread_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

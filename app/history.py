"""Lịch sử hội thoại theo thread, dạng trung lập giữa các nhà cung cấp LLM.

Mỗi phần tử: {"role": "user" | "assistant", "text": str}. Chỉ lưu câu hỏi và câu trả lời cuối
(không lưu kết quả tool) cho nhẹ token.
"""
from __future__ import annotations


class History:
    def __init__(self, max_turns: int):
        self.max_turns = max_turns
        self._data: dict[int, list[dict]] = {}

    def get(self, thread_id: int) -> list[dict]:
        return list(self._data.get(thread_id, []))

    def add_turn(self, thread_id: int, question: str, answer: str) -> None:
        h = self._data.setdefault(thread_id, [])
        h.append({"role": "user", "text": question})
        h.append({"role": "assistant", "text": answer})
        excess = len(h) - self.max_turns * 2
        if excess > 0:
            del h[:excess]

    def clear(self, thread_id: int) -> None:
        self._data.pop(thread_id, None)

    def __len__(self) -> int:
        return len(self._data)

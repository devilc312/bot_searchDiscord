"""Cắt câu trả lời dài thành nhiều tin <= giới hạn Discord, không làm vỡ code block.

Chia ở ký tự xuống dòng/khoảng trắng, nếu điểm chia nằm trong ``` thì đóng fence ở cuối
tin này và mở lại (cùng ngôn ngữ) ở đầu tin sau; không chia giữa cặp backtick inline.
"""
from __future__ import annotations

FENCE = "```"
CLOSE = "\n" + FENCE


def fence_state_after(text: str, in_code: bool = False, lang: str = "") -> tuple[bool, str]:
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(FENCE):
            tag = s[3:].split()
            in_code, lang = (False, "") if in_code else (True, tag[0] if tag else "")
    return in_code, lang


def split_message(text: str, limit: int = 1900) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    carry: str | None = None  # ngôn ngữ của fence còn mở từ tin trước ("" = không có tag)
    while rest:
        prefix = f"{FENCE}{carry}\n" if carry is not None else ""
        tail = prefix + rest
        if carry is not None and fence_state_after(rest, True, carry)[0]:
            tail += CLOSE
        if len(tail) <= limit:  # phần còn lại vừa trong một tin
            chunks.append(tail)
            break
        room = max(1, limit - len(prefix) - len(CLOSE))
        region = rest[:room]
        cut = region.rfind("\n")
        if cut < room // 2:
            cut = region.rfind(" ")
        if cut < 1:
            cut = room
        head = rest[:cut]
        if (head.count("`") - head.count("\\`")) % 2 == 1:  # đang ở giữa code inline
            bt = head.rfind("`")
            safe = max(head.rfind(" ", 0, bt), head.rfind("\n", 0, bt))
            if safe > room // 4:
                cut = safe
                head = rest[:cut]
        rest = rest[cut:].lstrip()
        in_code, lang = fence_state_after(head, carry is not None, carry or "")
        chunk = prefix + head
        carry = lang if in_code else None
        chunks.append(chunk + CLOSE if in_code else chunk)
    return chunks

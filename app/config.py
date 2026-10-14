# Copyright (C) 2026 devilc312
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Đọc cấu hình từ biến môi trường (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit())


@dataclass(frozen=True)
class Config:
    discord_token: str
    gemini_api_key: str = ""
    model: str = "gemini-3.8-flash"
    llm_provider: str = "gemini"    # "gemini" hoặc "anthropic"
    anthropic_base_url: str = ""
    anthropic_token: str = ""
    anthropic_model: str = ""
    owner_id: int | None = None
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)  # rỗng = ai cũng dùng được
    allowed_channel_ids: frozenset[int] = field(default_factory=frozenset)  # rỗng = mọi kênh
    history_turns: int = 6          # số cặp hỏi-đáp giữ làm ngữ cảnh mỗi thread
    max_tool_rounds: int = 4        # số vòng gọi tool tối đa mỗi câu hỏi
    rate_limit_per_min: int = 5     # số câu hỏi mỗi người mỗi phút
    data_dir: str = "data"          # nơi lưu danh sách thread

    @classmethod
    def from_env(cls) -> "Config":
        def need(name: str) -> str:
            v = os.environ.get(name, "").strip()
            if not v:
                raise SystemExit(f"Thiếu biến môi trường bắt buộc: {name}")
            return v

        provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
        if provider not in ("gemini", "anthropic"):
            raise SystemExit(f"LLM_PROVIDER không hợp lệ: {provider!r} (chỉ nhận gemini hoặc anthropic)")
        owner = os.environ.get("OWNER_ID", "").strip()
        discord_token = os.environ.get("DISCORD_TOKEN", "").strip() or need("DISCORD_BOT_TOKEN")
        if provider == "anthropic":
            llm = dict(anthropic_base_url=need("ANTHROPIC_BASE_URL"), anthropic_token=need("ANTHROPIC_AUTH_TOKEN"),
                       anthropic_model=need("ANTHROPIC_MODEL"))
        else:
            llm = dict(gemini_api_key=need("GEMINI_API_KEY"))
        return cls(
            discord_token=discord_token,
            llm_provider=provider,
            **llm,
            model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip(),
            owner_id=int(owner) if owner.isdigit() else None,
            allowed_user_ids=_ids(os.environ.get("ALLOWED_USER_IDS", "")),
            allowed_channel_ids=_ids(os.environ.get("ALLOWED_CHANNEL_IDS", "")),
            history_turns=int(os.environ.get("HISTORY_TURNS", "6")),
            max_tool_rounds=int(os.environ.get("MAX_TOOL_ROUNDS", "4")),
            rate_limit_per_min=int(os.environ.get("RATE_LIMIT_PER_MIN", "5")),
            data_dir=os.environ.get("DATA_DIR", "data"),
        )

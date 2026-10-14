# Copyright (C) 2026 devilc312
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hai tool cho LLM: tìm web (DuckDuckGo) và đọc nội dung một trang."""
from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import httpx
import trafilatura
from ddgs import DDGS

from .urlsafety import is_safe_url

MAX_PAGE_CHARS = 8000
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 4

TOOL_DECLARATIONS = [
    {
        "name": "web_search",
        "description": "Tìm kiếm trên web. Trả về danh sách tiêu đề, link và đoạn trích.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Từ khóa tìm kiếm"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Đọc nội dung chữ của một trang web theo URL (dùng sau khi đã search).",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL http(s) công khai"}},
            "required": ["url"],
        },
    },
]


def _search_sync(query: str, n: int = 6) -> list[dict]:
    with DDGS() as d:
        return list(d.text(query, max_results=n))


async def web_search(query: str) -> dict:
    query = (query or "").strip()[:300]
    if not query:
        return {"error": "query trống"}
    try:
        rows = await asyncio.to_thread(_search_sync, query)
    except Exception as e:  # DuckDuckGo hay chặn/ratelimit
        return {"error": f"search thất bại: {type(e).__name__}"}
    return {"results": [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in rows]}


async def read_page(url: str, client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "SearchBot/1.0"})
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if not await asyncio.to_thread(is_safe_url, current):
                return {"error": "URL không được phép (nội bộ hoặc không hợp lệ)"}
            async with client.stream("GET", current) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        return {"error": "redirect lỗi"}
                    current = urljoin(current, loc)
                    continue
                if r.status_code >= 400:
                    return {"error": f"HTTP {r.status_code}"}
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                html = bytes(body).decode(r.encoding or "utf-8", errors="replace")
                break
        else:
            return {"error": "quá nhiều lần redirect"}
        text = await asyncio.to_thread(trafilatura.extract, html) or ""
        return {"url": current, "text": text[:MAX_PAGE_CHARS], "truncated": len(text) > MAX_PAGE_CHARS}
    except httpx.HTTPError as e:
        return {"error": f"tải trang thất bại: {type(e).__name__}"}
    finally:
        if own:
            await client.aclose()


async def run_tool(name: str, args: dict) -> dict:
    if name == "web_search":
        return await web_search(str(args.get("query", "")))
    if name == "read_page":
        return await read_page(str(args.get("url", "")))
    return {"error": f"tool không tồn tại: {name}"}

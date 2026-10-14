"""Gọi LLM (Gemini hoặc API kiểu Anthropic) kèm vòng lặp tool. Cả hai trả lời qua `answer()`."""
from __future__ import annotations

import json

import httpx

from .tools import TOOL_DECLARATIONS, run_tool

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FINAL_NUDGE = "Hãy trả lời ngay bằng thông tin đã có."
EMPTY = "Mình không tạo được câu trả lời."


class LLMError(Exception):
    """Lỗi từ nhà cung cấp; message đã viết lại để hiển thị cho người dùng."""


def explain_http_error(status: int, body: str = "") -> str:
    if status == 429:
        return "Hết quota hoặc bị giới hạn tốc độ ở dịch vụ AI. Chủ bot cần kiểm tra gói hoặc đợi reset."
    if status == 404:
        return "Model không tồn tại hoặc đã bị ngừng. Chủ bot cần đổi tên model trong cấu hình."
    if status in (401, 403):
        return "Khóa API bị từ chối. Chủ bot cần kiểm tra khóa."
    return f"Dịch vụ AI lỗi (HTTP {status}). Thử lại sau."


def _compact(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)


class Gemini:
    def __init__(self, api_key: str, model: str, system_prompt: str, client: httpx.AsyncClient | None = None):
        self.api_key, self.model, self.system_prompt = api_key, model, system_prompt
        self._client = client or httpx.AsyncClient(timeout=60)

    async def _call(self, contents: list[dict]) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": self.system_prompt}]},
            "contents": contents,
            "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
        }
        try:
            r = await self._client.post(GEMINI_API.format(model=self.model), json=body,
                                        headers={"x-goog-api-key": self.api_key})
        except httpx.HTTPError as e:
            raise LLMError("Không kết nối được tới Gemini. Thử lại sau.") from e
        if r.status_code != 200:
            raise LLMError(explain_http_error(r.status_code, r.text))
        return r.json()

    async def answer(self, history: list[dict], question: str, max_rounds: int) -> str:
        contents = [{"role": "model" if h["role"] == "assistant" else "user", "parts": [{"text": h["text"]}]}
                    for h in history]
        contents.append({"role": "user", "parts": [{"text": question}]})
        for _ in range(max_rounds + 1):
            data = await self._call(contents)
            cands = data.get("candidates") or []
            if not cands:
                raise LLMError("Gemini không trả về nội dung (có thể bị bộ lọc an toàn chặn).")
            parts = (cands[0].get("content") or {}).get("parts") or []
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip() or EMPTY
            contents.append({"role": "model", "parts": parts})  # giữ nguyên parts (kể cả thoughtSignature)
            responses = []
            for c in calls:
                result = await run_tool(c.get("name", ""), c.get("args") or {})
                responses.append({"functionResponse": {"name": c.get("name", ""), "response": result}})
            contents.append({"role": "user", "parts": responses})
        contents.append({"role": "user", "parts": [{"text": FINAL_NUDGE}]})
        data = await self._call(contents)
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts).strip() or EMPTY


def parse_sse_message(raw: str) -> dict:
    """Ghép luồng SSE kiểu Anthropic thành một message {"content": [...]}.

    Một số gateway luôn trả SSE kể cả khi không xin stream. Hỗ trợ block text và tool_use
    (input được ghép từ các mảnh input_json_delta)."""
    blocks: dict[int, dict] = {}
    json_buf: dict[int, list[str]] = {}
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        kind, idx = ev.get("type"), ev.get("index", 0)
        if kind == "content_block_start":
            blocks[idx] = dict(ev.get("content_block") or {})
            json_buf[idx] = []
        elif kind == "content_block_delta" and idx in blocks:
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta":
                blocks[idx]["text"] = blocks[idx].get("text", "") + d.get("text", "")
            elif d.get("type") == "input_json_delta":
                json_buf[idx].append(d.get("partial_json", ""))
        elif kind == "error":
            raise LLMError("Dịch vụ AI báo lỗi giữa chừng. Thử lại sau.")
    out = []
    for idx in sorted(blocks):
        b = blocks[idx]
        if b.get("type") == "tool_use":
            joined = "".join(json_buf.get(idx, []))
            try:
                b["input"] = json.loads(joined) if joined else (b.get("input") or {})
            except ValueError:
                b["input"] = {}
        out.append(b)
    return {"content": out}


class Anthropic:
    """API kiểu Anthropic Messages (kể cả gateway tương thích), xác thực bằng Bearer token."""

    def __init__(self, base_url: str, token: str, model: str, system_prompt: str,
                 client: httpx.AsyncClient | None = None, max_tokens: int = 2048):
        self.url = base_url.rstrip("/") + "/v1/messages"
        self.token, self.model, self.system_prompt, self.max_tokens = token, model, system_prompt, max_tokens
        self._client = client or httpx.AsyncClient(timeout=90)
        self._tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                       for t in TOOL_DECLARATIONS]

    async def _call(self, messages: list[dict], *, allow_tools: bool = True) -> dict:
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": self.system_prompt,
                "messages": messages, "tools": self._tools}
        if not allow_tools:
            body["tool_choice"] = {"type": "none"}
        headers = {"Authorization": f"Bearer {self.token}", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        try:
            r = await self._client.post(self.url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError("Không kết nối được tới dịch vụ AI. Thử lại sau.") from e
        if r.status_code != 200:
            raise LLMError(explain_http_error(r.status_code, r.text))
        if "text/event-stream" in r.headers.get("content-type", ""):
            return parse_sse_message(r.text)
        try:
            return r.json()
        except ValueError as e:
            raise LLMError("Dịch vụ AI trả về dữ liệu không hợp lệ.") from e

    @staticmethod
    def _text(blocks: list[dict]) -> str:
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    async def answer(self, history: list[dict], question: str, max_rounds: int) -> str:
        messages = [{"role": h["role"], "content": h["text"]} for h in history]
        messages.append({"role": "user", "content": question})
        for _ in range(max_rounds + 1):
            data = await self._call(messages)
            blocks = data.get("content") or []
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                text = self._text(blocks)
                if not text and not blocks:
                    raise LLMError("Dịch vụ AI không trả về nội dung.")
                return text or EMPTY
            messages.append({"role": "assistant", "content": blocks})
            results = []
            for u in uses:
                out = await run_tool(u.get("name", ""), u.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": u.get("id", ""), "content": _compact(out)})
            messages.append({"role": "user", "content": results})
        messages.append({"role": "user", "content": FINAL_NUDGE})
        data = await self._call(messages, allow_tools=False)
        return self._text(data.get("content") or []) or EMPTY


def make_llm(cfg, system_prompt: str):
    if cfg.llm_provider == "anthropic":
        return Anthropic(cfg.anthropic_base_url, cfg.anthropic_token, cfg.anthropic_model, system_prompt)
    return Gemini(cfg.gemini_api_key, cfg.model, system_prompt)

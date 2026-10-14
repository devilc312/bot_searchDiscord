import json

import httpx
import pytest

from app import llm as llm_mod
from app.config import Config
from app.llm import Anthropic, Gemini, LLMError, make_llm


def make(handler):
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Anthropic("https://gw.example/", "TOKEN", "m", "sys", client=c)


def text(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn"}


async def test_plain_answer_and_request_shape():
    seen = {}
    def handler(req):
        seen["url"], seen["h"], seen["b"] = str(req.url), req.headers, json.loads(req.content)
        return httpx.Response(200, json=text("chào"))
    a = make(handler)
    assert await a.answer([{"role": "user", "text": "q0"}, {"role": "assistant", "text": "a0"}], "hi", 3) == "chào"
    assert seen["url"] == "https://gw.example/v1/messages"
    assert seen["h"]["authorization"] == "Bearer TOKEN" and "x-api-key" not in seen["h"]
    b = seen["b"]
    assert b["system"] == "sys" and b["model"] == "m" and b["max_tokens"] > 0
    assert b["messages"] == [{"role": "user", "content": "q0"}, {"role": "assistant", "content": "a0"},
                             {"role": "user", "content": "hi"}]
    assert {t["name"] for t in b["tools"]} == {"web_search", "read_page"}
    assert all("input_schema" in t for t in b["tools"])


async def test_tool_use_round(monkeypatch):
    calls = []
    async def fake_tool(name, args):
        calls.append((name, args)); return {"results": [1]}
    monkeypatch.setattr(llm_mod, "run_tool", fake_tool)
    bodies = []
    def handler(req):
        bodies.append(json.loads(req.content))
        if len(bodies) == 1:
            return httpx.Response(200, json={"content": [
                {"type": "text", "text": "để tìm"},
                {"type": "tool_use", "id": "tu_1", "name": "web_search", "input": {"query": "q"}}]})
        return httpx.Response(200, json=text("xong"))
    assert await make(handler).answer([], "hỏi", 3) == "xong"
    assert calls == [("web_search", {"query": "q"})]
    msgs = bodies[1]["messages"]
    assert msgs[-2]["role"] == "assistant" and msgs[-2]["content"][1]["type"] == "tool_use"
    tr = msgs[-1]["content"][0]
    assert msgs[-1]["role"] == "user" and tr["type"] == "tool_result" and tr["tool_use_id"] == "tu_1"
    assert json.loads(tr["content"]) == {"results": [1]}


async def test_tool_loop_bounded_then_forced_final(monkeypatch):
    async def fake_tool(name, args): return {}
    monkeypatch.setattr(llm_mod, "run_tool", fake_tool)
    bodies = []
    def handler(req):
        b = json.loads(req.content); bodies.append(b)
        if b.get("tool_choice") == {"type": "none"}:
            return httpx.Response(200, json=text("chốt"))
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": "x", "name": "web_search", "input": {}}]})
    assert await make(handler).answer([], "q", 2) == "chốt"
    assert len(bodies) == 2 + 1 + 1


@pytest.mark.parametrize("status,needle", [(429, "quota"), (404, "model"), (401, "Khóa"), (500, "500")])
async def test_http_errors_friendly_no_leak(status, needle):
    a = make(lambda r: httpx.Response(status, text="BODY-SECRET"))
    with pytest.raises(LLMError) as e:
        await a.answer([], "q", 1)
    assert needle in str(e.value) and "BODY-SECRET" not in str(e.value)


async def test_empty_content_and_bad_json():
    with pytest.raises(LLMError):
        await make(lambda r: httpx.Response(200, json={"content": []})).answer([], "q", 1)
    with pytest.raises(LLMError):
        await make(lambda r: httpx.Response(200, text="<html>gateway</html>")).answer([], "q", 1)


async def test_token_never_in_url():
    got = {}
    def handler(req):
        got["u"] = str(req.url); return httpx.Response(200, json=text("ok"))
    await make(handler).answer([], "q", 1)
    assert "TOKEN" not in got["u"]


# ---- chọn provider và cấu hình
def test_make_llm_selects_provider():
    base = dict(discord_token="d")
    assert isinstance(make_llm(Config(**base, gemini_api_key="k"), "s"), Gemini)
    a = make_llm(Config(**base, llm_provider="anthropic", anthropic_base_url="https://x", anthropic_token="t",
                        anthropic_model="m"), "s")
    assert isinstance(a, Anthropic) and a.url == "https://x/v1/messages"


def _clear(monkeypatch):
    for k in ("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "GEMINI_API_KEY", "LLM_PROVIDER", "ANTHROPIC_BASE_URL",
              "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DISCORD_TOKEN", "d")


def test_config_anthropic_requires_its_vars(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(SystemExit) as e:
        Config.from_env()
    assert "ANTHROPIC_BASE_URL" in str(e.value)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_MODEL", "m")
    c = Config.from_env()
    assert c.llm_provider == "anthropic" and c.anthropic_model == "m" and c.gemini_api_key == ""


def test_config_gemini_does_not_need_anthropic_vars(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert Config.from_env().llm_provider == "gemini"


def test_config_rejects_unknown_provider(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(SystemExit):
        Config.from_env()


# ---- SSE (gateway luôn trả stream)
def sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


SSE_TEXT = sse(
    {"type": "message_start", "message": {"content": []}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Xin "}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "chào"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
)
SSE_TOOL = sse(
    {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "call_1", "name": "web_search", "input": {}}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"query":'}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": ' "python"}'}},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
)


def sse_resp(body):
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def test_parse_sse_text_and_tool_input_assembled():
    from app.llm import parse_sse_message
    assert parse_sse_message(SSE_TEXT)["content"] == [{"type": "text", "text": "Xin chào"}]
    blk = parse_sse_message(SSE_TOOL)["content"][0]
    assert blk["name"] == "web_search" and blk["input"] == {"query": "python"} and blk["id"] == "call_1"


def test_parse_sse_ignores_garbage_and_bad_tool_json():
    from app.llm import parse_sse_message
    assert parse_sse_message("data: {not json\n\nevent: x\n")["content"] == []
    bad = sse({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "a", "name": "n", "input": {}}},
              {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"q'}})
    assert parse_sse_message(bad)["content"][0]["input"] == {}


def test_parse_sse_error_event():
    from app.llm import parse_sse_message
    with pytest.raises(LLMError):
        parse_sse_message(sse({"type": "error", "error": {"message": "SECRET"}}))


async def test_answer_over_sse_with_tool_round(monkeypatch):
    calls = []
    async def fake_tool(name, args):
        calls.append((name, args)); return {"ok": True}
    monkeypatch.setattr(llm_mod, "run_tool", fake_tool)
    n = [0]
    def handler(req):
        n[0] += 1
        return sse_resp(SSE_TOOL if n[0] == 1 else SSE_TEXT)
    assert await make(handler).answer([], "q", 3) == "Xin chào"
    assert calls == [("web_search", {"query": "python"})]

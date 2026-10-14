import httpx
import pytest

from app import llm as llm_mod
from app.llm import Gemini, LLMError


def make(handler):
    return Gemini("KEY", "m", "sys", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def text(t):
    return {"candidates": [{"content": {"parts": [{"text": t}]}}]}


async def test_plain_answer():
    g = make(lambda r: httpx.Response(200, json=text("chào")))
    assert await g.answer([], "hi", 3) == "chào"


async def test_tool_round_then_answer(monkeypatch):
    calls = []
    async def fake_tool(name, args):
        calls.append((name, args))
        return {"results": [{"title": "t", "url": "u", "snippet": "s"}]}
    monkeypatch.setattr(llm_mod, "run_tool", fake_tool)

    seen = []
    def handler(req):
        import json
        body = json.loads(req.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "web_search", "args": {"query": "q"}}}]}}]})
        return httpx.Response(200, json=text("xong"))
    g = make(handler)
    assert await g.answer([], "hỏi", 3) == "xong"
    assert calls == [("web_search", {"query": "q"})]
    last = seen[-1]["contents"][-1]
    assert "functionResponse" in last["parts"][0]


async def test_api_key_in_header_not_url():
    got = {}
    def handler(req):
        got["url"], got["h"] = str(req.url), req.headers.get("x-goog-api-key")
        return httpx.Response(200, json=text("ok"))
    await make(handler).answer([], "q", 1)
    assert "KEY" not in got["url"] and got["h"] == "KEY"


async def test_tool_loop_is_bounded(monkeypatch):
    async def fake_tool(name, args):
        return {"results": []}
    monkeypatch.setattr(llm_mod, "run_tool", fake_tool)
    n = [0]
    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "web_search", "args": {"query": "q"}}}]}}]})
    g = make(handler)
    await g.answer([], "q", 2)
    assert n[0] == 2 + 1 + 1  # 3 vòng + 1 lần ép trả lời


@pytest.mark.parametrize("status,needle", [(429, "quota"), (404, "model"), (401, "Khóa"), (500, "500")])
async def test_http_errors_become_llmerror(status, needle):
    g = make(lambda r: httpx.Response(status, text="BODY-SECRET"))
    with pytest.raises(LLMError) as e:
        await g.answer([], "q", 1)
    assert needle in str(e.value) and "BODY-SECRET" not in str(e.value)


async def test_empty_candidates_is_error():
    g = make(lambda r: httpx.Response(200, json={"candidates": []}))
    with pytest.raises(LLMError):
        await g.answer([], "q", 1)

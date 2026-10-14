import asyncio
import os
import tempfile
from types import SimpleNamespace

import httpx

from app import tools
from app.bot import SearchBot
from app.config import Config
from app.llm import LLMError
from app.store import ThreadStore


# ---- read_page: SSRF qua redirect
async def test_read_page_blocks_redirect_to_internal(monkeypatch):
    monkeypatch.setattr(tools, "is_safe_url", lambda u: "internal" not in u)
    def handler(req):
        if "public" in str(req.url):
            return httpx.Response(302, headers={"location": "http://internal.host/secret"})
        return httpx.Response(200, text="SECRET")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    r = await tools.read_page("http://public.example/", client=client)
    assert "error" in r and "SECRET" not in str(r)


async def test_read_page_extracts_text(monkeypatch):
    monkeypatch.setattr(tools, "is_safe_url", lambda u: True)
    html = "<html><body><article><p>" + "Nội dung quan trọng. " * 30 + "</p></article></body></html>"
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html)))
    r = await tools.read_page("https://ok.example/", client=client)
    assert "Nội dung quan trọng" in r["text"]


async def test_read_page_http_error(monkeypatch):
    monkeypatch.setattr(tools, "is_safe_url", lambda u: True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert (await tools.read_page("https://ok.example/", client=client))["error"] == "HTTP 404"


async def test_read_page_redirect_loop(monkeypatch):
    monkeypatch.setattr(tools, "is_safe_url", lambda u: True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "https://a.example/"})))
    assert "redirect" in (await tools.read_page("https://a.example/", client=client))["error"]


async def test_search_failure_is_contained(monkeypatch):
    def boom(q, n=6):
        raise RuntimeError("ratelimit")
    monkeypatch.setattr(tools, "_search_sync", boom)
    r = await tools.web_search("x")
    assert r == {"error": "search thất bại: RuntimeError"}


async def test_unknown_tool():
    assert "error" in await tools.run_tool("rm_rf", {})


# ---- bot với đối tượng giả
BOT_USER = SimpleNamespace(id=42)


class FakeThread:
    def __init__(self, id=900):
        self.id, self.sent = id, []
    async def send(self, t): self.sent.append(t)
    def typing(self):
        class C:
            async def __aenter__(s): return None
            async def __aexit__(s, *a): return False
        return C()


def cfg(**kw):
    base = dict(discord_token="t", gemini_api_key="k", owner_id=1)
    base.update(kw)
    return Config(**base)


class FakeLLM:
    def __init__(self, result=None, exc=None): self.result, self.exc, self.calls = result, exc, []
    async def answer(self, history, q, rounds):
        self.calls.append(q)
        if self.exc: raise self.exc
        return self.result


def make_bot(llm, **kw):
    b = SearchBot(cfg(**kw), llm=llm, store=ThreadStore(os.path.join(tempfile.mkdtemp(), "t.json")))
    b._connection.user = BOT_USER  # discord.Client.user là property đọc từ _connection
    return b


def msg(content, author_id=1, thread=None, bot=42):
    thr = thread or FakeThread()
    async def create_thread(name, auto_archive_duration): return thr
    async def reply(t, mention_author=False): thr.sent.append(("reply", t))
    bot_user = SimpleNamespace(id=bot)
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id, bot=False, display_name="Tí"),
        content=content, mentions=[bot_user] if f"<@{bot}>" in content else [],
        channel=SimpleNamespace(id=5, parent_id=None), create_thread=create_thread, reply=reply,
    ), thr


async def test_bot_answers_in_thread_and_labels_owner():
    llm = FakeLLM("trả lời")
    b = make_bot(llm)
    m, thr = msg("<@42> giá vàng?")
    m.mentions = [BOT_USER]
    await b.on_message(m)
    assert thr.sent == ["trả lời"]
    assert "| 1 | chủ bot]" in llm.calls[0] and "giá vàng?" in llm.calls[0]


async def test_bot_llm_error_shows_friendly_message_only():
    b = make_bot(FakeLLM(exc=LLMError("Hết quota")))
    m, thr = msg("<@42> hi"); m.mentions = [BOT_USER]
    await b.on_message(m)
    assert thr.sent == ["Hết quota"]


async def test_bot_unexpected_error_hides_details():
    b = make_bot(FakeLLM(exc=ValueError("token=AIzaSECRET")))
    m, thr = msg("<@42> hi"); m.mentions = [BOT_USER]
    await b.on_message(m)
    assert "AIzaSECRET" not in str(thr.sent) and thr.sent


async def test_bot_ignores_not_allowed_user_and_bots_and_unmentioned():
    llm = FakeLLM("x")
    b = make_bot(llm, allowed_user_ids=frozenset({1}))
    m, thr = msg("<@42> hi", author_id=2); m.mentions = [BOT_USER]
    await b.on_message(m)
    m2, _ = msg("không tag ai")
    await b.on_message(m2)
    m3, _ = msg("<@42> hi"); m3.author.bot = True; m3.mentions = [BOT_USER]
    await b.on_message(m3)
    assert llm.calls == []


async def test_bot_rate_limit():
    llm = FakeLLM("x")
    b = make_bot(llm, rate_limit_per_min=1)
    for _ in range(2):
        m, thr = msg("<@42> hi"); m.mentions = [BOT_USER]
        await b.on_message(m)
    assert len(llm.calls) == 1


async def test_bot_empty_question_prompts():
    llm = FakeLLM("x")
    b = make_bot(llm)
    m, thr = msg("<@42>"); m.mentions = [BOT_USER]
    await b.on_message(m)
    assert llm.calls == [] and thr.sent and thr.sent[0][0] == "reply"


# ---- slash command và thread tracking
class FakeInteraction:
    def __init__(self, channel_id):
        self.channel = SimpleNamespace(id=channel_id)
        self.sent = []
        outer = self
        class Resp:
            async def send_message(self, t, ephemeral=False): outer.sent.append((t, ephemeral))
        self.response = Resp()


async def test_slash_commands_registered():
    b = make_bot(FakeLLM("x"))
    assert {c.name for c in b.tree.get_commands()} == {"reset", "help"}


async def test_reset_clears_only_in_bot_thread():
    b = make_bot(FakeLLM("x"))
    b.history.add_turn(900, "q", "a")
    b.bot_threads.add(900)
    cmd = b.tree.get_command("reset")
    i = FakeInteraction(900)
    await cmd.callback(i)
    assert b.history.get(900) == [] and i.sent[0][1] is True
    i2 = FakeInteraction(12345)
    await cmd.callback(i2)
    assert "thread của bot" in i2.sent[0][0]


async def test_followup_in_known_thread_needs_no_mention():
    import discord

    class FakeDiscordThread(discord.Thread):  # isinstance(.., discord.Thread) đúng, bỏ qua __init__ thật
        def __init__(self, thr):
            self._thr = thr
        @property
        def id(self): return self._thr.id
        @property
        def parent_id(self): return None
        async def send(self, t): await self._thr.send(t)
        def typing(self): return self._thr.typing()

    llm = FakeLLM("tiếp")
    b = make_bot(llm)
    b.bot_threads.add(900)
    m, thr = msg("hỏi tiếp không tag")
    m.channel = FakeDiscordThread(thr)
    await b.on_message(m)
    assert llm.calls and thr.sent == ["tiếp"]


async def test_unknown_thread_without_mention_is_ignored():
    import discord

    class FakeDiscordThread(discord.Thread):
        def __init__(self, thr): self._thr = thr
        @property
        def id(self): return self._thr.id
        @property
        def parent_id(self): return None

    llm = FakeLLM("x")
    b = make_bot(llm)
    m, thr = msg("không tag, thread lạ")
    m.channel = FakeDiscordThread(thr)
    await b.on_message(m)
    assert llm.calls == []

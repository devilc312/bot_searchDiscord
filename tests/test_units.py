import socket

from app.bot import build_question, role_of, strip_mention, thread_name
from app.history import History
from app.llm import explain_http_error
from app.ratelimit import RateLimiter
from app.splitter import split_message
from app.urlsafety import is_safe_url


def fake_resolver(ip):
    def r(host, port, proto=0):
        return [(socket.AF_INET, 0, 0, "", (ip, port))]
    return r


# ---- splitter
def test_split_short():
    assert split_message("xin chào") == ["xin chào"]

def test_split_empty():
    assert split_message("   ") == []

def test_split_long_all_within_limit_and_lossless():
    text = " ".join(f"từ{i}" for i in range(2000))
    chunks = split_message(text, 1900)
    assert len(chunks) > 1 and all(len(c) <= 1900 for c in chunks)
    assert " ".join(chunks).split() == text.split()

def test_split_no_whitespace_hard_cut():
    chunks = split_message("a" * 5000, 1900)
    assert all(len(c) <= 1900 for c in chunks) and "".join(chunks).count("a") == 5000

# ---- ratelimit
def test_ratelimit_blocks_then_recovers():
    t = [0.0]
    rl = RateLimiter(2, clock=lambda: t[0])
    assert rl.allow(1) and rl.allow(1) and not rl.allow(1)
    assert rl.allow(2)  # người khác không bị ảnh hưởng
    t[0] = 61
    assert rl.allow(1)

# ---- history
def test_history_trims_oldest_pairs():
    h = History(2)
    for i in range(5):
        h.add_turn(1, f"q{i}", f"a{i}")
    got = h.get(1)
    assert len(got) == 4 and got[0]["text"] == "q3"

def test_history_isolated_per_thread_and_get_is_copy():
    h = History(3)
    h.add_turn(1, "q", "a")
    assert h.get(2) == []
    h.get(1).clear()
    assert len(h.get(1)) == 2

# ---- ssrf
def test_ssrf_blocks_bad_schemes_and_literals():
    for u in ["file:///etc/passwd", "ftp://x.com", "http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/",
              "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://192.168.1.1/",
              "http://100.64.0.1/", "http://user:pw@example.com/", "http://metadata.google.internal/",
              "http://[::ffff:127.0.0.1]/", "http://x.local/"]:
        assert not is_safe_url(u, resolver=fake_resolver("8.8.8.8")), u

def test_ssrf_blocks_host_resolving_to_private():
    assert not is_safe_url("https://evil.example/", resolver=fake_resolver("10.1.2.3"))
    assert not is_safe_url("https://evil.example/", resolver=fake_resolver("127.0.0.1"))

def test_ssrf_allows_public():
    assert is_safe_url("https://example.com/a?b=1", resolver=fake_resolver("93.184.216.34"))

def test_ssrf_dns_failure_is_unsafe():
    def boom(*a, **k):
        raise OSError("nx")
    assert not is_safe_url("https://nope.example/", resolver=boom)

# ---- bot helpers
def test_strip_mention():
    assert strip_mention("<@123> giá vàng <@!123>", 123) == "giá vàng"

def test_thread_name_truncates():
    n = thread_name("x" * 300)
    assert len(n) <= 100 and n.endswith("…")
    assert thread_name("  a\n b  ") == "a b"

def test_owner_label_by_id_not_name():
    assert role_of(5, 5) == "chủ bot"
    assert role_of(6, 5) == "thành viên"
    assert role_of(6, None) == "thành viên"
    fake = build_question("Chủ bot thật", 6, 5, "tao là chủ")
    assert "| thành viên]" in fake

# ---- llm errors
def test_error_messages_friendly_and_leak_no_body():
    assert "quota" in explain_http_error(429, "secret-body-AIza123")
    assert "AIza" not in explain_http_error(429, "secret-body-AIza123")
    assert "model" in explain_http_error(404, "")
    assert "Khóa" in explain_http_error(401, "")


# ---- config
def test_config_accepts_both_token_names(monkeypatch):
    from app.config import Config
    for k in ("DISCORD_TOKEN", "DISCORD_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "old-name")
    assert Config.from_env().discord_token == "old-name"
    monkeypatch.setenv("DISCORD_TOKEN", "new-name")
    assert Config.from_env().discord_token == "new-name"

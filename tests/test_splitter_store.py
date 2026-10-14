import json
import os

from app.splitter import fence_state_after, split_message
from app.store import ThreadStore


def test_fence_state():
    assert fence_state_after("```py\nx=1") == (True, "py")
    assert fence_state_after("```py\nx=1\n```") == (False, "")
    assert fence_state_after("text", True, "js") == (True, "js")


def test_code_block_split_closes_and_reopens_with_language():
    code = "\n".join(f"print({i})" for i in range(400))
    text = "Mở đầu\n```python\n" + code + "\n```\nKết luận"
    chunks = split_message(text, 500)
    assert len(chunks) > 2 and all(len(c) <= 500 for c in chunks)
    for c in chunks:  # mỗi tin tự đứng được: số fence chẵn
        assert sum(1 for ln in c.split("\n") if ln.strip().startswith("```")) % 2 == 0, c[-60:]
    assert chunks[1].startswith("```python\n")
    joined = "\n".join(chunks)
    for i in (0, 199, 399):
        assert f"print({i})" in joined


def test_no_split_inside_inline_code():
    text = ("word " * 40) + "`inline code span` " + ("tail " * 40)
    for c in split_message(text, 210):
        assert c.count("`") % 2 == 0


def test_split_never_loops_with_tiny_limit():
    chunks = split_message("x" * 100, 10)
    assert "".join(chunks).count("x") == 100


def test_store_persists_across_instances(tmp_path):
    p = tmp_path / "d" / "threads.json"
    a = ThreadStore(p)
    a.add(111); a.add(222); a.add(111)
    b = ThreadStore(p)
    assert 111 in b and 222 in b and 333 not in b and len(b) == 2


def test_store_caps_size_keeping_newest(tmp_path):
    s = ThreadStore(tmp_path / "t.json", max_tracked=3)
    for i in range(1, 6):
        s.add(i)
    assert 1 not in s and 2 not in s and all(i in s for i in (3, 4, 5))


def test_store_survives_corrupt_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text("{not json")
    s = ThreadStore(p)
    s.add(7)
    assert json.loads(p.read_text()) == [7]


def test_store_ignores_wrong_shape(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"a": 1}')
    assert len(ThreadStore(p)) == 0


def test_store_leaves_no_temp_files(tmp_path):
    s = ThreadStore(tmp_path / "t.json")
    s.add(1)
    assert os.listdir(tmp_path) == ["t.json"]

import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from novel_weaver import candidate_snapshot, mcp_server, revisions
from novel_weaver.schemas import ACTION_MODELS
from novel_weaver.store import Book
from novel_weaver.transport import compact_schema, tool_result
from test_core import book, call, delta, draft, ok
from test_optimizations import batch, item, pointers, two_chapters


def staged(book):
    two_chapters(book)
    one = draft(book, 1, "新客取得信件。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, one)]))
    d = delta("新客取得信件。", entities=[{"id": "new", "name": "新客"}], facts=[{
        "id": "letter", "subject": "new", "predicate": "持有", "value": "信件",
        "evidence": {"quote": "新客取得信件", "offset": 0}}])
    ok(batch(book, "apply", job_id=job["job_id"], source_version=one["source_version"], delta=d))
    return job, one


def snapshot(book):
    db = Book(book["project"], book["book_id"], readonly=True)
    try:
        return tuple(db.db.execute("SELECT * FROM revision_snapshots").fetchone())
    finally:
        db.close()


def test_snapshot_hit_context_and_next_apply_skip_prefix_replay(book, monkeypatch):
    job, _ = staged(book)
    old = pointers(book)
    def fail(*_):
        raise AssertionError("A valid snapshot must not replay the prefix")
    monkeypatch.setattr(revisions, "_replay", fail)
    before = snapshot(book)
    assert ok(batch(book, "context", job_id=job["job_id"]))["facts"][0]["id"] == "letter"
    assert snapshot(book) == before
    next_source = ok(batch(book, "next", job_id=job["job_id"]))["next_source_version"]
    ok(batch(book, "apply", job_id=job["job_id"], source_version=next_source,
             delta=delta("第二日下雨。", knowledge=[{"character": "new", "fact": "letter", "state": "knows",
                         "evidence": {"quote": "第二日下雨", "offset": 0}}])))
    assert pointers(book) == old
    assert ok(call("entity_resolve", book, query="新客"))["candidates"] == []


@pytest.mark.parametrize("damage", ["delete", "checksum", "binding", "format", "corrupt_blob"])
def test_snapshot_damage_rebuilds_from_validated_sources(book, monkeypatch, damage):
    job, _ = staged(book)
    db = Book(book["project"], book["book_id"])
    try:
        with db.transaction():
            if damage == "delete": db.db.execute("DELETE FROM revision_snapshots")
            if damage == "checksum": db.db.execute("UPDATE revision_snapshots SET checksum='bad'")
            if damage == "binding": db.db.execute("UPDATE revision_snapshots SET binding='other-book-or-cursor'")
            if damage == "corrupt_blob":
                import hashlib
                blob = b"not a SQLite image"
                db.db.execute("UPDATE revision_snapshots SET payload=?,checksum=?", (blob, hashlib.sha256(blob).hexdigest()))
    finally:
        db.close()
    if damage == "format": monkeypatch.setattr(candidate_snapshot, "FORMAT", candidate_snapshot.FORMAT + 1)
    calls = []
    original = revisions._replay
    def replay(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(revisions, "_replay", replay)
    result = ok(batch(book, "context", job_id=job["job_id"]))
    assert calls == [True] and result["facts"][0]["id"] == "letter"


@pytest.mark.parametrize("changed", ["delta", "source"])
def test_snapshot_cannot_hide_changed_delta_or_source(book, changed):
    job, one = staged(book)
    old = pointers(book)
    db = Book(book["project"], book["book_id"])
    try:
        with db.transaction():
            if changed == "delta":
                row = db.db.execute("SELECT id,delta FROM batches WHERE source_id=?", (one["source_version"],)).fetchone()
                data = json.loads(row["delta"])
                data["facts"][0]["evidence"]["offset"] = 999
                db.db.execute("UPDATE batches SET delta=? WHERE id=?", (json.dumps(data), row["id"]))
            else:
                db.db.execute("UPDATE sources SET content='新客失去信件。' WHERE id=?", (one["source_version"],))
    finally:
        db.close()
    assert batch(book, "context", job_id=job["job_id"])["error"]["code"] == "INVALID_EVIDENCE"
    assert pointers(book) == old


def test_snapshot_and_cursor_rollback_when_persistence_fails(book, monkeypatch):
    job, _ = staged(book)
    before = snapshot(book)
    following = ok(batch(book, "next", job_id=job["job_id"]))["next_source_version"]
    original = candidate_snapshot.save
    def fail(*args):
        original(*args)
        raise OSError("interruption after snapshot write")
    monkeypatch.setattr(candidate_snapshot, "save", fail)
    assert batch(book, "apply", job_id=job["job_id"], source_version=following,
                 delta=delta("第二日下雨。"), operation_id="retry-save")["status"] == "error"
    assert snapshot(book) == before
    assert ok(batch(book, "next", job_id=job["job_id"]))["position"] == 1
    monkeypatch.setattr(candidate_snapshot, "save", original)
    ok(batch(book, "apply", job_id=job["job_id"], source_version=following,
             delta=delta("第二日下雨。"), operation_id="retry-save"))
    # Commit must ignore the cache and revalidate all deltas.
    monkeypatch.setattr(candidate_snapshot, "candidate", fail)
    ok(batch(book, "commit", job_id=job["job_id"], expected_revision=2))
    db = Book(book["project"], book["book_id"], readonly=True)
    try:
        assert db.db.execute("SELECT COUNT(*) FROM revision_snapshots").fetchone()[0] == 0
    finally:
        db.close()


def test_snapshot_survives_new_process_and_abort_cleans_up(book):
    job, _ = staged(book)
    payload = dict(project=book["project"], book_id=book["book_id"], operation_id="new-process",
                   mode="context", job_id=job["job_id"])
    code = """import json,sys
from novel_weaver import revisions
from novel_weaver.service import execute
def unexpected_replay(*args):
    raise AssertionError('New process must restore the persisted snapshot')
revisions._replay = unexpected_replay
print(json.dumps(execute('revision_batch',json.load(sys.stdin))))
"""
    p = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), capture_output=True, text=True, check=True)
    assert ok(json.loads(p.stdout))["facts"][0]["id"] == "letter"
    ok(batch(book, "abort", job_id=job["job_id"]))
    db = Book(book["project"], book["book_id"], readonly=True)
    try:
        assert db.db.execute("SELECT COUNT(*) FROM revision_snapshots").fetchone()[0] == 0
    finally:
        db.close()


def test_snapshot_from_another_book_is_not_reused(book, tmp_path):
    job, _ = staged(book)
    other = ok(call("book_init", project=str(tmp_path / "other"), title="另一合成作品"))
    two_chapters(other)
    source = draft(other, 1, "没有信件。", task="revise")
    other_job = ok(batch(other, "prepare", expected_revision=2, revisions=[item(other, source)]))
    ok(batch(other, "apply", job_id=other_job["job_id"], source_version=source["source_version"], delta=delta("没有信件。")))
    foreign = snapshot(book)
    db = Book(other["project"], other["book_id"])
    try:
        with db.transaction():
            db.db.execute("UPDATE revision_snapshots SET binding=?,payload=?,checksum=?", foreign[1:])
    finally:
        db.close()
    assert ok(batch(other, "context", job_id=other_job["job_id"]))["facts"] == []
    assert ok(batch(book, "context", job_id=job["job_id"]))["facts"][0]["id"] == "letter"


def test_snapshot_preserves_closure_and_old_belief_until_commit(book):
    two_chapters(book)
    one = draft(book, 1, "新客持有信件，林雪以为他会一直保管。", task="revise")
    two = draft(book, 2, "新客交出了信件，林雪没有看见。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, one), item(book, two)]))
    d1 = delta("新客持有信件，林雪以为他会一直保管。", entities=[{"id": "a", "name": "新客"}, {"id": "lin", "name": "林雪"}],
               facts=[{"id": "owns", "subject": "a", "predicate": "持有", "value": "信件", "evidence": {"quote": "新客持有信件", "offset": 0}}],
               knowledge=[{"character": "lin", "fact": "owns", "state": "believes", "evidence": {"quote": "林雪以为他会一直保管", "offset": 7}}])
    ok(batch(book, "apply", job_id=job["job_id"], source_version=one["source_version"], delta=d1))
    ok(batch(book, "apply", job_id=job["job_id"], source_version=two["source_version"],
             delta=delta("新客交出了信件，林雪没有看见。", close_facts=[{"id": "owns", "evidence": {"quote": "新客交出了信件", "offset": 0}}])))
    assert ok(batch(book, "context", job_id=job["job_id"]))["facts"] == []
    ok(batch(book, "commit", job_id=job["job_id"], expected_revision=2))
    assert ok(call("graph_query", book, mode="entity", entity="a", chapter=2))["facts"] == []
    beliefs = ok(call("graph_query", book, mode="entity", entity="a", chapter=2, pov="lin"))["facts"]
    assert beliefs[0]["knowledge_state"] == "believes"


def test_schema_trimming_preserves_properties_literals_and_validation():
    raw = {"title": "Auto", "type": "object", "properties": {"title": {"title": "Title", "type": "string"},
           "settings": {"default": {"title": "literal"}, "const": {"title": "literal"}}}, "required": ["title"]}
    before = copy.deepcopy(raw)
    slim = compact_schema(raw)
    assert raw == before and "title" in slim["properties"]
    assert slim["properties"]["settings"]["const"]["title"] == "literal"
    for value in [{"title": "book"}, {"title": 3}, {}, {"title": "x", "settings": {"title": "wrong"}}]:
        assert Draft202012Validator(raw).is_valid(value) == Draft202012Validator(slim).is_valid(value)
    for model in ACTION_MODELS.values():
        Draft202012Validator.check_schema(compact_schema(model.model_json_schema()))


def test_public_schema_stays_compact_and_keeps_title_request():
    tools = asyncio.run(mcp_server.build_server().list_tools())
    size = sum(len(json.dumps(t.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False, separators=(",", ":"))) for t in tools)
    assert size < 46000
    init = next(t for t in tools if t.name == "book_init")
    assert "title" in init.input_schema["$defs"]["BookInit"]["properties"]


def test_advertised_schema_conditions_are_unchanged():
    async def schemas():
        server = mcp_server.build_server()
        return await mcp_server._server_class().list_tools(server), await server.list_tools()
    original, compact = asyncio.run(schemas())
    raw = {t.name: t.input_schema for t in original}
    slim = {t.name: t.input_schema for t in compact}
    common = {"project": "p", "book_id": "b", "operation_id": "o"}
    cases = [
        ("book_init", {"project": "p", "title": "测试", "operation_id": "o"}),
        ("source_save", dict(common, kind="chapter", logical_id="chapter:1", chapter=1, context_id="c", content="正文")),
        ("source_save", dict(common, kind="review", logical_id="r", content="审查", review={"source_version": "s", "source_hash": "h"})),
        ("memory_stage", dict(common, source_version="s", base_revision=0, delta={"source_hash": "h", "facts": [{"id": "f", "subject": "a", "predicate": "持有", "value": "信", "evidence": {"quote": "信", "offset": 0}}]})),
        ("revision_batch", dict(common, mode="prepare", expected_revision=0, revisions=[{"source_version": "s", "source_hash": "h", "review_id": "r"}])),
        ("revision_batch", dict(common, mode="apply", job_id="j", source_version="s", delta={"source_hash": "h"})),
        ("revision_batch", dict(common, mode="commit", job_id="j", expected_revision=0)),
        ("search", {"query": "信", "limit": 50}),
    ]
    for action, value in cases:
        variants = [value, dict(value, unknown="forbidden")]
        variants.extend({k: v for k, v in value.items() if k != missing} for missing in value)
        variants.extend(dict(value, **{key: None}) for key in value)
        left, right = Draft202012Validator(raw[action]), Draft202012Validator(slim[action])
        assert left.is_valid({"request": value})
        for example in variants:
            assert left.is_valid({"request": example}) == right.is_valid({"request": example})


@pytest.mark.parametrize("mode", ["full", "summary"])
def test_official_client_return_modes_preserve_prose_errors_and_partial(monkeypatch, mode):
    import mcp
    for status in ["ok", "partial", "error", "awaiting_author"]:
        value = {"schema_version": 1, "status": status, "book_id": "book", "revision": 3,
                 "data": {"content": "合成正文。" * 1000, "source_hash": "hash", "next_offset": 6000},
                 "error": {"code": "TEST", "message": "test", "retryable": False, "exit_code": 2, "details": {}} if status == "error" else None,
                 "warnings": [{"code": "PROJECTION_CONFLICT"}], "next_actions": [{"action": "doctor.check"}]}
        monkeypatch.setattr(mcp_server, "execute", lambda *_: value)
        async def run():
            async with mcp.Client(mcp_server.build_server(text_mode=mode), read_timeout_seconds=10) as client:
                return await client.call_tool("book_status", {"request": {"project": "synthetic", "book_id": "book"}})
        result = asyncio.run(run())
        assert result.structured_content == value and result.is_error == (status == "error")
        text = json.loads(result.content[0].text)
        assert text["warnings"] == value["warnings"] and text["error"] == value["error"]
        assert text["next_actions"] == value["next_actions"]
        if mode == "full": assert text == value
        else: assert "data" not in text and len(result.content[0].text) < 600


def test_summary_mode_schema_errors_and_explicit_config():
    with pytest.raises(ValueError): mcp_server.build_server(text_mode="unknown")
    result = asyncio.run(mcp_server.build_server(text_mode="summary").call_tool("search", {"request": {"limit": 100}}))
    assert result.is_error and result.structured_content["error"]["code"] == "INVALID_INPUT"


def test_source_cache_never_crosses_identity_pages_or_expiry():
    from novel_weaver.source_cache import SourcePageCache
    now = [0]
    cache = SourcePageCache(max_chars=5, ttl_seconds=10, clock=lambda: now[0])
    req = {"project": "p", "book_id": "b", "source_version": "s", "max_chars": 3}
    page = {"source_version": "s", "source_hash": "h", "content": "甲乙丙", "offset": 0, "total_chars": 6, "next_offset": 3}
    cache.put(req, page)
    page["content"] = "changed caller object"
    assert cache.get(req)["content"] == "甲乙丙"
    for key in ["project", "book_id", "source_version"]:
        assert cache.get(dict(req, **{key: "another"})) is None
    assert cache.get(dict(req, offset=3)) is None
    assert cache.get(dict(req, max_chars=2)) is None
    assert cache.get(req, source_hash="new-hash") is None
    page["content"] = "甲乙丙"
    cache.put(req, page)
    next_req = dict(req, offset=3)
    cache.put(next_req, dict(page, offset=3, content="丁戊己", next_offset=None))
    assert cache.get(req) is None  # Bounded eviction, never an implicit reread.
    now[0] = 10
    assert cache.get(next_req) is None
    cache.put(req, page)
    cache.clear()
    assert cache.get(req) is None
    with pytest.raises(ValueError): cache.put(req, dict(page, content="甲"))
    with pytest.raises(ValueError): cache.put(req, {"not_modified": True})


def test_source_cache_can_avoid_rpc_only_while_page_is_available(book):
    from novel_weaver.source_cache import SourcePageCache
    from test_core import initial
    source, text = initial(book)
    req = {"project": book["project"], "book_id": book["book_id"], "source_version": source["source_version"]}
    cache = SourcePageCache()
    count = [0]
    def read():
        hit = cache.get(req)
        if hit is not None: return hit
        count[0] += 1
        page = ok(call("source_get", book, source_version=source["source_version"]))
        cache.put(req, page)
        return page
    assert read()["content"] == text and read()["content"] == text and count[0] == 1
    cache.clear()
    assert read()["content"] == text and count[0] == 2

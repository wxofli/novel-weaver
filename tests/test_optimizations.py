"""Integration tests use synthetic, isolated books, never an author's project."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from novel_weaver import mcp_server
from novel_weaver.schemas import Fact, MemorySync, RevisionBatch, SourceSave
from novel_weaver.service import execute
from novel_weaver.store import Book, digest
from test_core import accept, book, call, delta, draft, evidence, initial, ok


def batch(book, mode, **kwargs):
    return execute("revision_batch", dict(project=book["project"], book_id=book["book_id"],
                   operation_id=kwargs.pop("operation_id", uuid4().hex), mode=mode, **kwargs))


def review(book, source):
    return ok(call("source_save", book, kind="review", logical_id="review:" + source["source_version"],
                   content="核对了指定版本。", review={"source_version": source["source_version"],
                   "source_hash": source["source_hash"], "findings": []}))["review_id"]


def item(book, source):
    return {"source_version": source["source_version"], "source_hash": source["source_hash"], "review_id": review(book, source)}


def two_chapters(book):
    first, _ = initial(book)
    second = draft(book, 2, "第二日下雨。")
    ok(accept(book, second, "第二日下雨。"))
    return first, second


def pointers(book):
    db = Book(book["project"], book["book_id"], readonly=True)
    try:
        return dict(db.db.execute("SELECT logical_id,source_id FROM accepted"))
    finally:
        db.close()


def test_batch_replay_validates_new_prefix_and_commits_once(book):
    two_chapters(book)
    old = pointers(book)
    text1, text2 = "新客持有信件。", "新客读过信件。"
    one = draft(book, 1, text1, task="revise")
    two = draft(book, 2, text2, task="revise")
    revisions = [item(book, two), item(book, one)]  # Input order does not define replay order.
    payload = dict(expected_revision=2, revisions=revisions, operation_id="prepare-once", include_source=True, max_chars=3)
    prepared = batch(book, "prepare", **payload)
    assert batch(book, "prepare", **payload) == prepared
    job = ok(prepared)
    assert job["chapter"] == 1 and job["source"]["content"] == text1[:3]
    assert job["source"]["next_offset"] == 3
    jid = job["job_id"]
    assert pointers(book) == old
    assert batch(book, "commit", job_id=jid, expected_revision=2)["error"]["code"] == "REVISION_INCOMPLETE"
    assert call("memory_sync", book, mode="next", job_id=jid)["error"]["code"] == "REVISION_BATCH_REQUIRED"
    assert call("source_accept", book, source_version=one["source_version"], expected_revision=2)["error"]["code"] == "SYNC_IN_PROGRESS"
    d1 = delta(text1, entities=[{"id": "new", "name": "新客"}], facts=[{
        "id": "new-fact", "subject": "new", "predicate": "持有", "value": "信件", "evidence": evidence(text1, text1)}])
    applied = batch(book, "apply", job_id=jid, source_version=one["source_version"], delta=d1,
                    include_source=True, operation_id="apply-once")
    assert applied == batch(book, "apply", job_id=jid, source_version=one["source_version"], delta=d1,
                            include_source=True, operation_id="apply-once")
    assert applied["revision"] == 2 and pointers(book) == old
    assert ok(call("entity_resolve", book, query="新客"))["candidates"] == []
    candidate_context = ok(batch(book, "context", job_id=jid, entity_ids=["new"]))
    assert candidate_context["view"] == "candidate_author_memory"
    assert [f["id"] for f in candidate_context["facts"]] == ["new-fact"]
    assert batch(book, "context", job_id=jid, max_chars=1)["error"]["code"] == "BUDGET_EXCEEDED"
    assert pointers(book) == old
    resumed = ok(batch(book, "next", job_id=jid))  # New connection, persisted cursor.
    assert resumed["position"] == 1 and resumed["next_source_version"] == two["source_version"]
    d2 = delta(text2, knowledge=[{"character": "new", "fact": "new-fact", "state": "knows", "evidence": evidence(text2, text2)}])
    assert ok(batch(book, "apply", job_id=jid, source_version=two["source_version"], delta=d2))["ready_to_commit"]
    result = batch(book, "commit", job_id=jid, expected_revision=2, operation_id="commit-once")
    assert result == batch(book, "commit", job_id=jid, expected_revision=2, operation_id="commit-once")
    assert result["revision"] == 3 and ok(result)["chapters_replayed"] == 2
    assert pointers(book)["chapter:1"] == one["source_version"]
    assert ok(call("book_status", book))["active_job"] is None
    assert ok(call("graph_query", book, mode="entity", entity="new", pov="new", chapter=2))["facts"][0]["id"] == "new-fact"
    assert ok(call("entity_resolve", book, query="沈舟"))["candidates"] == []


@pytest.mark.parametrize("failure", ["order", "hash", "quote", "unknown_fact"])
def test_batch_bad_delta_does_not_advance_or_change_canon(book, failure):
    two_chapters(book)
    old = pointers(book)
    source = draft(book, 1, "替换正文。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, source)]))
    d = delta("替换正文。")
    sid = source["source_version"]
    if failure == "order":
        sid = old["chapter:2"]
    elif failure == "hash":
        d["source_hash"] = "wrong"
    elif failure == "quote":
        d.update(entities=[{"id": "x", "name": "甲"}], facts=[{"id": "f", "subject": "x", "predicate": "说", "value": "话",
                 "evidence": {"quote": "不存在", "offset": 0}}])
    else:
        d["knowledge"] = [{"character": "reader", "fact": "missing", "state": "knows", "evidence": evidence("替换正文。", "替换正文。")}]
    assert batch(book, "apply", job_id=job["job_id"], source_version=sid, delta=d)["status"] == "error"
    assert pointers(book) == old
    assert ok(batch(book, "next", job_id=job["job_id"]))["position"] == 0
    assert ok(call("graph_query", book, entity="jade"))["facts"][0]["id"] == "owns-a"
    assert ok(batch(book, "abort", job_id=job["job_id"]))["canon_unchanged"]
    assert ok(call("book_status", book))["active_job"] is None


@pytest.mark.parametrize("failure", ["review", "hash", "duplicate", "revision", "superseded", "context"])
def test_batch_rejects_stale_bindings_before_preparing(book, failure):
    two_chapters(book)
    one = draft(book, 1, "改稿一。", task="revise")
    two = draft(book, 2, "改稿二。", task="revise")
    a, b = item(book, one), item(book, two)
    items, rev = [a], 2
    if failure == "review": a["review_id"] = b["review_id"]
    if failure == "hash": a["source_hash"] = "wrong"
    if failure == "duplicate": items = [a, a]
    if failure == "revision": rev = 1
    if failure == "superseded": draft(book, 1, "再次修改。", task="revise")
    if failure == "context":
        setting = ok(call("source_save", book, kind="outline", logical_id="outline:new", content="新计划"))
        ok(call("source_accept", book, source_version=setting["source_version"], expected_revision=2))
        rev = 3
    assert batch(book, "prepare", revisions=items, expected_revision=rev)["status"] == "error"
    assert ok(call("book_status", book))["active_job"] is None


def test_batch_commit_failure_rolls_back_and_can_resume(book, monkeypatch):
    from novel_weaver import retrieval
    two_chapters(book)
    old = pointers(book)
    replacements = [draft(book, n, f"第{n}章改稿。", task="revise") for n in [1, 2]]
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, s) for s in replacements]))
    for n, s in enumerate(replacements, 1):
        ok(batch(book, "apply", job_id=job["job_id"], source_version=s["source_version"], delta=delta(f"第{n}章改稿。")))
    original = retrieval.index_source
    def fail(book, source):
        original(book, source)
        if source["chapter"] == 2:
            raise OSError("simulated interrupted commit")
    monkeypatch.setattr(retrieval, "index_source", fail)
    result = batch(book, "commit", job_id=job["job_id"], expected_revision=2, operation_id="retry")
    assert result["status"] == "error" and pointers(book) == old
    assert ok(call("graph_query", book, entity="jade"))["facts"]
    assert ok(batch(book, "next", job_id=job["job_id"]))["ready_to_commit"]
    monkeypatch.setattr(retrieval, "index_source", original)
    assert ok(batch(book, "commit", job_id=job["job_id"], expected_revision=2, operation_id="retry"))["accepted"]


def test_batch_rechecks_superseded_candidate_and_preserves_external_projection(book):
    two_chapters(book)
    source = draft(book, 2, "候选稿。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, source)]))
    ok(batch(book, "apply", job_id=job["job_id"], source_version=source["source_version"], delta=delta("候选稿。")))
    draft(book, 2, "更新候选。", task="revise")
    assert batch(book, "commit", job_id=job["job_id"], expected_revision=2)["error"]["code"] == "SUPERSEDED_DRAFT"
    ok(batch(book, "abort", job_id=job["job_id"]))
    current = draft(book, 2, "最终候选。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, current)]))
    ok(batch(book, "apply", job_id=job["job_id"], source_version=current["source_version"], delta=delta("最终候选。")))
    path = Path(book["project"]) / "正文/第0002章.md"
    path.write_text("作者手工修改", encoding="utf-8")
    result = batch(book, "commit", job_id=job["job_id"], expected_revision=2)
    assert result["status"] == "partial" and result["data"]["accepted"]
    assert path.read_text(encoding="utf-8") == "作者手工修改"


def test_entity_resolution_history_ambiguity_kind_and_pov(book, tmp_path):
    initial(book)
    text = "林雪后来被称为白鹭。另一人也被称为舟哥。"
    change = delta(text, entities=[{"id": "lin", "name": "林雪", "aliases": ["白鹭"]},
                                  {"id": "other", "name": "另一人", "aliases": ["舟哥"]}])
    ok(accept(book, draft(book, 2, text), text, change))
    assert ok(call("entity_resolve", book, query="白鹭", chapter=1))["candidates"] == []
    assert ok(call("entity_resolve", book, query="白鹭", chapter=2))["resolved_id"] == "lin"
    assert ok(call("entity_resolve", book, query="舟哥", chapter=2))["ambiguous"]
    assert ok(call("entity_resolve", book, query="玉佩", kind="character"))["candidates"] == []
    assert ok(call("entity_resolve", book, query="jade", pov="lin"))["candidates"] == []
    visible = ok(call("entity_resolve", book, query="jade", pov="reader"))
    assert visible["candidates"] == [{"id": "jade", "match": "id"}]
    assert ok(call("entity_resolve", book, query="jade", pov="reader", kind="character"))["candidates"] == []
    assert ok(call("entity_resolve", book, query="reader", pov="reader"))["candidates"] == []
    assert ok(call("entity_resolve", book, query="白", chapter=2))["resolved_id"] is None
    assert ok(call("entity_resolve", book, query="白鹭", pov="reader"))["candidates"] == []
    assert ok(call("entity_resolve", book, query="不存在"))["resolved_id"] is None
    assert call("entity_resolve", book, query="other", pov="other", chapter=1)["status"] == "error"
    other = ok(call("book_init", project=str(tmp_path / "other"), title="另一本"))
    assert ok(call("entity_resolve", other, query="白鹭"))["candidates"] == []


def test_conditional_source_read_is_explicit_version_and_book_bound(book, tmp_path):
    source, text = initial(book)
    page = ok(call("source_get", book, source_version=source["source_version"], max_chars=4))
    cached = ok(call("source_get", book, source_version=source["source_version"], max_chars=4, if_none_match=source["source_hash"]))
    assert cached["not_modified"] and "content" not in cached and cached["next_offset"] == page["next_offset"]
    full = ok(call("source_get", book, source_version=source["source_version"], if_none_match="stale"))
    assert full["content"] == text
    new = draft(book, 1, text + "新句。", task="revise")
    assert "content" in ok(call("source_get", book, source_version=new["source_version"], if_none_match=source["source_hash"]))
    other = ok(call("book_init", project=str(tmp_path / "other"), title="另一本"))
    assert call("source_get", other, source_version=source["source_version"], if_none_match=source["source_hash"])["status"] == "error"


def test_sync_returns_bounded_next_source(book):
    two_chapters(book)
    third = draft(book, 3, "第三日放晴。")
    ok(accept(book, third, "第三日放晴。"))
    replacement = draft(book, 1, "替换。", task="revise")
    result = ok(accept(book, replacement, "替换。"))
    next_item = ok(call("memory_sync", book, mode="next", job_id=result["job_id"], include_source=True, max_chars=2))
    assert next_item["source"]["content"] == "第二" and next_item["source"]["next_offset"] == 2
    applied = call("memory_sync", book, mode="apply", job_id=result["job_id"],
                   source_version=next_item["next_source_version"], base_revision=4,
                   delta=delta("第二日下雨。"), include_source=True)
    following = ok(applied)["source"]
    assert following["source_version"] == third["source_version"] and following["content"] == "第三日放晴。"
    assert following["source_hash"] == third["source_hash"]
    finished = ok(call("memory_sync", book, mode="apply", job_id=result["job_id"],
                      source_version=following["source_version"], base_revision=applied["revision"],
                      delta=delta("第三日放晴。"), include_source=True))
    assert finished["position"] == finished["total"] and "source" not in finished


def test_official_mcp_client_receives_safe_schema_error():
    import mcp
    request = {"project": "not-opened", "book_id": "b", "query": "PRIVATE-MANUSCRIPT", "limit": 100}
    async def run():
        async with mcp.Client(mcp_server.build_server(), read_timeout_seconds=10) as client:
            return await client.call_tool("search", {"request": request})
    result = asyncio.run(run())
    assert result.is_error and result.structured_content == execute("search", request)
    assert "PRIVATE-MANUSCRIPT" not in result.content[0].text


@pytest.mark.parametrize("action,payload", [
    ("source_save", {"kind": "review", "chapter": 1, "logical_id": "r", "content": "PRIVATE-MANUSCRIPT"}),
    ("memory_sync", {"mode": "apply", "job_id": "job"}),
    ("revision_batch", {"mode": "apply", "job_id": "job"}),
    ("search", {"query": "PRIVATE-MANUSCRIPT", "limit": 100}),
])
def test_mcp_and_core_validation_errors_match_without_echoing_inputs(action, payload):
    payload.update(project="nonexistent", book_id="b")
    if action != "search": payload["operation_id"] = "op"
    expected = execute(action, payload)
    result = asyncio.run(mcp_server.build_server().call_tool(action, {"request": payload}))
    got = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    assert got == expected and got["error"]["code"] == "INVALID_INPUT"
    assert "PRIVATE-MANUSCRIPT" not in json.dumps(got)
    assert got["error"]["details"]["issues"]


def test_schema_advertises_conditions_and_budget_error_gives_minimum(book):
    assert SourceSave.model_json_schema()["allOf"]
    assert Fact.model_json_schema()["oneOf"]
    assert MemorySync.model_json_schema()["allOf"]
    assert RevisionBatch.model_json_schema()["allOf"]
    result = call("context_build", book, chapter=1, task="write", budget_chars=500,
                  scene_brief={"goal": "目标" * 300})
    error = result["error"]
    assert error["code"] == "BUDGET_EXCEEDED" and error["details"]["minimum_required_chars"] > 500


@pytest.mark.parametrize("model,valid,invalid", [
    (Fact, {"id": "f", "subject": "a", "predicate": "状态", "value": "等待", "evidence": {"quote": "等", "offset": 0}}, {"object": "b"}),
    (SourceSave, {"project": "p", "book_id": "b", "operation_id": "o", "kind": "review", "logical_id": "r", "content": "", "review": {"source_version": "s", "source_hash": "h"}}, {"chapter": 1}),
    (MemorySync, {"project": "p", "book_id": "b", "operation_id": "o", "job_id": "j", "mode": "apply", "source_version": "s", "base_revision": 0, "delta": {"source_hash": "h"}}, {"delta": None}),
    (RevisionBatch, {"project": "p", "book_id": "b", "operation_id": "o", "mode": "prepare", "expected_revision": 1, "revisions": [{"source_version": "s", "source_hash": "h", "review_id": "r"}]}, {"revisions": []}),
])
def test_advertised_json_schema_accepts_valid_and_rejects_invalid_requests(model, valid, invalid):
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(model.model_json_schema())
    validator.validate(valid)
    model.model_validate(valid)
    bad = dict(valid, **invalid)
    assert list(validator.iter_errors(bad))
    with pytest.raises(ValueError):
        model.model_validate(bad)


def test_batch_fingerprint_conflict_does_not_overwrite_changed_canon(book):
    first, _ = two_chapters(book)
    source = draft(book, 2, "候选稿。", task="revise")
    job = ok(batch(book, "prepare", expected_revision=2, revisions=[item(book, source)]))
    ok(batch(book, "apply", job_id=job["job_id"], source_version=source["source_version"], delta=delta("候选稿。")))
    replacement = draft(book, 1, "外部变化。", task="revise")
    # Fault injection confined to the synthetic fixture: change a pointer without bumping revision.
    db = Book(book["project"], book["book_id"])
    try:
        with db.transaction():
            db.db.execute("UPDATE accepted SET source_id=? WHERE logical_id='chapter:1'", (replacement["source_version"],))
    finally:
        db.close()
    changed = pointers(book)
    assert changed["chapter:1"] != first["source_version"]
    assert batch(book, "commit", job_id=job["job_id"], expected_revision=2)["error"]["code"] == "REVISION_CONFLICT"
    assert pointers(book) == changed


def test_session_card_distinguishes_candidate_job():
    from novel_weaver.hooks import _session_card
    text = _session_card({"data": {"active_job": {"kind": "revision_batch", "position": 1, "total": 3}}}, "synthetic", "b")
    assert "canon unchanged" in text

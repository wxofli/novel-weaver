import json
from pathlib import Path

import httpx
import pytest

from novel_weaver.service import execute
from novel_weaver.store import Book, digest
from test_core import call, ok, draft, delta, evidence, accept, initial, stage_review, book


def test_stale_workflows_and_reserved_reader(book):
    source = draft(book, 1, "正文。")
    stage_review(book, source, "正文。")
    note = ok(call("source_save", book, kind="outline", logical_id="outline:one", content="计划"))
    ok(call("source_accept", book, source_version=note["source_version"], expected_revision=0))
    state = ok(call("book_status", book))
    assert "context.build" in state["pending_work"][0]["needs"]
    assert "memory.stage" in state["pending_work"][0]["needs"]
    assert not state["awaiting_author"]
    ok(call("context_build", book, chapter=1, pov="reader"))


def test_aliases_cannot_leak_backward_or_through_pov(book):
    initial(book)
    source = draft(book, 2, "沈舟又被称为面具客。")
    ok(accept(book, source, "沈舟又被称为面具客。", delta("沈舟又被称为面具客。", entities=[{"id": "shen", "name": "沈舟", "aliases": ["面具客"]}])))
    before = ok(call("graph_query", book, mode="entity", entity="shen", chapter=1))
    assert "面具客" not in before["entity"]["aliases"]
    assert "面具客" in ok(call("graph_query", book, mode="entity", entity="shen", chapter=2))["entity"]["aliases"]
    assert ok(call("graph_query", book, mode="entity", entity="shen", pov="reader", chapter=1))["entity"] == {"id": "shen"}


def test_context_scopes_reader_knowledge_to_relevant_entities(book):
    text = "甲看见许多不同的物品。"
    entities = [{"id": "a", "name": "甲"}] + [{"id": f"e{i}", "name": f"乙{i}"} for i in range(60)]
    facts = [{"id": f"f{i}", "subject": f"e{i}", "predicate": "状态", "value": "活跃", "evidence": evidence(text, text)} for i in range(60)]
    knowledge = [{"character": "reader", "fact": f"f{i}", "state": "knows", "evidence": evidence(text, text)} for i in range(60)]
    source = draft(book, 1, text)
    ok(accept(book, source, text, delta(text, entities=entities, facts=facts, knowledge=knowledge)))
    context = ok(call("context_build", book, chapter=2, entity_ids=["a"], query="甲"))
    assert context["knowledge"]["reader"]["known"] == []
    assert context["facts"] == []


def test_setting_replacement_retracts_old_assertions(book):
    def save_rule(text, value, revision):
        src = ok(call("source_save", book, kind="setting", logical_id="setting:rule", content=text))
        batch = ok(call("memory_stage", book, source_version=src["source_version"], base_revision=revision,
                        delta=delta(text, entities=[{"id": "rule", "name": "境界"}], facts=[{"id": value, "subject": "rule", "predicate": "上限", "value": value, "evidence": evidence(text, text)}])))
        return ok(call("source_accept", book, source_version=src["source_version"], batch_id=batch["batch_id"], expected_revision=revision))
    save_rule("境界上限为九。", "九", 0)
    src = draft(book, 1, "山门静默。")
    ok(accept(book, src, "山门静默。"))
    result = save_rule("境界上限为十。", "十", 2)
    assert result["job_id"]
    assert ok(call("graph_query", book, entity="rule", chapter=0))["facts"][0]["value"] == "十"
    job = ok(call("memory_sync", book, mode="next", job_id=result["job_id"]))
    ok(call("memory_sync", book, mode="apply", job_id=result["job_id"], source_version=job["next_source_version"], base_revision=3, delta=delta("山门静默。")))
    assert [f["value"] for f in ok(call("graph_query", book, entity="rule"))["facts"]] == ["十"]


def test_projection_retry_is_honest_and_crlf_is_preserved(book, monkeypatch):
    from novel_weaver import store
    source = draft(book, 1, "第一行\r\n第二行\r\n")
    batch, review, rev = stage_review(book, source, "第一行\r\n第二行\r\n")
    original = store.os.replace
    monkeypatch.setattr(store.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("occupied")))
    payload = dict(source_version=source["source_version"], batch_id=batch, review_id=review, expected_revision=rev, operation_id="same-accept")
    first = call("source_accept", book, **payload)
    assert first["status"] == "partial"
    assert call("source_accept", book, **payload)["status"] == "partial"
    monkeypatch.setattr(store.os, "replace", original)
    recovered = call("source_accept", book, **payload)
    assert recovered["status"] == "ok"
    assert not ok(call("book_status", book))["changed_projections"]
    assert (Path(book["project"]) / "正文" / "第0001章.md").read_bytes() == "第一行\r\n第二行\r\n".encode()


def test_knowledge_and_hook_results_expose_source_evidence(book):
    initial(book)
    facts = ok(call("graph_query", book, entity="jade", pov="reader"))["facts"]
    ev = facts[0]["knowledge_evidence"]
    source = ok(call("source_get", book, source_version=ev["source_id"]))
    assert source["content"][ev["offset"]:ev["offset"] + len(ev["quote"])] == ev["quote"]
    ctx = ok(call("context_build", book, chapter=2, entity_ids=["shen"]))
    assert ctx["hooks"][0]["source_version"]


def test_optional_vectors_rrf_profile_changes_and_fallback(book, monkeypatch):
    pytest.importorskip("sqlite_vec")
    initial(book)
    monkeypatch.setenv("NOVEL_EMBED_BASE_URL", "https://embedding.invalid/v1")
    monkeypatch.setenv("NOVEL_EMBED_MODEL", "test-model")

    def post(url, **kwargs):
        texts = kwargs["json"]["input"]
        data = [{"index": i, "embedding": [1.0, 0.25]} for i, _ in enumerate(texts)]
        return httpx.Response(200, json={"data": data}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    ok(call("index_update", book, embedding=True))
    result = call("search", book, query="玉佩")
    assert ok(result)["hits"][0]["channels"] == ["bm25", "vector"]
    assert ok(call("index_status", book))["pending_vectors"] == 0
    monkeypatch.setenv("NOVEL_EMBED_MODEL", "another-model")
    assert ok(call("index_status", book))["pending_vectors"] > 0
    result = call("search", book, query="玉佩")
    assert ok(result)["hits"][0]["channels"] == ["bm25"]
    assert result["warnings"][0]["code"] == "VECTOR_PROFILE_STALE"
    ok(call("index_rebuild", book, embedding=True))
    def fail(*a, **kw):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "post", fail)
    result = call("search", book, query="玉佩")
    assert ok(result)["hits"] and result["warnings"][0]["code"] == "VECTOR_DEGRADED"


def test_context_transaction_certifies_its_snapshot(book, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from novel_weaver import retrieval
    initial(book)
    outline = ok(call("source_save", book, kind="outline", logical_id="outline:later", content="新的章纲"))
    original = retrieval.search
    started = threading.Event()
    future = None
    executor = ThreadPoolExecutor(max_workers=1)
    def writer():
        started.set()
        return call("source_accept", book, source_version=outline["source_version"], expected_revision=1)
    def check_transaction(b, request):
        nonlocal future
        if future is None:
            future = executor.submit(writer)
            assert started.wait(2)
            # A real concurrent commit must not label old context as new.
            threading.Event().wait(0.15)
        return original(b, request)
    monkeypatch.setattr(retrieval, "search", check_transaction)
    try:
        context = ok(call("context_build", book, chapter=2))
        ok(future.result(timeout=10))
        assert context["revision"] == 1
        result = call("source_save", book, kind="chapter", logical_id="chapter:2", chapter=2, content="第二章", context_id=context["context_id"])
        assert result["error"]["code"] == "STALE_CONTEXT"
    finally:
        executor.shutdown(wait=True)


def test_missing_path_target_is_input_error(book):
    initial(book)
    assert call("graph_query", book, entity="shen", mode="path")["error"]["code"] == "TARGET_REQUIRED"


def test_history_masks_future_closure_and_paths_work(book):
    initial(book)
    text = "沈舟把玉佩交给林雪，林雪接住玉佩。"
    second = draft(book, 2, text)
    ok(accept(book, second, text, delta(text,
        close_facts=[{"id": "owns-a", "evidence": evidence(text, text)}],
        facts=[{"id": "owns-b", "subject": "lin", "predicate": "持有", "object": "jade", "evidence": evidence(text, text)}])))
    past = ok(call("graph_query", book, entity="shen", chapter=1))["facts"]
    assert past[0]["valid_to"] is None
    timeline = ok(call("graph_query", book, mode="timeline", entity="jade", chapter=1))["facts"]
    assert "closing_evidence" not in timeline[0] and timeline[0]["valid_to"] is None
    timeline = ok(call("graph_query", book, mode="timeline", entity="jade", chapter=2))["facts"]
    assert next(f for f in timeline if f["id"] == "owns-a")["closing_evidence"]["quote"] == text
    path = ok(call("graph_query", book, entity="lin", target="jade", mode="path", depth=1))["path"]
    assert path and path[0]["id"] == "owns-b"


def test_pov_and_history_do_not_resolve_future_alias(book):
    initial(book)
    source = draft(book, 2, "沈舟又被称为面具客。")
    ok(accept(book, source, "沈舟又被称为面具客。", delta("沈舟又被称为面具客。", entities=[{"id": "shen", "name": "沈舟", "aliases": ["面具客"]}])))
    assert call("graph_query", book, entity="面具客", chapter=1)["error"]["code"] == "ENTITY_NOT_FOUND"
    assert call("graph_query", book, entity="面具客", chapter=2, pov="reader")["error"]["code"] == "POV_ENTITY_ID_REQUIRED"


def test_first_chapter_can_be_revised_without_future_entity_metadata(book):
    initial(book)
    context = ok(call("context_build", book, task="revise", chapter=1, query="沈舟 玉佩"))
    assert context["as_of_chapter"] == 0
    assert context["facts"] == []


def test_concurrent_accept_is_one_commit_and_idempotent(book):
    from concurrent.futures import ThreadPoolExecutor
    source = draft(book, 1, "同一章正文。")
    batch, review, revision = stage_review(book, source, "同一章正文。")
    payload = dict(source_version=source["source_version"], batch_id=batch, review_id=review,
                   expected_revision=revision, operation_id="concurrent-one")
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: call("source_accept", book, **payload), range(3)))
    assert all(r == results[0] for r in results)
    assert results[0]["revision"] == 1
    assert ok(call("book_status", book))["memory_frontier"] == 1


def test_unseen_transition_preserves_character_belief_and_hides_closure(book):
    initial(book)
    text = "沈舟把玉佩暗中交给林雪。"
    src = draft(book, 2, text)
    ok(accept(book, src, text, delta(text, close_facts=[{"id": "owns-a", "evidence": evidence(text, text)}], facts=[{
        "id": "owns-b", "subject": "lin", "predicate": "持有", "object": "jade", "evidence": evidence(text, text)}])))
    assert ok(call("graph_query", book, entity="jade"))["facts"][0]["subject"] == "lin"
    pov = ok(call("graph_query", book, entity="jade", pov="reader"))["facts"]
    assert len(pov) == 1 and pov[0]["id"] == "owns-a" and pov[0]["valid_to"] is None
    timeline = ok(call("graph_query", book, entity="jade", pov="reader", mode="timeline"))["facts"]
    assert "closing_evidence" not in timeline[0] and timeline[0]["valid_to"] is None
    context = ok(call("context_build", book, chapter=3, pov="shen", entity_ids=["jade"]))
    assert context["knowledge"]["shen"]["known"][0]["id"] == "owns-a"
    assert "owns-b" in context["knowledge"]["shen"]["not_established_as_known"]
    text3 = "沈舟终于发现玉佩在林雪那里，先前的认知已经过时。"
    third = draft(book, 3, text3)
    ok(accept(book, third, text3, delta(text3, knowledge=[
        {"character": "shen", "fact": "owns-a", "state": "rejects", "evidence": evidence(text3, text3)},
        {"character": "shen", "fact": "owns-b", "state": "knows", "evidence": evidence(text3, text3)}])))
    assert [f["id"] for f in ok(call("graph_query", book, entity="jade", pov="shen"))["facts"]] == ["owns-b"]


def test_unreadable_projection_cannot_rollback_memory_commit(book, monkeypatch):
    from novel_weaver import store
    initial(book)
    second = draft(book, 2, "夜雨落下。")
    batch, review, rev = stage_review(book, second, "夜雨落下。")
    original = store.read_text_exact
    def occupied(path):
        if path.name == "第0001章.md":
            raise PermissionError("editor has this file locked")
        return original(path)
    monkeypatch.setattr(store, "read_text_exact", occupied)
    result = call("source_accept", book, source_version=second["source_version"], batch_id=batch, review_id=review, expected_revision=rev)
    ok(result)
    assert ok(call("book_status", book))["latest_chapter"] == 2
    assert ok(call("book_status", book))["changed_projections"][0]["code"] == "PROJECTION_UNREADABLE"
    monkeypatch.setattr(store, "read_text_exact", original)
    path = Path(book["project"]) / "正文" / "第0001章.md"
    path.write_bytes(b"\xff")
    assert ok(call("doctor_repair", book))["changed_projections"][0]["code"] == "PROJECTION_UNREADABLE"
    assert path.read_bytes() == b"\xff"


def test_doctor_restores_missing_projection(book):
    initial(book)
    path = Path(book["project"]) / "正文" / "第0001章.md"
    path.unlink()
    ok(call("doctor_repair", book))
    assert path.exists()

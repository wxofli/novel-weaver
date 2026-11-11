import json
from pathlib import Path
from uuid import uuid4

import pytest

from novel_weaver.service import execute
from novel_weaver.store import Book, digest


def call(action, book=None, **kwargs):
    payload = dict(kwargs)
    if book:
        payload.update(project=book["project"], book_id=book["book_id"])
    if action in {"book_init", "source_save", "source_accept", "memory_stage", "memory_sync", "book_import", "index_update", "index_rebuild", "doctor_repair"}:
        payload.setdefault("operation_id", uuid4().hex)
    return execute(action, payload)


def ok(result):
    assert result["status"] != "error", result
    return result["data"]


@pytest.fixture
def book(tmp_path):
    return ok(call("book_init", project=str(tmp_path / "中文 作品"), title="测试小说"))


def evidence(text, quote):
    return {"quote": quote, "offset": text.index(quote)}


def delta(text, **kwargs):
    return dict(source_hash=digest(text), **kwargs)


def draft(book, chapter, text, *, task="write", run_id="run:1"):
    ctx = ok(call("context_build", book, chapter=chapter, task=task, query="玉佩", run_id=run_id))
    return ok(call("source_save", book, kind="chapter", logical_id=f"chapter:{chapter}", chapter=chapter,
                   content=text, context_id=ctx["context_id"], run_id=run_id))


def stage_review(book, source, text, changes=None):
    changes = changes or delta(text)
    revision = ok(call("book_status", book))
    rev = execute("book_status", {"project": book["project"]})["revision"]
    batch = ok(call("memory_stage", book, source_version=source["source_version"], base_revision=rev, delta=changes))
    review = ok(call("source_save", book, kind="review", logical_id="review:" + source["source_version"], content="已审阅",
                     review={"source_version": source["source_version"], "source_hash": digest(text), "findings": []}))
    return batch["batch_id"], review["review_id"], rev


def accept(book, source, text, changes=None):
    batch, review, rev = stage_review(book, source, text, changes)
    return call("source_accept", book, source_version=source["source_version"], expected_revision=rev,
                batch_id=batch, review_id=review)


def initial(book):
    text = "沈舟持有玉佩。林雪并不知情。读者看到了玉佩。"
    change = delta(text, entities=[{"id": "shen", "name": "沈舟", "aliases": ["舟哥"]},
                                  {"id": "lin", "name": "林雪"}, {"id": "jade", "name": "玉佩", "kind": "item"}],
                   facts=[{"id": "owns-a", "subject": "shen", "predicate": "持有", "object": "jade", "evidence": evidence(text, "沈舟持有玉佩")}],
                   knowledge=[{"character": "shen", "fact": "owns-a", "state": "knows", "evidence": evidence(text, "沈舟持有玉佩")},
                              {"character": "reader", "fact": "owns-a", "state": "knows", "evidence": evidence(text, "读者看到了玉佩")}],
                   hooks=[{"id": "jade-secret", "summary": "玉佩来历", "evidence": evidence(text, "玉佩")}], summary="沈舟持有玉佩，林雪不知情。")
    source = draft(book, 1, text)
    ok(accept(book, source, text, change))
    return source, text


def test_isolation_and_knowledge(book, tmp_path):
    initial(book)
    other = ok(call("book_init", project=str(tmp_path / "other"), title="另一本"))
    assert ok(call("search", other, query="玉佩"))["hits"] == []
    wrong = execute("book_status", {"project": book["project"], "book_id": other["book_id"]})
    assert wrong["error"]["code"] == "BOOK_MISMATCH"
    assert len(ok(call("graph_query", book, entity="舟哥", chapter=1))["facts"]) == 1
    assert ok(call("graph_query", book, entity="jade", pov="lin", chapter=1))["facts"] == []
    assert len(ok(call("graph_query", book, entity="jade", pov="reader", chapter=1))["facts"]) == 1
    hits = ok(call("search", book, query="玉佩"))["hits"]
    assert hits and hits[0]["quote"] == "沈舟持有玉佩。林雪并不知情。读者看到了玉佩。"


def test_context_delta_review_and_idempotence(book):
    bad = call("source_save", book, kind="chapter", logical_id="chapter:1", chapter=1, content="正文")
    assert bad["error"]["code"] == "INVALID_INPUT"
    source = draft(book, 1, "第一章正文。")
    no_memory = call("source_accept", book, source_version=source["source_version"], expected_revision=0)
    assert no_memory["error"]["code"] == "MEMORY_REQUIRED"
    bad_evidence = delta("第一章正文。", entities=[{"id": "a", "name": "甲"}], facts=[{
        "id": "f", "subject": "a", "predicate": "说", "value": "错误", "evidence": {"quote": "不存在", "offset": 0}}])
    assert call("memory_stage", book, source_version=source["source_version"], base_revision=0, delta=bad_evidence)["error"]["code"] == "INVALID_EVIDENCE"
    batch, review, rev = stage_review(book, source, "第一章正文。")
    payload = dict(source_version=source["source_version"], batch_id=batch, review_id=review, expected_revision=rev, operation_id="accept-once")
    first = call("source_accept", book, **payload)
    assert first == call("source_accept", book, **payload)
    conflict = call("source_accept", book, **dict(payload, expected_revision=9))
    assert conflict["error"]["code"] == "OPERATION_CONFLICT"
    assert first["revision"] == 1


def test_draft_and_plan_scope(book):
    source = draft(book, 1, "未采纳的玉佩剧情。")
    batch, review, rev = stage_review(book, source, "未采纳的玉佩剧情。")
    assert ok(call("search", book, query="玉佩"))["hits"] == []
    context = ok(call("context_build", book, chapter=1, task="revise", draft_id=source["source_version"]))
    assert context["draft"]["candidate_memory"]["source_hash"] == source["source_hash"]
    research = ok(call("source_save", book, kind="research", logical_id="research:a", content="玉佩的历史资料。"))
    ok(call("source_accept", book, source_version=research["source_version"], expected_revision=0))
    assert ok(call("search", book, query="玉佩"))["hits"] == []
    assert ok(call("search", book, query="玉佩", scope="reference"))["hits"]
    stale = call("source_accept", book, source_version=source["source_version"], batch_id=batch, review_id=review, expected_revision=1)
    assert stale["error"]["code"] == "STALE_CONTEXT"


def test_prose_edit_invalidates_review(book):
    old = draft(book, 1, "旧稿。")
    batch, review, rev = stage_review(book, old, "旧稿。")
    new = draft(book, 1, "新稿。")
    assert call("source_accept", book, source_version=old["source_version"], batch_id=batch, review_id=review, expected_revision=0)["error"]["code"] == "SUPERSEDED_DRAFT"
    new_batch = ok(call("memory_stage", book, source_version=new["source_version"], base_revision=0, delta=delta("新稿。")))
    assert call("source_accept", book, source_version=new["source_version"], batch_id=new_batch["batch_id"], review_id=review, expected_revision=0)["error"]["code"] == "STALE_REVIEW"


def test_transfer_revision_replays_and_restores_earlier_fact(book):
    initial(book)
    text = "沈舟将玉佩交给林雪。"
    second = draft(book, 2, text)
    changes = delta(text, close_facts=[{"id": "owns-a", "evidence": evidence(text, text)}], facts=[{
        "id": "owns-b", "subject": "lin", "predicate": "持有", "object": "jade", "evidence": evidence(text, text)}])
    ok(accept(book, second, text, changes))
    third = draft(book, 3, "风雨将至。")
    ok(accept(book, third, "风雨将至。"))
    assert ok(call("graph_query", book, entity="jade", chapter=1))["facts"][0]["subject"] == "shen"
    assert ok(call("graph_query", book, entity="jade", chapter=3))["facts"][0]["subject"] == "lin"
    replacement = draft(book, 2, "沈舟把玉佩收回袖中。", task="revise")
    result = ok(accept(book, replacement, "沈舟把玉佩收回袖中。"))
    jid = result["job_id"]
    assert ok(call("graph_query", book, entity="jade", chapter=2))["facts"][0]["subject"] == "shen"
    assert call("graph_query", book, entity="jade", chapter=3)["error"]["code"] == "MEMORY_NOT_READY"
    assert call("source_accept", book, source_version=third["source_version"], expected_revision=4)["error"]["code"] == "SYNC_IN_PROGRESS"
    job = ok(call("memory_sync", book, mode="next", job_id=jid))
    assert job["next_source_version"] == third["source_version"]
    full = ok(call("source_get", book, source_version=job["next_source_version"]))
    rev = call("book_status", book)["revision"]
    applied = call("memory_sync", book, mode="apply", job_id=jid, source_version=job["next_source_version"], base_revision=rev,
                   delta=delta(full["content"]), operation_id="replay-third")
    ok(applied)
    assert applied == call("memory_sync", book, mode="apply", job_id=jid, source_version=job["next_source_version"], base_revision=rev,
                           delta=delta(full["content"]), operation_id="replay-third")
    assert not ok(call("book_status", book))["active_job"]
    assert ok(call("graph_query", book, entity="jade", chapter=3))["facts"][0]["subject"] == "shen"


def test_import_preview_mapping_resume_and_immutable_sources(book, tmp_path):
    manuscript = tmp_path / "旧稿.txt"
    manuscript.write_bytes("第一章 初见\n沈舟看到玉佩。\n第二章 分别\n林雪离开。".encode("gb18030"))
    preview = ok(call("book_import", book, mode="preview", files=[str(manuscript)]))
    assert len(preview["mapping"]) == 2
    started = ok(call("book_import", book, mode="start", mapping_id=preview["mapping_id"]))
    assert call("context_build", book, chapter=3)["error"]["code"] == "MEMORY_NOT_READY"
    for number in (1, 2):
        job = ok(call("memory_sync", book, mode="next", job_id=started["job_id"]))
        source = ok(call("source_get", book, source_version=job["next_source_version"], max_chars=10000))
        rev = call("book_status", book)["revision"]
        ok(call("memory_sync", book, mode="apply", job_id=started["job_id"], source_version=source["source_version"], base_revision=rev, delta=delta(source["content"])))
    assert ok(call("book_status", book))["memory_frontier"] == 2
    old_file = Path(book["project"]) / "正文" / "第0001章.md"
    old_file.write_text("外部编辑", encoding="utf-8")
    assert ok(call("book_status", book))["changed_projections"]
    original = ok(call("source_get", book, source_version=source["source_version"]))
    assert "林雪离开" in original["content"]


def test_changed_import_source_is_rejected(book, tmp_path):
    path = tmp_path / "text.md"
    path.write_text("# 章一\n正文", encoding="utf-8")
    preview = ok(call("book_import", book, mode="preview", files=[str(path)]))
    path.write_text("changed", encoding="utf-8")
    assert call("book_import", book, mode="start", mapping_id=preview["mapping_id"])["error"]["code"] == "IMPORT_SOURCE_CHANGED"


def test_run_scoped_pending_and_budget(book):
    src = draft(book, 1, "正文。", run_id="session:turn")
    state = ok(call("book_status", book))
    assert state["pending_work"][0]["run_id"] == "session:turn"
    stage_review(book, src, "正文。")
    assert call("book_status", book)["status"] == "awaiting_author"
    brief = {"constraints": ["规矩" * 500]}
    assert call("context_build", book, chapter=1, budget_chars=500, scene_brief=brief)["error"]["code"] == "BUDGET_EXCEEDED"


def test_doctor_restores_pending_projection_without_overwriting_external_edit(book, monkeypatch):
    from novel_weaver import store
    original = store.os.replace
    monkeypatch.setattr(store.os, "replace", lambda *args: (_ for _ in ()).throw(PermissionError("occupied")))
    source = draft(book, 1, "正文。")
    result = accept(book, source, "正文。")
    assert result["status"] == "partial"
    monkeypatch.setattr(store.os, "replace", original)
    ok(call("doctor_repair", book))
    path = Path(book["project"]) / "正文" / "第0001章.md"
    assert path.read_text(encoding="utf-8") == "正文。"
    path.write_text("作者的新修改", encoding="utf-8")
    ok(call("doctor_repair", book))
    assert path.read_text(encoding="utf-8") == "作者的新修改"


def test_candidate_facts_do_not_become_established_knowledge(book):
    text = "沈舟猜测玉佩能开门。"
    src = draft(book, 1, text)
    changes = delta(text, entities=[{"id": "a", "name": "沈舟"}], facts=[{
        "id": "guess", "subject": "a", "predicate": "猜测", "value": "玉佩能开门", "certainty": "candidate", "evidence": evidence(text, text)}])
    ok(accept(book, src, text, changes))
    facts = ok(call("graph_query", book, entity="a"))["facts"]
    assert facts[0]["certainty"] == "candidate"

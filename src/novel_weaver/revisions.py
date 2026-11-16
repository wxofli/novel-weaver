"""Resumable candidate replay with one atomic canon/graph commit.

Uses jobs/batches plus disposable, lazily created candidate snapshots.
Each delta is validated against an isolated ordered prefix; final commit always
replays authoritative deltas. Cache misses rebuild inside a rolled-back savepoint.
"""
import json
import time

from .errors import NovelError, require
from .memory import apply_delta
from .schemas import MemoryDelta
from .store import dumps, uid
from . import candidate_snapshot


def _check_revisions(book, revisions):
    from .service import context_ticket
    chapters = set()
    for item in revisions:
        source = book.source(item["source_version"])
        require(source["kind"] == "chapter" and source["chapter"] not in chapters,
                "REVISION_SCOPE", "Use one replacement per existing chapter", 2)
        chapters.add(source["chapter"])
        require(source["hash"] == item["source_hash"], "SOURCE_HASH_MISMATCH", "Replacement hash differs", 4)
        accepted = book.db.execute("SELECT source_id FROM accepted WHERE logical_id=?", (source["logical_id"],)).fetchone()
        require(accepted and accepted[0] != source["id"], "REVISION_SCOPE", "Batch revision only replaces accepted chapters", 4)
        latest = book.db.execute("SELECT id FROM sources WHERE logical_id=? ORDER BY created_at DESC LIMIT 1", (source["logical_id"],)).fetchone()
        require(latest[0] == source["id"], "SUPERSEDED_DRAFT", "Replacement has a newer candidate", 4)
        context_ticket(book, source["context_id"], source["chapter"])
        review = book.source(item["review_id"])
        details = json.loads(review["review_json"] or "{}")
        require(review["kind"] == "review" and details.get("source_version") == source["id"]
                and details.get("source_hash") == source["hash"], "STALE_REVIEW", "Review must bind exact replacement", 4)
        for finding in details.get("findings", []):
            require(not finding.get("quote") or finding["quote"] in source["content"], "INVALID_EVIDENCE", "Review quote is absent", 2)
    return chapters


def progress(book, job, manifest, *, include_source=False, max_chars=12000):
    from .service import source_page
    position = job["position"]
    sources = manifest["sources"]
    data = {"job_id": job["id"], "kind": "revision_batch", "position": position, "total": len(sources),
            "ready_to_commit": position == len(sources), "baseline_revision": manifest["revision"],
            "first_chapter": manifest["first_chapter"], "canon_unchanged": True}
    if position < len(sources):
        source = book.source(sources[position])
        data.update(next_source_version=source["id"], source_hash=source["hash"], chapter=source["chapter"])
        if include_source:
            data["source"] = source_page(source, max_chars=max_chars)
    return data


def _replay(book, manifest, batch_ids):
    from .service import replay_prefix
    replay_prefix(book, manifest["first_chapter"])
    for source_id, batch_id in zip(manifest["sources"], batch_ids):
        row = book.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        require(row and row["source_id"] == source_id and row["base_revision"] == manifest["revision"],
                "STALE_DELTA", "Revision delta binding changed", 4)
        apply_delta(book, book.source(source_id), MemoryDelta.model_validate_json(row["delta"]))


def execute_batch(book, request):
    from .retrieval import index_source
    from .service import add_ledger
    if request.mode == "prepare":
        require(not book.active_job(), "SYNC_IN_PROGRESS", "Finish or abort the active job first", 4)
        require(request.expected_revision == book.revision, "REVISION_CONFLICT", "Book revision changed", 4)
        revisions = [r.model_dump() for r in request.revisions]
        chapters = _check_revisions(book, revisions)
        first = min(chapters)
        replacement = {book.source(r["source_version"])["chapter"]: r["source_version"] for r in revisions}
        sources = [replacement.get(r["chapter"], r["id"]) for r in book.db.execute(
            "SELECT s.id,s.chapter FROM accepted a JOIN sources s ON s.id=a.source_id WHERE s.kind='chapter' AND s.chapter>=? ORDER BY s.chapter", (first,))]
        manifest = {"revision": book.revision, "fingerprint": book.fingerprint(), "first_chapter": first,
                    "revisions": revisions, "sources": sources, "batches": []}
        job_id = uid("revision")
        book.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job_id, "revision_batch", dumps(manifest), 0, "active", time.time_ns()))
        return progress(book, book.active_job(), manifest, include_source=request.include_source, max_chars=request.max_chars)

    job = book.active_job()
    require(job and job["id"] == request.job_id and job["kind"] == "revision_batch",
            "REVISION_JOB_NOT_ACTIVE", "No matching active revision batch", 4)
    manifest = json.loads(job["manifest"])
    if request.mode == "abort":
        candidate_snapshot.discard(book, job["id"])
        book.db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job["id"],))
        return {"job_id": job["id"], "aborted": True, "canon_unchanged": True}
    require(book.revision == manifest["revision"] and book.fingerprint() == manifest["fingerprint"],
            "REVISION_CONFLICT", "Revision baseline changed; abort and rebuild", 4)
    _check_revisions(book, manifest["revisions"])
    if request.mode == "next":
        return progress(book, job, manifest, include_source=request.include_source, max_chars=request.max_chars)
    if request.mode == "context":
        from .memory import fact_rows
        with candidate_snapshot.candidate(book, job, manifest) as graph:
            chapter = manifest["first_chapter"] + job["position"] - 1
            rows = fact_rows(graph, chapter, seeds=set(request.entity_ids) if request.entity_ids else None)
            rows.sort(key=lambda row: (-row["introduced"], row["id"]))
            data = {"job_id": job["id"], "view": "candidate_author_memory", "as_of_chapter": chapter,
                    "canon_unchanged": True, "facts": [], "truncated": False}
            minimum = len(dumps(data))
            if minimum > request.max_chars:
                raise NovelError("BUDGET_EXCEEDED", "Candidate context metadata exceeds the budget",
                                 details={"minimum_required_chars": minimum, "provided_chars": request.max_chars})
            for row in rows[:50]:
                data["facts"].append(row)
                if len(dumps(data)) > request.max_chars:
                    data["facts"].pop()
                    break
            data["truncated"] = len(data["facts"]) < len(rows)
            payload = None if graph.restored else candidate_snapshot.capture(graph)
        if payload is not None:
            candidate_snapshot.save(book, job, manifest, payload)
        return data
    if request.mode == "apply":
        require(job["position"] < len(manifest["sources"])
                and request.source_version == manifest["sources"][job["position"]],
                "SYNC_ORDER", "Stage only the next exact revision source", 4)
        with candidate_snapshot.candidate(book, job, manifest) as graph:
            apply_delta(graph, book.source(request.source_version), request.delta)
            payload = candidate_snapshot.capture(graph)
        batch_id = uid("batch")
        book.db.execute("INSERT INTO batches VALUES (?,?,?,?,0)",
                        (batch_id, request.source_version, book.revision, request.delta.model_dump_json()))
        manifest["batches"].append(batch_id)
        job["position"] += 1
        book.db.execute("UPDATE jobs SET manifest=?,position=? WHERE id=?", (dumps(manifest), job["position"], job["id"]))
        candidate_snapshot.save(book, job, manifest, payload)
        return dict(progress(book, job, manifest, include_source=request.include_source, max_chars=request.max_chars), batch_id=batch_id)

    require(request.expected_revision == book.revision, "REVISION_CONFLICT", "Book revision changed", 4)
    require(job["position"] == len(manifest["sources"]), "REVISION_INCOMPLETE", "Stage every affected chapter before commit", 4)
    # Re-validate and build once more inside the same transaction as pointer changes.
    from .service import replay_prefix
    replay_prefix(book, manifest["first_chapter"])
    book.db.execute("UPDATE ledger SET valid=0 WHERE chapter>=?", (manifest["first_chapter"],))
    for source_id, batch_id in zip(manifest["sources"], manifest["batches"]):
        row = book.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        require(row and row["source_id"] == source_id and row["base_revision"] == book.revision,
                "STALE_DELTA", "Revision delta binding changed", 4)
        add_ledger(book, book.source(source_id), MemoryDelta.model_validate_json(row["delta"]))
        book.db.execute("UPDATE batches SET applied=1 WHERE id=?", (batch_id,))
    for item in manifest["revisions"]:
        source = book.source(item["source_version"])
        book.db.execute("UPDATE accepted SET source_id=? WHERE logical_id=?", (source["id"], source["logical_id"]))
        index_source(book, source)
        book.queue_projection(source)
    book.set_meta("frontier", book.source(manifest["sources"][-1])["chapter"])
    book.db.execute("UPDATE jobs SET status='complete' WHERE id=?", (job["id"],))
    candidate_snapshot.discard(book, job["id"])
    book.bump()
    return {"job_id": job["id"], "accepted": True, "chapters_revised": len(manifest["revisions"]),
            "chapters_replayed": len(manifest["sources"]), "memory_frontier": book.frontier()}

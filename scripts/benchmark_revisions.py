"""Compare old/new workflows on temporary synthetic books, never real manuscripts."""
import argparse
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from novel_weaver.service import execute, WRITE_ACTIONS
from novel_weaver.store import Book, digest
from novel_weaver import candidate_snapshot, service, revisions

HISTORICAL_ORDER = [58, 61, 64, 65, 63, 68, 69, 70, 73, 74, 75, 51, 21, 23, 4, 1]


@contextmanager
def measured_replay(legacy=False):
    """Instrument real core calls; legacy reproduces v0.1.6 validation savepoints."""
    metrics = Counter()
    original_apply, original_candidate, original_save = revisions.apply_delta, candidate_snapshot.candidate, candidate_snapshot.save
    original_capture = candidate_snapshot.capture
    original_connect = sqlite3.connect
    class CountedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            metrics["sqlite_statements"] += 1
            return super().execute(sql, parameters)
        def executemany(self, sql, parameters):
            rows = list(parameters)
            metrics["sqlite_statements"] += len(rows)
            return super().executemany(sql, rows)
    def connect(*args, **kwargs):
        kwargs.setdefault("factory", CountedConnection)
        return original_connect(*args, **kwargs)
    def apply(*args):
        metrics["delta_applications"] += 1
        return original_apply(*args)
    def save(book, job, manifest, payload):
        metrics["peak_snapshot_bytes"] = max(metrics["peak_snapshot_bytes"], len(payload))
        return original_save(book, job, manifest, payload)
    @contextmanager
    def replay(book, job, manifest):
        book.db.execute("SAVEPOINT benchmark_legacy")
        try:
            revisions._replay(book, manifest, manifest["batches"])
            yield SimpleNamespace(db=book.db, restored=False)
        finally:
            book.db.execute("ROLLBACK TO benchmark_legacy")
            book.db.execute("RELEASE benchmark_legacy")
    try:
        service.apply_delta = revisions.apply_delta = apply
        sqlite3.connect = connect
        candidate_snapshot.save = save
        if legacy:
            candidate_snapshot.candidate = replay
            candidate_snapshot.save = lambda *args: None
            candidate_snapshot.capture = lambda *args: None
        yield metrics
    finally:
        service.apply_delta = revisions.apply_delta = original_apply
        candidate_snapshot.candidate, candidate_snapshot.save = original_candidate, original_save
        candidate_snapshot.capture = original_capture
        sqlite3.connect = original_connect


def compare(directory, chapters=75, order=None, *, snapshot_compare=False, include_context=False, facts_per_chapter=1):
    order = HISTORICAL_ORDER if order is None else order
    assert order and len(set(order)) == len(order) and all(1 <= n <= chapters for n in order)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    book = {}
    assert facts_per_chapter >= 1
    def make_text(n, changed):
        state = "新" if changed else "旧"
        return "\n".join(f"第{n}章，甲记录{state}事项{j + 1 if facts_per_chapter > 1 else ''}。" for j in range(facts_per_chapter))
    def call(action, **kwargs):
        counts[action] += 1
        payload = dict(book, **kwargs)
        if action in WRITE_ACTIONS or action == "book_init":
            payload.setdefault("operation_id", uuid4().hex)
        result = execute(action, payload)
        if result["status"] == "error":
            raise RuntimeError(result["error"])
        return result
    def changes(n, text):
        lines = text.splitlines()
        facts = [{"id": f"fact:{n}:{j}", "subject": "a", "predicate": "记事", "value": line,
                  "evidence": {"quote": line, "offset": text.index(line)}} for j, line in enumerate(lines)]
        return {"source_hash": digest(text), "entities": [{"id": "a", "name": "甲"}] if n == 1 else [],
                "facts": facts, "knowledge": [{"character": person, "fact": f["id"], "state": "knows", "evidence": f["evidence"]}
                                                for f in facts for person in ("reader", "a")] if facts_per_chapter > 1 else []}
    def saved(n, text):
        ctx = call("context_build", task="revise", chapter=n, pov="reader")["data"]
        source = call("source_save", kind="chapter", logical_id=f"chapter:{n}", chapter=n,
                      content=text, context_id=ctx["context_id"])["data"]
        call("source_get", source_version=source["source_version"])
        review = call("source_save", kind="review", logical_id="review:" + source["source_version"], content="合成验证",
                      review={"source_version": source["source_version"], "source_hash": source["source_hash"], "findings": []})["data"]
        return dict(source_version=source["source_version"], source_hash=source["source_hash"], review_id=review["review_id"])
    base = directory / "baseline"
    result = call("book_init", project=str(base), title="Synthetic benchmark")
    book = {"project": str(base), "book_id": result["data"]["book_id"]}
    revision = 0
    for n in range(1, chapters + 1):
        text = make_text(n, False)
        s = saved(n, text)
        staged = call("memory_stage", source_version=s["source_version"], base_revision=revision, delta=changes(n, text))["data"]
        result = call("source_accept", source_version=s["source_version"], review_id=s["review_id"], batch_id=staged["batch_id"], expected_revision=revision)
        revision = result["revision"]
    results, fingerprints = {}, []
    for mode in (("batch_replay", "batch_snapshot") if snapshot_compare else ("sequential", "batch")):
        target = directory / mode
        shutil.copytree(base, target)
        book["project"] = str(target)
        revision = chapters
        counts.clear()
        start = time.perf_counter()
        with measured_replay(legacy=mode == "batch_replay") as metrics:
            run_mode(mode, call, saved, changes, make_text, order, chapters, revision, include_context)
        results[mode] = {"tool_calls": sum(counts.values()), "calls_by_tool": dict(counts),
                         "seconds": round(time.perf_counter() - start, 3), **metrics}
        db = Book(target, book["book_id"], readonly=True)
        try:
            assert db.frontier() == chapters and db.active_job() is None
            graph = {}
            for table in candidate_snapshot.TABLES:
                rows = []
                for row in db.db.execute(f"SELECT * FROM {table}"):
                    row = dict(row)
                    if "source_id" in row:
                        source = db.source(row["source_id"])
                        row["source_id"] = (source["chapter"], source["hash"])
                    rows.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
                graph[table] = sorted(rows)
            hashes = [tuple(r) for r in db.db.execute("SELECT s.chapter,s.hash FROM accepted a JOIN sources s ON s.id=a.source_id ORDER BY s.chapter")]
            fingerprints.append((graph, hashes))
        finally:
            db.close()
    assert fingerprints[0] == fingerprints[1], "Final canon/semantic graph diverged"
    results.update(chapters=chapters, revised_chapters=len(order), semantic_graph_and_canon_equal=True,
                   facts_per_chapter=facts_per_chapter, context_before_each_apply=include_context,
                   sequential_extraction_passes=sum(chapters - n + 1 for n in order), batch_extraction_passes=chapters - min(order) + 1,
                   caveat="Synthetic local calls, no model inference or token billing. Warm snapshots avoid prefix validation; final commit replays every delta.")
    return results


def run_mode(mode, call, saved, changes, make_text, order, chapters, revision, include_context):
    if mode == "sequential":
        for n in order:
            text = make_text(n, True)
            s = saved(n, text)
            staged = call("memory_stage", source_version=s["source_version"], base_revision=revision, delta=changes(n, text))["data"]
            result = call("source_accept", source_version=s["source_version"], review_id=s["review_id"], batch_id=staged["batch_id"], expected_revision=revision)
            revision = result["revision"]
            job = result["data"]["job_id"]
            # Each old revision requires the unchanged suffix to be extracted again.
            for following in range(n + 1, chapters + 1):
                next_item = call("memory_sync", mode="next", job_id=job)["data"]
                source = call("source_get", source_version=next_item["next_source_version"])["data"]
                result = call("memory_sync", mode="apply", job_id=job, source_version=source["source_version"],
                              base_revision=revision, delta=changes(following, source["content"]))
                revision = result["revision"]
    else:
        replacements = [saved(n, make_text(n, True)) for n in order]
        next_item = call("revision_batch", mode="prepare", revisions=replacements, expected_revision=revision, include_source=True)["data"]
        job = next_item["job_id"]
        while not next_item["ready_to_commit"]:
            source = next_item["source"]
            assert source["next_offset"] is None
            if include_context:
                call("revision_batch", mode="context", job_id=job)
            next_item = call("revision_batch", mode="apply", job_id=job, source_version=source["source_version"],
                             delta=changes(source["chapter"], source["content"]), include_source=True)["data"]
        call("revision_batch", mode="commit", job_id=job, expected_revision=revision)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", type=int, default=75)
    parser.add_argument("--order", type=json.loads, default=HISTORICAL_ORDER)
    parser.add_argument("--compare-snapshots", action="store_true")
    parser.add_argument("--include-context", action="store_true")
    parser.add_argument("--facts-per-chapter", type=int, default=1)
    args = parser.parse_args()
    cache = Path(__file__).resolve().parents[1] / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="revision-benchmark-", dir=cache) as folder:
        print(json.dumps(compare(folder, args.chapters, args.order, snapshot_compare=args.compare_snapshots,
                                 include_context=args.include_context, facts_per_chapter=args.facts_per_chapter), ensure_ascii=False, indent=2))

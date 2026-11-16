"""Compare old/new workflows on temporary synthetic books, never real manuscripts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from novel_weaver.service import execute, WRITE_ACTIONS
from novel_weaver.store import Book, digest

HISTORICAL_ORDER = [58, 61, 64, 65, 63, 68, 69, 70, 73, 74, 75, 51, 21, 23, 4, 1]


def compare(directory, chapters=75, order=None):
    order = HISTORICAL_ORDER if order is None else order
    assert order and len(set(order)) == len(order) and all(1 <= n <= chapters for n in order)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    book = {}
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
        return {"source_hash": digest(text), "entities": [{"id": "a", "name": "甲"}] if n == 1 else [],
                "facts": [{"id": f"fact:{n}", "subject": "a", "predicate": "记事", "value": text,
                           "evidence": {"quote": text, "offset": 0}}]}
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
        text = f"第{n}章，甲记录旧事项。"
        s = saved(n, text)
        staged = call("memory_stage", source_version=s["source_version"], base_revision=revision, delta=changes(n, text))["data"]
        result = call("source_accept", source_version=s["source_version"], review_id=s["review_id"], batch_id=staged["batch_id"], expected_revision=revision)
        revision = result["revision"]
    results, fingerprints = {}, []
    for mode in ("sequential", "batch"):
        target = directory / mode
        shutil.copytree(base, target)
        book["project"] = str(target)
        revision = chapters
        counts.clear()
        start = time.perf_counter()
        if mode == "sequential":
            for n in order:
                text = f"第{n}章，甲记录新事项。"
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
            replacements = [saved(n, f"第{n}章，甲记录新事项。") for n in order]
            next_item = call("revision_batch", mode="prepare", revisions=replacements, expected_revision=revision, include_source=True)["data"]
            job = next_item["job_id"]
            while not next_item["ready_to_commit"]:
                source = next_item["source"]
                assert source["next_offset"] is None
                next_item = call("revision_batch", mode="apply", job_id=job, source_version=source["source_version"],
                                 delta=changes(source["chapter"], source["content"]), include_source=True)["data"]
            call("revision_batch", mode="commit", job_id=job, expected_revision=revision)
        results[mode] = {"tool_calls": sum(counts.values()), "calls_by_tool": dict(counts), "seconds": round(time.perf_counter() - start, 3)}
        db = Book(target, book["book_id"], readonly=True)
        try:
            assert db.frontier() == chapters and db.active_job() is None
            facts = [tuple(r) for r in db.db.execute("SELECT id,subject,predicate,value FROM facts ORDER BY id")]
            hashes = [tuple(r) for r in db.db.execute("SELECT s.chapter,s.hash FROM accepted a JOIN sources s ON s.id=a.source_id ORDER BY s.chapter")]
            fingerprints.append((facts, hashes))
        finally:
            db.close()
    assert fingerprints[0] == fingerprints[1], "Final canon/semantic graph diverged"
    results.update(chapters=chapters, revised_chapters=len(order), semantic_graph_and_canon_equal=True,
                   sequential_extraction_passes=sum(chapters - n + 1 for n in order), batch_extraction_passes=chapters - min(order) + 1,
                   caveat="Synthetic local calls, no model inference or token billing. Batch validation rebuilds prefixes internally; extraction occurs once per suffix chapter.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapters", type=int, default=75)
    parser.add_argument("--order", type=json.loads, default=HISTORICAL_ORDER)
    args = parser.parse_args()
    cache = Path(__file__).resolve().parents[1] / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="revision-benchmark-", dir=cache) as folder:
        print(json.dumps(compare(folder, args.chapters, args.order), ensure_ascii=False, indent=2))

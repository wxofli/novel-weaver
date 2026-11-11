"""Synthetic retrieval benchmark; does not use model APIs or the author's books.

The fixture loads SQLite directly to measure retrieval separately from authoring.
Transaction and acceptance semantics are covered by the integration test suite.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novel_weaver.retrieval import index_source
from novel_weaver.service import execute
from novel_weaver.store import Book, dumps, initialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".cache/benchmarks")
    parser.add_argument("--chapters", type=int, default=1000)
    parser.add_argument("--chars-per-chapter", type=int, default=2000)
    parser.add_argument("--facts", type=int, default=50000)
    parser.add_argument("--queries", type=int, default=40)
    args = parser.parse_args()
    if min(args.chapters, args.chars_per_chapter, args.facts, args.queries) <= 0:
        parser.error("all sizes must be positive")
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix="synthetic-", dir=output))
    metadata = initialize(project, "合成检索基准", "benchmark-init")
    book = Book(project, metadata["book_id"])
    started = time.perf_counter()
    with book.transaction():
        for i in range(1000):
            book.db.execute("INSERT INTO entities VALUES (?,?,?,?)", (f"entity{i}", f"人物{i:04d}", "character", "[]"))
        sources = []
        paragraph = "沈舟走到码头，拿出玉佩查看纹路。远处的船灯在雾中摇晃，林雪站在岸边等候。"
        for chapter in range(1, args.chapters + 1):
            header = f"第{chapter}章\n人物{chapter % 1000:04d}到达雨港。\n"
            content = (header + ((paragraph + "\n") * (args.chars_per_chapter // len(paragraph) + 2)))[:args.chars_per_chapter]
            source = book.save_source("chapter", f"chapter:{chapter}", content, chapter)
            sources.append(source)
            book.db.execute("INSERT INTO accepted VALUES (?,?)", (source["logical_id"], source["id"]))
            index_source(book, source)
        records = []
        for i in range(args.facts):
            source = sources[i % len(sources)]
            records.append((f"fact{i}", f"entity{i % 1000}", "经历", None, f"事件{i}", source["id"],
                            source["content"][:20], 0, source["chapter"], source["chapter"], None, "established", None))
        book.db.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", records)
        book.set_meta("frontier", args.chapters)
        book.set_meta("revision", args.chapters)
    book.close()
    build_seconds = time.perf_counter() - started
    payload = dict(project=str(project), book_id=metadata["book_id"])
    results = {}
    for action, parameters in (("search", {"query": "玉佩"}), ("graph_query", {"entity": "entity12"})):
        warm = execute(action, dict(payload, **parameters))
        assert warm["status"] == "ok", warm
        assert warm["data"].get("hits") or warm["data"].get("facts"), warm
        timings = []
        for _ in range(args.queries):
            began = time.perf_counter()
            response = execute(action, dict(payload, **parameters))
            assert response["status"] == "ok", response
            timings.append((time.perf_counter() - began) * 1000)
        p95 = sorted(timings)[min(len(timings) - 1, int(len(timings) * 0.95))]
        results[action] = {"median_ms": round(statistics.median(timings), 2), "p95_ms": round(p95, 2), "target_met": p95 <= 500}
    report = {"fixture": str(project), "chapters": args.chapters, "characters": args.chapters * args.chars_per_chapter,
              "facts": args.facts, "fixture_build_seconds": round(build_seconds, 2),
              "includes_model_or_network": False, "queries_per_operation": args.queries, "results": results}
    (output / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if all(result["target_met"] for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

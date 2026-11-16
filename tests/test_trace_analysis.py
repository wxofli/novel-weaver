import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location("trace_analysis", Path(__file__).resolve().parents[1] / "scripts/analyze_traces.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_trace_analysis_deduplicates_and_separates_workflow_states(tmp_path):
    def event(call_id, name, data, *, status="ok", thread="parent", minute="01"):
        result = {"schema_version": 1, "status": status, "data": data, "error": None}
        return {"type": "event_msg", "timestamp": f"2026-11-16T00:{minute}:00Z", "payload": {
            "thread_id": thread, "type": "item_completed", "item": {"type": "McpToolCall", "id": call_id,
            "server": "novel_weaver", "tool": name, "arguments": {"request": {"source_version": "s", "book_id": "b"}},
            "result": {"structuredContent": result, "content": [{"type": "text", "text": json.dumps(result)}]}}}}
    rows = [event("a", "book_status", {"latest_chapter": 5}, status="awaiting_author"),
            event("b", "source_get", {"content": "PRIVATE-TEXT"}), event("b", "source_get", {"content": "PRIVATE-TEXT"}),
            event("c", "source_get", {"content": "PRIVATE-TEXT"}),
            event("d", "source_accept", {"job_id": "j1", "memory_frontier": 2}, minute="02"),
            event("e", "source_accept", {"job_id": "j2", "memory_frontier": 4}, minute="03")]
    parent, child = tmp_path / "parent.jsonl", tmp_path / "child.jsonl"
    parent.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    child.write_text("\n".join(map(json.dumps, rows + [event("f", "book_status", {}, thread="child")])), encoding="utf-8")
    report = module.analyze([("parent", parent), ("child", child)])
    assert report["tools"]["source_get"]["calls"] == 2
    assert report["same_thread_page_reads"]["repeat_calls"] == 1
    assert report["tools"]["book_status"]["awaiting_author"] == 1
    spans = report["revision_counterfactual_by_utc_day"]["2026-11-16"]
    assert spans["sequential_chapter_passes"] == 6 and spans["single_batch_chapter_passes"] == 4
    assert "PRIVATE-TEXT" not in json.dumps(report)


def test_trace_analysis_keeps_missing_results_unclassified(tmp_path):
    row = {"type": "event_msg", "timestamp": "2026-11-16T00:00:00Z", "payload": {"thread_id": "t", "type": "item_completed",
           "item": {"type": "McpToolCall", "id": "c", "server": "novel_weaver", "tool": "search", "arguments": {},
                    "result": {"content": [{"type": "text", "text": "truncated"}]}}}}
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(row) + "\n{partial", encoding="utf-8")
    report = module.analyze([("t", path)])
    assert report["tools"]["search"]["unparsed"] == 1 and report["unreadable_lines"] == 1


def test_synthetic_trace_pattern_preserves_results_with_fewer_calls(tmp_path):
    spec = importlib.util.spec_from_file_location("revision_benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark_revisions.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    result = benchmark.compare(tmp_path, chapters=4, order=[3, 1])
    assert result["sequential_extraction_passes"] == 6
    assert result["batch_extraction_passes"] == 4
    assert result["semantic_graph_and_canon_equal"]
    assert result["batch"]["tool_calls"] < result["sequential"]["tool_calls"]

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


spec = importlib.util.spec_from_file_location("trace_analysis", Path(__file__).resolve().parents[1] / "scripts/analyze_traces.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_transport_script_imports_outside_repo_with_isolated_python(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/benchmark_transport.py"
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_transport',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.envelope({'structuredContent':{'schema_version':1}})=={'schema_version':1}
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(script)], cwd=tmp_path, check=True, capture_output=True, text=True)


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


def test_snapshot_benchmark_preserves_all_graph_tables_with_less_replay(tmp_path):
    spec = importlib.util.spec_from_file_location("snapshot_benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark_revisions.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    result = benchmark.compare(tmp_path, chapters=4, order=[3, 1], snapshot_compare=True, include_context=True, facts_per_chapter=3)
    assert result["semantic_graph_and_canon_equal"]
    assert result["batch_snapshot"]["delta_applications"] == 8
    assert result["batch_replay"]["delta_applications"] == 20
    assert result["batch_snapshot"]["tool_calls"] == result["batch_replay"]["tool_calls"]


def test_transport_counterfactual_cache_respects_compaction(tmp_path):
    spec = importlib.util.spec_from_file_location("transport_benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark_transport.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    rows = []
    for n in range(3):
        if n == 2: rows.append({"type": "compacted", "timestamp": "2026-11-16T00:00:02Z", "payload": {}})
        value = {"schema_version": 1, "status": "ok", "book_id": "b", "revision": 1, "error": None, "warnings": [], "next_actions": [],
                 "data": {"source_version": "s", "source_hash": "h", "content": "PRIVATE-TEXT", "offset": 0, "total_chars": 12, "next_offset": None}}
        rows.append({"type": "event_msg", "timestamp": f"2026-11-16T00:00:0{n}Z", "payload": {"thread_id": "t", "type": "item_completed", "item": {
            "type": "McpToolCall", "id": str(n), "server": "novel_weaver", "tool": "source_get", "arguments": {"request": {"project": "p", "book_id": "b", "source_version": "s"}},
            "result": {"structuredContent": value}}}})
    p = tmp_path / "trace.jsonl"
    p.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    result = benchmark.analyze([("t", p)], None)
    assert result["trace_counterfactual"]["cache_rpc_hits"] == 1
    assert result["trace_counterfactual"]["compaction_clears"] == 1
    assert "PRIVATE-TEXT" not in json.dumps(result)

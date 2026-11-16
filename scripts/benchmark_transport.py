"""Aggregate-only, read-only transport and bounded-cache trace counterfactual."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from novel_weaver import mcp_server
from novel_weaver.source_cache import SourcePageCache
from novel_weaver.transport import tool_result
try:
    from scripts.analyze_traces import envelope, session_files
except ModuleNotFoundError:
    from analyze_traces import envelope, session_files


def chars(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


async def schema_sizes():
    server = mcp_server.build_server(text_mode="full")
    original = await mcp_server._server_class().list_tools(server)
    compact = await server.list_tools()
    size = lambda ts: sum(chars(t.model_dump(mode="json", by_alias=True, exclude_none=True)) for t in ts)
    return {"tools": len(compact), "before_chars": size(original), "after_chars": size(compact)}


def analyze(files, before):
    seen, summary = set(), Counter()
    for thread, path in files:
        now = [0.0]
        cache = SourcePageCache(clock=lambda: now[0])
        with Path(path).open("rb") as stream:
            extent = Path(path).stat().st_size
            while stream.tell() < extent:
                try:
                    row = json.loads(stream.readline(extent - stream.tell()))
                except (ValueError, UnicodeError):
                    continue
                if before and row.get("timestamp", "") > before:
                    continue
                p = row.get("payload", {})
                if p.get("thread_id") and p["thread_id"] != thread:
                    continue
                if row.get("type") == "compacted" or p.get("type") == "context_compacted":
                    cache.clear()
                    summary["compaction_clears"] += 1
                item = p.get("item", {})
                if (row.get("type") != "event_msg" or p.get("type") != "item_completed"
                        or item.get("type") != "McpToolCall" or item.get("server") != "novel_weaver"):
                    continue
                if item.get("id") in seen:
                    continue
                seen.add(item.get("id"))
                value = envelope(item.get("result") or {})
                if value is None:
                    summary["unparsed"] += 1
                    continue
                summary["parsed_responses"] += 1
                for mode in ("full", "summary"):
                    result = tool_result(value, mode)
                    summary[mode + "_text_chars"] += len(result.content[0].text)
                    summary[mode + "_result_chars"] += chars(result.model_dump(mode="json", by_alias=True, exclude_none=True))
                if item["tool"] != "source_get" or value.get("status") != "ok":
                    continue
                summary["source_reads"] += 1
                now[0] = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp()
                request = item.get("arguments", {}).get("request", {})
                try:
                    hit = cache.get(request, source_hash=value["data"].get("source_hash"))
                    if hit is None:
                        cache.put(request, value["data"])
                    else:
                        assert hit == value["data"], "Cached source page diverged"
                        summary["cache_rpc_hits"] += 1
                        summary["cache_content_chars_avoided"] += len(hit["content"])
                except (ValueError, KeyError):
                    summary["uncacheable_reads"] += 1
    return {"files": len(files), "cutoff": before, "schema": asyncio.run(schema_sizes()),
            "trace_counterfactual": dict(summary),
            "cache_policy": {"characters": 200000, "pages": 128, "ttl_seconds": 300, "per_thread": True},
            "limits": "Transport characters, not billed/model tokens. Cache simulation assumes pages remain accessible; clears at observed compactions. No actual host enablement or book writes."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-db", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--before")
    args = parser.parse_args()
    print(json.dumps(analyze(session_files(args.session_db, args.project), args.before), ensure_ascii=False, indent=2))

"""Read-only, aggregate-only analysis of Codex JSONL traces.

No book tool calls, manuscript output, or database mutations. Repeated reads
are opportunities, not proof that an agent retained a usable cache. Historical
MCP payload wrappers that cannot be decoded remain unclassified.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3


def envelope(result):
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and "schema_version" in structured:
        return structured
    for block in result.get("content", []):
        try:
            value = json.loads(block.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and "schema_version" in value:
            return value
    return None


def session_files(database, project):
    wanted = str(Path(project).resolve()).removeprefix("\\\\?\\").replace("\\", "/").casefold()
    with sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT id,rollout_path,cwd,attached_thread_parent_id FROM threads ORDER BY created_at").fetchall()
    return [(thread, Path(path)) for thread, path, cwd, parent in rows if not parent
            and cwd.removeprefix("\\\\?\\").replace("\\", "/").casefold() == wanted]


def analyze(files, *, before=None):
    tools = defaultdict(Counter)
    outer = Counter()
    usage = Counter()
    errors = Counter()
    reads = Counter()
    lengths = {}
    seen_calls, seen_usage, seen_mcp = set(), set(), set()
    read_chars = duplicate_payloads = parsed_lines = unreadable_lines = 0
    events = []
    for thread, path in files:
        with Path(path).open("rb") as stream:
            # The parent may still be appending. Read only this file's starting extent.
            limit = Path(path).stat().st_size
            while stream.tell() < limit:
                try:
                    record = json.loads(stream.readline())
                except (ValueError, UnicodeDecodeError):
                    unreadable_lines += 1
                    continue
                if before and record.get("timestamp", "") > before:
                    continue
                payload = record.get("payload", {})
                if not isinstance(payload, dict) or (payload.get("thread_id") and payload["thread_id"] != thread):
                    continue
                parsed_lines += 1
                if record.get("type") == "token_usage_record":
                    rid = payload.get("response_id")
                    if rid and rid not in seen_usage:
                        seen_usage.add(rid)
                        usage.update({k: v for k, v in payload.get("usage", {}).items() if isinstance(v, int)})
                if record.get("type") == "response_item" and payload.get("type") in {"function_call", "custom_tool_call"}:
                    cid = payload.get("call_id", payload.get("id"))
                    if cid and cid not in seen_calls:
                        seen_calls.add(cid)
                        outer[payload.get("name", "unknown")] += 1
                item = payload.get("item", {})
                if record.get("type") != "event_msg" or payload.get("type") != "item_completed" or item.get("type") != "McpToolCall" or item.get("server") != "novel_weaver":
                    continue
                cid = item.get("id")
                if cid in seen_mcp:
                    continue
                seen_mcp.add(cid)
                name, result = item["tool"], item.get("result") or {}
                value = envelope(result)
                request = item.get("arguments", {}).get("request", {})
                tools[name]["calls"] += 1
                if value is None:
                    category = "schema_error" if "validation error" in str(result.get("content")) else "unparsed"
                    tools[name][category] += 1
                    continue
                status = value.get("status", "unparsed")
                tools[name][status] += 1
                if value.get("error"):
                    errors[value["error"]["code"]] += 1
                if result.get("structuredContent") and result.get("content"):
                    try:
                        duplicate_payloads += json.loads(result["content"][0].get("text", "")) == value
                    except (ValueError, TypeError):
                        pass
                data = value.get("data") or {}
                if name == "source_get" and status == "ok":
                    key = (thread, request.get("book_id"), request.get("source_version"), request.get("offset", 0), request.get("max_chars", 12000))
                    reads[key] += 1
                    lengths[key] = len(data.get("content", ""))
                    read_chars += lengths[key]
                if name in {"book_status", "source_accept"} and status in {"ok", "awaiting_author"}:
                    events.append((record.get("timestamp", ""), name, data))
    latest = 0
    revisions = defaultdict(list)
    for timestamp, name, data in sorted(events, key=lambda e: e[0]):
        if name == "book_status":
            latest = max(latest, data.get("latest_chapter", 0))
        elif data.get("job_id") and data.get("memory_frontier") and latest >= data["memory_frontier"]:
            revisions[timestamp[:10]].append((data["memory_frontier"], latest))
    comparison = {}
    for day, spans in revisions.items():
        old = sum(end - start + 1 for start, end in spans)
        new = max(end for _, end in spans) - min(start for start, _ in spans) + 1
        comparable = len({end for _, end in spans}) == 1
        comparison[day] = {"observed_revision_commits": len(spans), "sequential_chapter_passes": old,
                           "fixed_chapter_frontier": comparable,
                           "single_batch_chapter_passes": new if comparable else None,
                           "reduction_fraction": (old - new) / old if comparable else None,
                           "assumption": "same-day revisions were available together; no intervening author decisions require separate commits"}
    return {"files": len(files), "parsed_lines": parsed_lines, "unreadable_lines": unreadable_lines,
            "cutoff_utc": before, "tools": dict(tools), "outer_calls_deduplicated": outer,
            "usage_deduplicated": usage, "usage_records": len(seen_usage), "error_codes": errors,
            "duplicate_text_and_structured_results": duplicate_payloads,
            "same_thread_page_reads": {"calls": sum(reads.values()), "unique_keys": len(reads),
                "repeat_calls": sum(n - 1 for n in reads.values()), "content_chars": read_chars,
                "repeat_content_chars": sum((n - 1) * lengths[k] for k, n in reads.items()),
                "interpretation": "upper-bound opportunities; invalid after context loss without an accessible cache"},
            "revision_counterfactual_by_utc_day": comparison}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-db", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--before", help="inclusive UTC ISO timestamp")
    args = parser.parse_args()
    files = session_files(args.session_db, args.project)
    print(json.dumps(analyze(files, before=args.before), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

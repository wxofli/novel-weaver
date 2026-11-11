"""Read-only host hooks. These hints never execute the actions they suggest."""
from __future__ import annotations

import json
from pathlib import Path


CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
SUPPORTED_EVENTS = CONTEXT_EVENTS | {"Stop"}
AUTOMATED_NEEDS = {"memory.stage", "memory_stage", "memory.sync", "memory_sync", "review", "source.review", "accept", "source.accept", "source_accept", "index.update", "index_update"}


def execute(action: str, payload: dict) -> dict:
    from .service import execute as core_execute

    return core_execute(action, payload)


def discover_book(cwd: str) -> tuple[str, str] | None:
    """Select the nearest marker, including when a parent also hosts a book."""
    directory = Path(cwd).resolve()
    for root in (directory, *directory.parents):
        marker = root / ".novel" / "project.json"
        if marker.is_file():
            metadata = json.loads(marker.read_text(encoding="utf-8-sig"))
            book_id = metadata.get("book_id")
            if not isinstance(book_id, str) or not book_id:
                raise ValueError(f"Invalid book_id in {marker}")
            return str(root), book_id
    return None


def _context(event_name: str, text: str) -> dict:
    if event_name not in CONTEXT_EVENTS or not text:
        return {}
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text[:1500]}}


def _run_id(event: dict) -> str | None:
    session, turn = event.get("session_id"), event.get("turn_id")
    if not session or not turn:
        return None
    return f"{session}:{turn}"


def _plan_mode(event: dict) -> bool:
    return event.get("permission_mode") == "plan" or event.get("mode") == "plan" or event.get("plan_mode") is True


def _cancelled(event: dict) -> bool:
    return any(event.get(flag) is True for flag in ("cancelled", "canceled", "interrupted")) or str(event.get("stop_reason", "")).lower() in {"cancelled", "canceled", "interrupt", "interrupted", "user_cancel"}


def _short(value, limit: int = 140) -> str:
    return str(value).replace("\n", " ")[:limit]


def _actions(status: dict) -> str:
    labels = []
    for action in status.get("next_actions", [])[:6]:
        if isinstance(action, str):
            labels.append(_short(action, 100))
        elif isinstance(action, dict):
            label = _short(action.get("action", ""), 60)
            for key in ("source_version", "job_id"):
                if action.get(key):
                    label += f" {key}={_short(action[key], 60)}"
            if label:
                labels.append(label)
    return "; ".join(labels)


def _card(status: dict, project: str, book_id: str, event: dict) -> str:
    data = status.get("data") or {}
    lines = ["Novel Weaver book state", f"run_id={_run_id(event) or 'unavailable'}", f"book_id={book_id}", f"project={_short(project, 200)}", f"title={_short(data.get('title', ''), 100)}", f"latest_chapter={data.get('latest_chapter', 0)}; memory_frontier={data.get('memory_frontier', 0)}"]
    if _plan_mode(event):
        lines.append("Plan mode is read-only. Use book status, search, graph and source reads to plan the work; do not modify book state.")
    else:
        actions = _actions(status)
        if actions:
            lines.append("Next actions: " + actions)
        lines.append("For book authoring requests use this project's Novel Weaver skills and context_build before writing. Keep ordinary conversation outside book memory. Pass the run_id above to this turn's book work when available.")
    return "\n".join(lines)[:1500]


def _supported_tool(event: dict) -> bool:
    name = str(event.get("tool_name", ""))
    if name in {"Write", "Edit", "MultiEdit", "apply_patch"}:
        return True
    if name in {"Bash", "Shell", "shell", "exec_command", "mcp__functions__exec"}:
        payload = event.get("tool_input") or {}
        return "novelctl" in str(payload.get("command", payload.get("cmd", "")))
    return any(name.endswith("__" + action) for action in AUTOMATED_NEEDS if "_" in action) or "novel_weaver" in name or "novel-weaver" in name


def _continue_reason(status: dict, event: dict) -> str | None:
    run_id = _run_id(event)
    data = status.get("data") or {}
    if not run_id or event.get("stop_hook_active") is not False or data.get("awaiting_author"):
        return None
    pending = []
    for item in data.get("pending_work", []):
        if not isinstance(item, dict) or item.get("run_id") != run_id:
            continue
        if item.get("awaiting_author") or item.get("status") == "awaiting_author" or item.get("automated") is False:
            continue
        raw_needs = item.get("needs", [])
        if "awaiting_author" in raw_needs:
            continue
        needs = [need for need in raw_needs if need in AUTOMATED_NEEDS]
        if needs:
            pending.append(f"{_short(item.get('source_version', 'saved source'), 80)}: {', '.join(needs)}")
    if not pending:
        return None
    return (f"Novel Weaver has incomplete automated work for this run ({run_id}): " + "; ".join(pending[:5]) + ". Continue the applicable book workflow once using the saved source and exact batch/review IDs. Stop if author input is required.")[:1500]


def handle_event(event_name: str, event: dict) -> dict:
    """Return official hook JSON, swallowing failures so host sessions stay usable."""
    if event_name not in SUPPORTED_EVENTS or not isinstance(event, dict) or _cancelled(event):
        return {}
    if event_name == "Stop" and (_plan_mode(event) or event.get("stop_hook_active") is not False or not _run_id(event)):
        return {}
    if event_name == "PreToolUse" and not _supported_tool(event):
        return {}
    try:
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return {}
        book = discover_book(cwd)
        if book is None:
            return {}
        project, book_id = book
        status = execute("book_status", {"project": project, "book_id": book_id})
        if status.get("error"):
            return _context(event_name, "Novel Weaver status unavailable: " + _short(status["error"].get("message", "unknown error"), 500))
        if event_name in {"SessionStart", "UserPromptSubmit"}:
            return _context(event_name, _card(status, project, book_id, event))
        if event_name == "Stop":
            reason = _continue_reason(status, event)
            return {"decision": "block", "reason": reason} if reason else {}
        if _plan_mode(event):
            return _context(event_name, "Novel Weaver: plan mode is read-only; inspect book sources and state without requesting mutations.")
        if event_name == "PreToolUse":
            return _context(event_name, "Novel Weaver: use book tools for authoritative source and memory changes. Chapter saves require fresh context; acceptance requires the exact saved source's staged batch and structured review. Pass this turn's run_id when available. Markdown projections do not replace authoritative source versions.")
        data = status.get("data") or {}
        lines = []
        actions = _actions(status)
        if actions:
            lines.append("Novel Weaver next actions: " + actions)
        changed = data.get("changed_projections") or []
        if changed:
            paths = [item.get("path", "") if isinstance(item, dict) else item for item in changed[:6]]
            lines.append("Changed projections: " + ", ".join(_short(path, 160) for path in paths) + ". Inspect the changes and use source_save for intentional edits; do not silently import them.")
        return _context(event_name, "\n".join(lines))
    except Exception as exc:
        return _context(event_name, "Novel Weaver hook could not read book state: " + _short(exc, 500))

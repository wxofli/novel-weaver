"""Read-only host hooks. These hints never execute the actions they suggest."""
from __future__ import annotations

import json
import re
from pathlib import Path


CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse"}
SUPPORTED_EVENTS = CONTEXT_EVENTS | {"Stop"}
AUTOMATED_NEEDS = {"memory.stage", "review"}


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
    return " ".join(str(value).splitlines())[:limit]


def _session_card(status: dict, project: str, book_id: str) -> str:
    data = status.get("data") or {}
    lines = ["Novel Weaver book", f"book_id={book_id}", f"project={_short(project, 300)}",
             f"title={json.dumps(_short(data.get('title', ''), 100), ensure_ascii=False)}",
             f"accepted_chapter={data.get('latest_chapter', 0)} memory_frontier={data.get('memory_frontier', 0)}"]
    if data.get("active_job"):
        job = data["active_job"]
        lines.append(f"Memory synchronization pending ({job['position']}/{job['total']}).")
    return "\n".join(lines)


def _prompt_card(status: dict, event: dict) -> str:
    data = status.get("data") or {}
    run = _run_id(event)
    lines = [f"Novel Weaver run_id={run}. Pass it to this turn's book work when applicable."] if run else []
    if _plan_mode(event):
        lines.append("Plan mode is read-only. Inspect the book without changing it.")
    waiting = [_short(item["source_version"], 80) for item in data.get("pending_work", []) if item.get("awaiting_author")]
    if waiting:
        lines.append("Awaiting author adoption: " + ", ".join(waiting[:3]) + ".")
    return "\n".join(lines)


def _edited_paths(event: dict, cwd: Path) -> set[Path]:
    name = str(event.get("tool_name", ""))
    payload = event.get("tool_input") or {}
    if not isinstance(payload, dict):
        return set()
    if name == "apply_patch":
        paths = re.findall(r"^\*\*\* (?:Update File|Add File|Delete File|Move to): (.+)$", str(payload.get("command", "")), re.MULTILINE)
    elif name in {"Write", "Edit", "MultiEdit"} and isinstance(payload.get("file_path"), str):
        paths = [payload["file_path"]]
    else:
        paths = []
    return {(cwd / path.strip()).resolve() for path in paths if Path(path.strip()).suffix.lower() == ".md"}


def _post_notice(event: dict, cwd: Path) -> str:
    name = str(event.get("tool_name", ""))
    if re.fullmatch(r"mcp__[^ ]*novel[_-]weaver__\w+", name):
        args = event.get("tool_input") or {}
        request = args.get("request", {}) if isinstance(args, dict) else {}
        response = event.get("tool_response") or {}
        if not isinstance(request, dict) or not isinstance(response, dict) or response.get("isError") or response.get("is_error"):
            return ""
        result = response.get("structuredContent", response.get("structured_content", response))
        project, book_id = request.get("project"), request.get("book_id")
        if not isinstance(result, dict) or result.get("status") != "partial" or result.get("error"):
            return ""
        if not all(isinstance(value, str) and value for value in (project, book_id)) or not Path(project).is_absolute() or result.get("book_id") != book_id:
            return ""
        status = execute("book_status", {"project": project, "book_id": book_id, "brief": True})
        if not status.get("error"):
            return f"Novel Weaver: the operation on book_id={_short(book_id, 80)} reported partial completion. Inspect its warnings before retrying."
        return ""

    edited = _edited_paths(event, cwd)
    if not edited:
        return ""
    book = discover_book(str(cwd))
    if not book:
        return ""
    project, book_id = book
    root = Path(project)
    if not any(path.is_relative_to(root / "正文") or path.is_relative_to(root / "草稿") for path in edited):
        return ""
    status = execute("book_status", {"project": project, "book_id": book_id})
    changed = (status.get("data") or {}).get("changed_projections", [])
    paths = [item["path"] for item in changed if (root / item["path"]).resolve() in edited]
    if not paths:
        return ""
    return "Novel Weaver tracked Markdown changed: " + ", ".join(_short(path) for path in paths[:4]) + ". Inspect the diff before saving a new source version."


def _continue_reason(status: dict, event: dict) -> str | None:
    run_id = _run_id(event)
    data = status.get("data") or {}
    if not run_id or event.get("stop_hook_active") is not False or data.get("awaiting_author") or data.get("active_job"):
        return None
    pending = []
    for item in data.get("pending_work", []):
        if not isinstance(item, dict) or item.get("run_id") != run_id:
            continue
        if item.get("awaiting_author") or item.get("status") == "awaiting_author" or item.get("automated") is False:
            continue
        needs = item.get("needs", [])
        if needs and set(needs) <= AUTOMATED_NEEDS:
            pending.append(f"{_short(item.get('source_version', 'saved source'), 80)}: {', '.join(needs)}")
    if not pending:
        return None
    return (f"Novel Weaver has incomplete candidate work for this run ({run_id}): " + "; ".join(pending[:5]) + ". Complete only the listed memory staging or review of those saved drafts. Leave adoption to the author.")[:1500]


def handle_event(event_name: str, event: dict) -> dict:
    """Return official hook JSON, swallowing failures so host sessions stay usable."""
    if event_name not in SUPPORTED_EVENTS or not isinstance(event, dict) or _cancelled(event):
        return {}
    if event_name == "Stop" and (_plan_mode(event) or event.get("stop_hook_active") is not False or not _run_id(event)):
        return {}
    try:
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return {}
        if event_name == "PostToolUse":
            return _context(event_name, "" if _plan_mode(event) else _post_notice(event, Path(cwd)))
        book = discover_book(cwd)
        if book is None:
            return {}
        project, book_id = book
        status = execute("book_status", {"project": project, "book_id": book_id, "brief": True})
        if status.get("error"):
            return _context(event_name, "Novel Weaver status unavailable: " + _short(status["error"].get("message", "unknown error"), 500))
        if event_name == "SessionStart":
            return _context(event_name, _session_card(status, project, book_id))
        if event_name == "UserPromptSubmit":
            return _context(event_name, _prompt_card(status, event))
        reason = _continue_reason(status, event)
        return {"decision": "block", "reason": reason} if reason else {}
    except Exception as exc:
        return _context(event_name, "Novel Weaver hook could not read book state: " + _short(exc, 500))

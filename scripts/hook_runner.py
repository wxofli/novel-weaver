"""Fail-open, offline launcher for Novel Weaver's read-only host hooks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
SUPPORTED_EVENTS = CONTEXT_EVENTS | {"Stop", "PreCompact", "Interrupt"}


def _command(root: Path, event: str) -> list[str]:
    candidates = (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python")
    if os.name != "nt":
        candidates = candidates[::-1]
    for interpreter in candidates:
        if interpreter.is_file():
            return [str(interpreter), "-m", "novel_weaver.cli", "hook", "run", event]
    return [
        shutil.which("uv") or "uv", "run", "--project", str(root),
        "--locked", "--offline", "--no-sync", "novelctl", "hook", "run", event,
    ]


def _valid_output(value: object, event: str) -> bool:
    """Allow the official JSON shapes emitted by this read-only hook handler."""
    if not isinstance(value, dict):
        return False
    if not value:
        return True
    if event in CONTEXT_EVENTS and set(value) == {"hookSpecificOutput"}:
        output = value["hookSpecificOutput"]
        return (
            isinstance(output, dict)
            and set(output) == {"hookEventName", "additionalContext"}
            and output["hookEventName"] == event
            and isinstance(output["additionalContext"], str)
        )
    return (
        event == "Stop"
        and set(value) == {"decision", "reason"}
        and value["decision"] == "block"
        and isinstance(value["reason"], str)
        and bool(value["reason"].strip())
    )


def _diagnostic(message: str) -> None:
    print("Novel Weaver hook launcher: " + message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    result: dict = {}
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if len(arguments) != 1 or arguments[0] not in SUPPORTED_EVENTS:
            raise ValueError("expected one supported hook event")
        event = arguments[0]
        stream = getattr(sys.stdin, "buffer", None)
        payload = stream.read() if stream is not None else sys.stdin.read().encode("utf-8")
        environment = os.environ.copy()
        environment.update({
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        })
        completed = subprocess.run(
            _command(ROOT, event), input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=2 if event == "Interrupt" else 8, env=environment, cwd=ROOT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.stderr:
            _diagnostic(completed.stderr.decode("utf-8", errors="replace").strip()[:2000])
        if completed.returncode != 0:
            raise RuntimeError(f"child exited with code {completed.returncode}")
        value = json.loads(completed.stdout.decode("utf-8"))
        if not _valid_output(value, event):
            raise ValueError("child output is not a supported hook JSON object")
        result = value
    except (Exception, KeyboardInterrupt) as exc:
        _diagnostic(f"{type(exc).__name__}: {exc}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

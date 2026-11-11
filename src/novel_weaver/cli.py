"""Argument-parser adapter for the transport-independent Novel Weaver core."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import UnionType
from typing import Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from .errors import NovelError
from .schemas import ACTION_MODELS


COMMANDS = {
    "book": {"init": "book_init", "status": "book_status", "import": "book_import"},
    "source": {"get": "source_get", "save": "source_save", "accept": "source_accept"},
    "context": {"build": "context_build"},
    "memory": {"stage": "memory_stage", "sync": "memory_sync"},
    "graph": {"query": "graph_query"},
    "index": {"status": "index_status", "update": "index_update", "rebuild": "index_rebuild"},
    "doctor": {"check": "doctor_check", "repair": "doctor_repair"},
}
COMMON_FIELDS = {"project", "book_id", "operation_id", "run_id"}


def execute(action: str, payload: dict) -> dict:
    """Import the core only when an actual book operation is requested."""
    from .service import execute as core_execute

    return core_execute(action, payload)


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise UsageError(message)


def _common_options(parser: argparse.ArgumentParser) -> None:
    for field in sorted(COMMON_FIELDS):
        parser.add_argument("--" + field.replace("_", "-"), default=argparse.SUPPRESS)
    parser.add_argument("--input", metavar="FILE|-", default=argparse.SUPPRESS, help="UTF-8 JSON request; explicit flags override its fields")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="emit one compact JSON envelope")


def _json_value(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"expected JSON: {exc.msg}") from exc


def _field_options(parser: argparse.ArgumentParser, model: type[BaseModel]) -> None:
    for name, field in model.model_fields.items():
        if name in COMMON_FIELDS:
            continue
        annotation = field.annotation
        if get_origin(annotation) in (Union, UnionType):
            options = [option for option in get_args(annotation) if option is not type(None)]
            if len(options) == 1:
                annotation = options[0]
        kwargs = {"default": argparse.SUPPRESS}
        if annotation is bool:
            kwargs["action"] = argparse.BooleanOptionalAction
        elif get_origin(annotation) is Literal:
            values = get_args(annotation)
            kwargs.update(type=type(values[0]), choices=values)
        elif annotation in (str, int, float):
            kwargs["type"] = annotation
        else:
            kwargs.update(type=_json_value, metavar="JSON")
        parser.add_argument("--" + name.replace("_", "-"), **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="novelctl", description="Book-isolated writing memory and tools")
    _common_options(parser)
    groups = parser.add_subparsers(dest="_group", required=True)
    for group, commands in COMMANDS.items():
        group_parser = groups.add_parser(group)
        _common_options(group_parser)
        subcommands = group_parser.add_subparsers(dest="_command", required=True)
        for command, action in commands.items():
            leaf = subcommands.add_parser(command)
            _common_options(leaf)
            _field_options(leaf, ACTION_MODELS[action])
            leaf.set_defaults(_action=action)
    search_parser = groups.add_parser("search")
    _common_options(search_parser)
    _field_options(search_parser, ACTION_MODELS["search"])
    search_parser.set_defaults(_action="search")
    hook_parser = groups.add_parser("hook")
    hook_commands = hook_parser.add_subparsers(dest="_command", required=True)
    hook_run = hook_commands.add_parser("run")
    hook_run.add_argument("event")
    hook_run.set_defaults(_local="hook")
    mcp_parser = groups.add_parser("mcp")
    mcp_commands = mcp_parser.add_subparsers(dest="_command", required=True)
    mcp_commands.add_parser("serve").set_defaults(_local="mcp")
    return parser


def _utf8_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _error(code: str, message: str, exit_code: int = 2, retryable: bool = False) -> dict:
    return {
        "schema_version": 1, "status": "error", "book_id": None,
        "revision": None, "data": {}, "warnings": [],
        "error": {"code": code, "message": message, "retryable": retryable, "exit_code": exit_code},
        "next_actions": [],
    }


def _output(result: dict, compact: bool) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=None if compact else 2))
    error = result.get("error")
    if error:
        print(f"{error.get('code', 'error')}: {error.get('message', 'Operation failed')}", file=sys.stderr)
        return int(error.get("exit_code", 3))
    return 0


def _read_input(location: str) -> dict:
    raw = sys.stdin.read() if location == "-" else Path(location).read_text(encoding="utf-8-sig")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise UsageError("--input must contain a JSON object")
    return value


def _hook(event_name: str) -> int:
    try:
        from .hooks import handle_event

        event = json.loads(sys.stdin.read())
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        result = handle_event(event_name, event)
    except Exception as exc:
        print(f"Novel Weaver hook: {exc}", file=sys.stderr)
        result = {}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    compact = "--json" in argv
    try:
        arguments = vars(build_parser().parse_args(argv))
        if arguments.get("_local") == "hook":
            return _hook(arguments["event"])
        if arguments.get("_local") == "mcp":
            from .mcp_server import serve

            serve()
            return 0
        action = arguments["_action"]
        payload = _read_input(arguments["input"]) if "input" in arguments else {}
        payload.update({key: value for key, value in arguments.items() if not key.startswith("_") and key not in {"input", "json"}})
        payload = ACTION_MODELS[action].model_validate(payload).model_dump(mode="json")
        return _output(execute(action, payload), compact)
    except SystemExit as exc:
        return int(exc.code or 0)
    except (UsageError, ValidationError, json.JSONDecodeError, OSError, UnicodeError) as exc:
        return _output(_error("invalid_request", str(exc)), compact)
    except NovelError as exc:
        return _output(_error(exc.code, exc.message, exc.exit_code, exc.retryable), compact)
    except Exception as exc:
        return _output(_error("adapter_error", str(exc), 3), compact)


if __name__ == "__main__":
    raise SystemExit(main())

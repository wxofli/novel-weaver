"""Transport tests keep the shared core mocked only at its adapter boundary."""
from __future__ import annotations

import asyncio
import builtins
import io
import json
from pathlib import Path
import sys
import uuid

import pytest


def envelope(data=None, *, next_actions=None):
    return {
        "schema_version": 1,
        "status": "ok",
        "book_id": "book-1",
        "revision": 3,
        "data": data or {},
        "warnings": [],
        "error": None,
        "next_actions": next_actions or [],
    }


@pytest.fixture
def cli(monkeypatch):
    from novel_weaver import cli

    calls = []

    def execute(action, payload):
        calls.append((action, payload))
        return envelope({"title": "星河"})

    monkeypatch.setattr(cli, "execute", execute)
    return cli, calls


def test_cli_explicit_flags_override_json_without_erasing_input(cli, tmp_path, capsys):
    module, calls = cli
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"project": "书", "book_id": "b", "query": "旧", "limit": 7, "explain": False}), encoding="utf-8")
    assert module.main(["search", "--input", str(request), "--query", "新", "--json"]) == 0
    assert calls == [("search", {"project": "书", "book_id": "b", "query": "新", "chapter": None, "scope": "canon", "limit": 7, "explain": False})]
    captured = capsys.readouterr()
    assert json.loads(captured.out)["data"]["title"] == "星河"
    assert captured.err == ""


@pytest.mark.parametrize("argv", [["--json", "book", "status"], ["book", "--json", "status"], ["book", "status", "--json"]])
def test_cli_common_flags_work_before_and_after_subcommands(cli, argv, capsys):
    module, calls = cli
    assert module.main(argv) == 0
    assert calls[0][0] == "book_status"
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


@pytest.mark.parametrize("argv", [
    ["source", "save", "--kind", "idea", "--logical-id", "x", "--content", "字"],
    ["search", "--query", "x", "--limit", "not-an-int"],
    ["book", "unknown"],
    ["search", "--query", "x", "--unexpected", "value"],
    ["search", "--query", "x", "--lim", "3"],
])
def test_cli_bad_arguments_produce_single_json_error(cli, argv, capsys):
    module, calls = cli
    assert module.main([*argv, "--json"]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "error"
    assert result["error"]["exit_code"] == 2
    assert captured.err
    assert calls == []


@pytest.mark.parametrize("raw", ["{broken", "[]", '{"query":"x","unknown":1}'])
def test_cli_invalid_stdin_input_is_structured(cli, raw, monkeypatch, capsys):
    module, calls = cli
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    assert module.main(["search", "--input", "-", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    assert not calls


def test_cli_nested_json_and_false_boolean_flags(cli, capsys):
    module, calls = cli
    assert module.main(["context", "build", "--entity-ids", '["阿青","阿白"]', "--chapter", "2", "--json"]) == 0
    assert calls[-1][1]["entity_ids"] == ["阿青", "阿白"]
    assert calls[-1][1]["chapter"] == 2
    assert module.main(["search", "--query", "线索", "--no-explain", "--json"]) == 0
    assert calls[-1][1]["explain"] is False
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_cli_book_init_requires_own_identity_fields_only(cli, capsys):
    module, calls = cli
    assert module.main(["book", "init", "--project", "书", "--title", "小说", "--operation-id", "init-1", "--json"]) == 0
    assert calls[-1] == ("book_init", {"project": "书", "title": "小说", "operation_id": "init-1"})
    capsys.readouterr()


@pytest.mark.parametrize("action,command,payload", [
    ("book_init", ["book", "init"], {"project": "p", "title": "t", "operation_id": "i"}),
    ("book_status", ["book", "status"], {}),
    ("book_import", ["book", "import"], {"mode": "preview"}),
    ("source_get", ["source", "get"], {"source_version": "v"}),
    ("source_save", ["source", "save"], {"kind": "idea", "logical_id": "i", "content": "text"}),
    ("source_accept", ["source", "accept"], {"source_version": "v", "expected_revision": 0}),
    ("context_build", ["context", "build"], {}),
    ("memory_stage", ["memory", "stage"], {"source_version": "v", "base_revision": 0, "delta": {"source_hash": "h"}}),
    ("memory_sync", ["memory", "sync"], {"job_id": "j"}),
    ("search", ["search"], {"query": "q"}),
    ("graph_query", ["graph", "query"], {}),
    ("index_status", ["index", "status"], {}),
    ("index_update", ["index", "update"], {}),
    ("index_rebuild", ["index", "rebuild"], {}),
    ("doctor_check", ["doctor", "check"], {}),
    ("doctor_repair", ["doctor", "repair"], {}),
])
def test_cli_routes_every_core_action(cli, action, command, payload, monkeypatch, capsys):
    from novel_weaver.schemas import ACTION_MODELS, WriteRequest

    module, calls = cli
    if issubclass(ACTION_MODELS[action], WriteRequest):
        payload = {"project": "p", "book_id": "b", "operation_id": "op", **payload}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert module.main([*command, "--input", "-", "--json"]) == 0
    assert calls[-1][0] == action
    capsys.readouterr()


def test_cli_preserves_core_error_and_exit_code(cli, monkeypatch, capsys):
    module, _ = cli
    result = envelope()
    result.update(status="error", error={"code": "stale_revision", "message": "重新读取", "retryable": True, "exit_code": 4})
    monkeypatch.setattr(module, "execute", lambda *_: result)
    assert module.main(["book", "status", "--json"]) == 4
    captured = capsys.readouterr()
    assert json.loads(captured.out) == result
    assert "重新读取" in captured.err


def test_cli_hook_bad_json_never_blocks_host(cli, monkeypatch, capsys):
    module, calls = cli
    monkeypatch.setattr(sys, "stdin", io.StringIO("{broken"))
    assert module.main(["hook", "run", "Stop"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert not calls


@pytest.fixture
def hook_book(tmp_path):
    root = tmp_path / "book"
    marker = root / ".novel" / "project.json"
    marker.parent.mkdir(parents=True)
    book_id = str(uuid.uuid4())
    marker.write_text(json.dumps({"book_id": book_id, "title": "星河"}), encoding="utf-8")
    child = root / "chapters"
    child.mkdir()
    return root, child, book_id


@pytest.fixture
def hooks(monkeypatch):
    from novel_weaver import hooks

    calls = []
    status = envelope({"title": "星河", "latest_chapter": 4, "memory_frontier": 3,
                       "pending_work": [{"source_version": "v4", "run_id": "session:turn", "needs": ["memory.stage", "review"]}],
                       "awaiting_author": False, "changed_projections": []})

    def execute(action, payload):
        calls.append((action, payload))
        return status

    monkeypatch.setattr(hooks, "execute", execute)
    return hooks, status, calls


def event(child, **extra):
    return {"cwd": str(child), "session_id": "session", "turn_id": "turn", **extra}


def additional_context(result):
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_hook_session_and_prompt_send_distinct_brief_context(hooks, hook_book):
    module, status, calls = hooks
    root, child, book_id = hook_book
    status["data"]["title"] = "星" * 2000
    session = additional_context(module.handle_event("SessionStart", event(child)))
    prompt = additional_context(module.handle_event("UserPromptSubmit", event(child)))
    assert "accepted_chapter=4" in session and "session:turn" not in session
    assert "session:turn" in prompt and "accepted_chapter" not in prompt
    assert len(session) < 600 and len(prompt) < 180
    assert calls == [("book_status", {"project": str(root), "book_id": book_id, "brief": True})] * 2


def test_hook_uses_closest_book_marker(hooks, hook_book):
    module, _, calls = hooks
    _, child, _ = hook_book
    nested = child / "nested"
    marker = nested / ".novel" / "project.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"book_id": str(uuid.uuid4())}), encoding="utf-8")
    module.handle_event("SessionStart", event(nested))
    assert calls[-1][1]["project"] == str(nested)


def test_hook_post_tool_ignores_failed_calls_and_uses_the_explicit_book_for_partial_results(hooks, hook_book):
    module, _, calls = hooks
    root, child, _ = hook_book
    other = {"project": str(root.parent / "other"), "book_id": "other-book"}
    base = event(child, tool_name="mcp__novel_weaver__source_accept", tool_input={"request": other})
    assert module.handle_event("PostToolUse", dict(base, tool_response={"isError": True})) == {}
    assert calls == []
    partial = {"structuredContent": {"status": "partial", "book_id": other["book_id"]}}
    result = module.handle_event("PostToolUse", dict(base, tool_response=partial))
    assert "partial completion" in additional_context(result)
    assert calls == [("book_status", dict(other, brief=True))]


def test_hook_reports_only_the_edited_tracked_projection(hooks, hook_book):
    module, status, _ = hooks
    root, child, _ = hook_book
    path = "正文/第0004章.md"
    status["data"]["changed_projections"] = [{"path": path, "source_version": "v4", "actual_hash": "h"},
                                               {"path": "正文/第0003章.md"}]
    edited = event(child, tool_name="apply_patch", tool_input={"command": f"*** Update File: {root / path}"})
    context = additional_context(module.handle_event("PostToolUse", edited))
    assert "正文/第0004章.md" in context
    assert "第0003章.md" not in context and "actual_hash" not in context


def test_hook_stop_blocks_once_only_for_current_run(hooks, hook_book):
    module, _, calls = hooks
    _, child, _ = hook_book
    result = module.handle_event("Stop", event(child, stop_hook_active=False))
    assert result["decision"] == "block"
    assert "v4" in result["reason"]
    assert module.handle_event("Stop", event(child, stop_hook_active=True)) == {}
    assert all(action == "book_status" for action, _ in calls)


def test_hook_stop_requires_explicit_inactive_reentry_flag(hooks, hook_book):
    module, _, _ = hooks
    _, child, _ = hook_book
    assert module.handle_event("Stop", event(child)) == {}


@pytest.mark.parametrize("extra", [{"turn_id": "another"}, {"turn_id": None}, {"session_id": None}, {"permission_mode": "plan"}, {"cancelled": True}, {"interrupted": True}])
def test_hook_stop_never_forces_unrelated_or_readonly_turns(hooks, hook_book, extra):
    module, _, _ = hooks
    _, child, _ = hook_book
    assert module.handle_event("Stop", event(child, stop_hook_active=False, **extra)) == {}


@pytest.mark.parametrize("state", [{"awaiting_author": True}, {"active_job": {"job_id": "sync-existing"}}])
def test_hook_stop_leaves_author_decisions_and_sync_jobs_to_the_workflow(hooks, hook_book, state):
    module, status, _ = hooks
    _, child, _ = hook_book
    status["data"].update(state)
    assert module.handle_event("Stop", event(child, stop_hook_active=False)) == {}


@pytest.mark.parametrize("needs", [["review", "awaiting_author"], ["memory.stage", "context.build"], ["review", "accept"]])
def test_hook_stop_does_not_continue_author_work_or_stale_drafts(hooks, hook_book, needs):
    module, status, _ = hooks
    _, child, _ = hook_book
    status["data"]["pending_work"][0]["needs"] = needs
    assert module.handle_event("Stop", event(child, stop_hook_active=False)) == {}


def test_hook_plan_mode_card_never_requests_writes(hooks, hook_book):
    module, _, _ = hooks
    _, child, _ = hook_book
    context = additional_context(module.handle_event("UserPromptSubmit", event(child, permission_mode="plan")))
    assert "read-only" in context.lower()
    assert "memory_stage" not in context


def test_hook_nonbook_is_noop_and_never_calls_core(hooks, tmp_path):
    module, _, calls = hooks
    assert module.handle_event("SessionStart", event(tmp_path)) == {}
    assert module.handle_event("Interrupt", event(tmp_path)) == {}
    assert calls == []


def test_legacy_pretool_event_does_not_requery_state(hooks, hook_book):
    module, _, calls = hooks
    _, child, _ = hook_book
    result = module.handle_event("PreToolUse", event(child, tool_name="Bash", tool_input={"command": "novelctl source save --input request.json"}))
    assert result == {} and calls == []


def test_hook_core_failure_returns_context_without_raising(hooks, hook_book, monkeypatch):
    module, _, _ = hooks
    _, child, _ = hook_book

    def fail(*_):
        raise OSError("unavailable")

    monkeypatch.setattr(module, "execute", fail)
    assert "unavailable" in additional_context(module.handle_event("SessionStart", event(child)))
    assert module.handle_event("Stop", event(child, stop_hook_active=False)) == {}


def test_mcp_registers_shared_typed_request_schema():
    pytest.importorskip("mcp.server")
    from novel_weaver import mcp_server
    from novel_weaver.schemas import ACTION_MODELS

    server = mcp_server.build_server()
    registered = asyncio.run(server.list_tools())
    assert {tool.name for tool in registered} == set(ACTION_MODELS)
    for tool in registered:
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
        assert set(schema["properties"]) == {"request"}
        assert schema["required"] == ["request"]
        request = schema["properties"]["request"]
        model_schema = schema["$defs"][request["$ref"].rsplit("/", 1)[-1]]
        assert model_schema["additionalProperties"] is False
        assert set(model_schema["properties"]) == set(ACTION_MODELS[tool.name].model_fields)
        output_schema = tool.output_schema if hasattr(tool, "output_schema") else tool.outputSchema
        assert output_schema["type"] == "object"
        assert output_schema["additionalProperties"] is True


def test_mcp_tool_annotations_describe_read_write_and_provider_effects():
    pytest.importorskip("mcp.server")
    from novel_weaver import mcp_server

    expected = {
        "book_init": (False, True, False, False),
        "book_status": (True, True, False, False),
        "book_import": (False, True, False, False),
        "source_get": (True, True, False, False),
        "source_save": (False, True, False, False),
        "source_accept": (False, True, True, False),
        "context_build": (False, False, False, True),
        "memory_stage": (False, True, False, False),
        "memory_sync": (False, True, True, False),
        "search": (True, True, False, True),
        "graph_query": (True, True, False, False),
        "index_status": (True, True, False, False),
        "index_update": (False, True, False, True),
        "index_rebuild": (False, True, True, True),
        "doctor_check": (True, True, False, False),
        "doctor_repair": (False, True, True, False),
    }
    registered = asyncio.run(mcp_server.build_server().list_tools())
    assert {tool.name for tool in registered} == set(expected)
    for tool in registered:
        assert tool.annotations is not None
        annotations = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        readonly, idempotent, destructive, open_world = expected[tool.name]
        assert annotations == {
            "readOnlyHint": readonly,
            "idempotentHint": idempotent,
            "destructiveHint": destructive,
            "openWorldHint": open_world,
        }


def test_mcp_typed_handlers_call_same_core_without_captured_parameters(monkeypatch):
    pytest.importorskip("mcp.server")
    from novel_weaver import mcp_server

    calls = []
    result = envelope({"answer": "汉字"})

    def execute(action, payload):
        calls.append((action, payload))
        return result

    monkeypatch.setattr(mcp_server, "execute", execute)
    server = mcp_server.build_server()
    output = asyncio.run(server.call_tool("search", {"request": {"query": "线索"}}))
    structured = getattr(output, "structured_content", getattr(output, "structuredContent", None))
    assert structured == result
    assert getattr(output, "is_error", getattr(output, "isError", False)) is False
    assert json.loads(output.content[0].text) == result
    asyncio.run(server.call_tool("book_status", {"request": {"project": "p", "book_id": "b"}}))
    assert [action for action, _ in calls] == ["search", "book_status"]
    assert calls[0][1]["query"] == "线索"
    assert calls[1][1] == {"project": "p", "book_id": "b", "brief": False}


def test_mcp_rejects_unknown_request_fields_before_core(monkeypatch):
    pytest.importorskip("mcp.server")
    from novel_weaver import mcp_server

    calls = []
    monkeypatch.setattr(mcp_server, "execute", lambda *args: calls.append(args))
    server = mcp_server.build_server()
    with pytest.raises(Exception, match="[Ee]xtra"):
        asyncio.run(server.call_tool("search", {"request": {"query": "q", "surprise": True}}))
    assert calls == []


def test_mcp_official_client_marks_core_failures_and_preserves_envelope(tmp_path):
    mcp = pytest.importorskip("mcp")
    if not hasattr(mcp, "Client"):
        pytest.skip("in-process client test uses the project's pinned MCP v2 SDK")
    from novel_weaver import mcp_server
    from novel_weaver.service import execute

    request = {"project": str(tmp_path / "missing-book"), "book_id": None}
    expected = execute("book_status", request)
    assert expected["status"] == "error"
    assert expected["error"]["code"] == "BOOK_NOT_FOUND"

    async def call():
        async with mcp.Client(mcp_server.build_server(), read_timeout_seconds=10) as client:
            return await client.call_tool("book_status", {"request": request})

    result = asyncio.run(call())
    assert result.is_error is True
    assert result.structured_content == expected
    assert json.loads(result.content[0].text) == expected


def test_mcp_missing_sdk_gives_install_guidance(monkeypatch):
    from novel_weaver import mcp_server

    original_import = builtins.__import__

    def without_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError("missing mcp")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_mcp)
    with pytest.raises(RuntimeError, match="pip install"):
        mcp_server.build_server()


def test_mcp_stdio_lists_tools_through_official_client():
    mcp = pytest.importorskip("mcp")
    if not hasattr(mcp, "Client"):
        pytest.skip("stdio smoke test uses the project's pinned MCP v2 SDK")
    from novel_weaver.schemas import ACTION_MODELS

    root = Path(__file__).resolve().parents[1]
    parameters = mcp.StdioServerParameters(
        command=sys.executable,
        args=["-m", "novel_weaver.cli", "mcp", "serve"],
        cwd=str(root),
        env={"PYTHONPATH": str(root / "src"), "PYTHONIOENCODING": "utf-8"},
    )

    async def list_tools():
        async with mcp.Client(parameters, read_timeout_seconds=10) as client:
            return await client.list_tools()

    listed = asyncio.run(list_tools())
    assert {tool.name for tool in listed.tools} == set(ACTION_MODELS)

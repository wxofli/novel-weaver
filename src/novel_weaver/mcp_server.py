"""Official MCP SDK adapter; book tools use the same models and core as CLI."""
from __future__ import annotations

import json
import sys
from typing import Annotated, Any

from pydantic import BaseModel

from .schemas import ACTION_MODELS


DESCRIPTIONS = {
    "book_init": "Initialize a book project and its UUID. Requires an explicit project, title and operation_id.",
    "book_status": "Read this book's revision, chapter and memory progress, pending work and next actions.",
    "book_import": "Preview or start an explicit chapter import. Preview the mapping before starting it.",
    "source_get": "Read an immutable authoritative source version, with bounded character pagination.",
    "source_save": "Save a versioned source. Chapters require a fresh context_id; reviews require a structured Review.",
    "source_accept": "Accept the exact saved chapter with its staged batch_id, review_id and expected revision.",
    "context_build": "Build bounded book context for writing, revision, review, planning or queries. Preserve the returned context_id.",
    "memory_stage": "Stage a structured, evidence-backed MemoryDelta for an exact source hash and base revision.",
    "memory_sync": "Read the next accepted source of an active sync job or apply its exact next memory delta.",
    "search": "Search this book's canon, plan or references with chapter and evidence filters.",
    "graph_query": "Query evidence-backed book entities, neighbors, paths or timelines with chapter and point-of-view filters.",
    "index_status": "Read the book's text and optional vector index state.",
    "index_update": "Update the derived book index. Optional embeddings require explicit configuration.",
    "index_rebuild": "Rebuild this book's derived index from authoritative storage.",
    "doctor_check": "Read book health, source and projection consistency, and recovery suggestions.",
    "doctor_repair": "Repair recoverable derived book state using authoritative storage.",
}
READ_ONLY_ACTIONS = frozenset({"book_status", "source_get", "search", "graph_query", "index_status", "doctor_check"})
DESTRUCTIVE_ACTIONS = frozenset({"source_accept", "memory_sync", "index_rebuild", "doctor_repair"})
# Context assembly also searches passages and may use configured providers.
OPEN_WORLD_ACTIONS = frozenset({"context_build", "search", "index_update", "index_rebuild"})


def execute(action: str, payload: dict) -> dict:
    from .service import execute as core_execute

    return core_execute(action, payload)


def _server_class():
    try:
        from mcp.server import MCPServer

        return MCPServer
    except ImportError as v2_error:
        try:
            from mcp.server.fastmcp import FastMCP

            return FastMCP
        except ImportError:
            raise RuntimeError("The official MCP SDK is unavailable. Install project dependencies with: python -m pip install -e . (the project requires mcp==2.3.0).") from v2_error


def _handler(action: str, request_model: type[BaseModel]):
    """Create one signature per tool without leaking closure/default parameters."""
    from mcp.types import CallToolResult, TextContent

    def call(request):
        result = execute(action, request.model_dump(mode="json"))
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=result.get("status") == "error",
        )

    call.__name__ = action
    call.__doc__ = DESCRIPTIONS.get(action, action.replace("_", " "))
    call.__annotations__ = {"request": request_model, "return": Annotated[CallToolResult, dict[str, Any]]}
    return call


def build_server():
    server_class = _server_class()
    from mcp.types import ToolAnnotations

    server = server_class(
        "Novel Weaver",
        instructions="Use the typed request object for each tool. Authoritative book writes require explicit project, book_id and operation_id. Use book_status and context_build to resume a book workflow; never index ordinary conversation as book memory.",
    )
    for action, model in ACTION_MODELS.items():
        annotations = ToolAnnotations(
            read_only_hint=action in READ_ONLY_ACTIONS,
            idempotent_hint=action in READ_ONLY_ACTIONS or "operation_id" in model.model_fields,
            destructive_hint=action in DESTRUCTIVE_ACTIONS,
            open_world_hint=action in OPEN_WORLD_ACTIONS,
        )
        server.tool(
            name=action,
            description=DESCRIPTIONS.get(action),
            annotations=annotations,
            structured_output=True,
        )(_handler(action, model))
    return server


def serve() -> None:
    build_server().run(transport="stdio")


def main() -> int:
    try:
        serve()
    except Exception as exc:
        print(f"Novel Weaver MCP: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

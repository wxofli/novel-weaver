# Novel Weaver implementation contract

One Python core implements every operation; CLI and MCP use
`novel_weaver.service.execute(action: str, payload: dict) -> dict` and the
Pydantic classes in `novel_weaver.schemas.ACTION_MODELS`.

Results contain schema_version=1, status, book_id, revision, data, warnings,
error, next_actions. Errors include code, message, retryable and exit_code.
MCP tools take a typed `request` object. CLI common options are --project,
--book-id, --operation-id, --run-id, --input FILE|- and --json. CLI flags
override JSON only when explicitly supplied; unknown fields are errors.

CLI commands map to ACTION_MODELS: book init/status/import; source get/save/accept;
context build; memory stage/sync; search; graph query; index status/update/rebuild;
doctor check/repair. Additional local commands: hook run EVENT; mcp serve.

Core writes require explicit project, book_id, operation_id (book_init creates
its identity). Source chapter saves require chapter and fresh context_id;
chapter acceptance requires the exact source's batch_id and review_id.
Review is saved with kind=review and the structured Review object. Memory
stage accepts MemoryDelta. memory_sync next/apply shares the sync-job contract:
only an active job's next accepted source can be replayed. Source get reads
immutable DB versions, not mutable Markdown projections.

CLI JSON stdout is a single envelope; stderr contains diagnostics. Hooks are
read-only and output official hook JSON instead of a CLI envelope. Hook run
reads stdin event JSON, discovers the closest .novel/project.json from cwd,
uses core status for book-scoped next_actions, and never calls models or
network. Stop continues at most once, only for this run's incomplete automated
work, never awaiting_author. run_id is session_id:turn_id when supplied by
hooks. Hook errors must not accidentally exit 2 and block the host.

MCP tools call the core directly with the shared models; they don't launch CLI
subprocesses. All book operations verify marker UUID against the database.

Execution checklist:
- [x] Core: isolation, source versions, evidence-backed graph and transactions.
- [x] Retrieval: temporal/knowledge filters, FTS, context tickets and budgets.
- [x] CLI, MCP and read-only hook adapters.
- [x] Eight authoring skills, plugin manifests and setup documentation.
- [x] Import, suffix replay, projections, vectors and recovery.
- [x] Unit/integration/stdio tests and benchmark.

See [verification.md](verification.md) for measured results and the remaining
host-installation acceptance boundary.

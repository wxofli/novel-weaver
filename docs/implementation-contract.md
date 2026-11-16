# Novel Weaver implementation contract

One Python core implements every operation; CLI and MCP use
`novel_weaver.service.execute(action: str, payload: dict) -> dict` and the
Pydantic classes in `novel_weaver.schemas.ACTION_MODELS`.

Results contain schema_version=1, status, book_id, revision, data, warnings,
error, next_actions. Errors include code, message, retryable, exit_code and details.
MCP advertises a typed top-level response envelope; data remains action-specific.
Input conditions (chapter/review saves, fact object/value, replay modes) are
also expressed in JSON Schema. INVALID_INPUT details contain safe field issues,
without submitted manuscript values; budget errors report the required minimum.
MCP tools take a typed `request` object. CLI common options are --project,
--book-id, --operation-id, --run-id, --input FILE|- and --json. CLI flags
override JSON only when explicitly supplied; unknown fields are errors.

CLI commands map to ACTION_MODELS: book init/status/import; source get/save/accept;
context build; memory stage/sync; search; graph query; index status/update/rebuild;
doctor check/repair; revision batch; entity resolve. Additional local commands:
hook run EVENT; mcp serve.

Core writes require explicit project, book_id, operation_id (book_init creates
its identity). Source chapter saves require chapter and fresh context_id;
chapter acceptance requires the exact source's batch_id and review_id.
Review is saved with kind=review and the structured Review object. Memory
stage accepts MemoryDelta. memory_sync next/apply shares the sync-job contract:
only an active job's next accepted source can be replayed. Source get reads
immutable DB versions, not mutable Markdown projections.

Source get supports explicit if_none_match: omit content only for a matching
source hash when the caller already holds that exact page. Sync next/apply can
include a bounded next-source page, preserving offsets and hashes. This is not
an implicit persistent cache. Entity resolve returns historically valid name/alias
candidates and ambiguity; POV matching exposes only visible IDs, never aliases.

Revision batch prepare freezes a baseline revision/fingerprint, exact replacement
hashes/reviews, and the complete affected suffix. Apply validates each freshly
extracted delta against the staged candidate prefix inside a rolled-back savepoint.
Next resumes persisted progress; context returns bounded candidate author facts.
Commit revalidates bindings and atomically replaces all accepted pointers, ledger
and graph, incrementing revision once. Abort leaves canon unchanged. Existing
jobs/batches tables are reused; older runtimes cannot resume this new job kind.
Single-chapter APIs remain available. See the [batch workflow](../skills/novel/references/batch-revision.md)
and [measured optimization results](optimization-verification.md).

Since 0.1.7, candidate graphs are restored into a separate in-memory
SQLite connection from a disposable revision_snapshots table, created only on
candidate apply/context. Cache bindings cover the book/job, baseline, cursor,
manifest and prefix source/delta bytes. Blob checksum/format failures rebuild
from authoritative inputs. Snapshot, batch and cursor persistence share one
transaction; commit/abort removes the snapshot. Final commit never trusts it
instead of replaying evidence. No snapshot is exposed to canon/POV queries.

Public schemas omit only annotation titles; property names, literal data and
all constraints remain. MCP text defaults to the full JSON envelope. The explicit
NOVEL_WEAVER_MCP_TEXT_MODE=summary mode omits data from the text copy only:
structuredContent is complete, including prose and evidence. Status, revision,
errors, warnings and next_actions remain in both channels. Clients relying on
text alone must keep full mode. CLI output and request schemas are unchanged.
SourcePageCache is an optional caller-owned bounded cache, not an automatic
server cache or implicit proof that an agent retains the manuscript. See
[snapshot and transport validation](snapshot-transport-verification.md).

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

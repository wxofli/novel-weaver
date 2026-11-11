"""The sole business entry point for CLI, MCP, hooks and tests."""
import json
from pathlib import Path
import re
import sqlite3
import time

from pydantic import ValidationError

from .errors import NovelError, require
from .memory import apply_delta, reset_graph, validate_delta
from .schemas import ACTION_MODELS, MemoryDelta
from .store import Book, digest, discover, dumps, initialize, uid


WRITE_ACTIONS = {"source_save", "source_accept", "memory_stage", "book_import", "index_update", "index_rebuild", "doctor_repair", "memory_sync"}


def envelope(book=None, data=None, warnings=None, status="ok", next_actions=None):
    return {"schema_version": 1, "status": status, "book_id": book.id if book else None,
            "revision": book.revision if book else None, "data": data or {}, "warnings": warnings or [],
            "error": None, "next_actions": next_actions or []}


def context_ticket(book, context_id, chapter):
    row = book.db.execute("SELECT * FROM contexts WHERE id=?", (context_id,)).fetchone()
    require(row is not None, "CONTEXT_REQUIRED", "Build a chapter context before saving prose")
    require(row["chapter"] == chapter and row["task"] in ("write", "revise"), "CONTEXT_MISMATCH", "Context was built for another chapter/task", 4)
    require(row["revision"] == book.revision and row["fingerprint"] == book.fingerprint(),
            "STALE_CONTEXT", "Story changed; build fresh context", 4)
    return dict(row)


def replay_prefix(book, chapter, exclude_source=None):
    reset_graph(book)
    for row in book.db.execute("SELECT l.*,s.chapter FROM ledger l JOIN sources s ON s.id=l.source_id WHERE l.valid=1 ORDER BY l.seq").fetchall():
        if row["source_id"] != exclude_source and (row["chapter"] is None or row["chapter"] < chapter):
            source = book.source(row["source_id"])
            apply_delta(book, source, MemoryDelta.model_validate_json(row["delta"]))


def validate_at_source(book, source, delta):
    previous = book.db.execute("SELECT source_id FROM accepted WHERE logical_id=?", (source["logical_id"],)).fetchone()
    revision = previous and source["kind"] in ("chapter", "setting", "decision")
    if revision:
        book.db.execute("SAVEPOINT validate_past")
        try:
            replay_prefix(book, source["chapter"] or 1, exclude_source=previous[0] if source["kind"] != "chapter" else None)
            validate_delta(book, source, delta, source["chapter"] or 0)
        finally:
            book.db.execute("ROLLBACK TO validate_past")
            book.db.execute("RELEASE validate_past")
    else:
        validate_delta(book, source, delta, source["chapter"] or 0)


def add_ledger(book, source, delta):
    apply_delta(book, source, delta)
    book.db.execute("INSERT INTO ledger(source_id,chapter,delta) VALUES (?,?,?)", (source["id"], source["chapter"], delta.model_dump_json()))


def source_save(book, r):
    if r.kind == "chapter":
        require(r.logical_id == f"chapter:{r.chapter}", "CHAPTER_ID", "Chapter logical_id must be chapter:<number>", 2)
        context_ticket(book, r.context_id, r.chapter)
    old = book.db.execute("SELECT * FROM sources WHERE logical_id=? ORDER BY created_at DESC LIMIT 1", (r.logical_id,)).fetchone()
    require(not old or (old["kind"] == r.kind and old["chapter"] == r.chapter),
            "SOURCE_KIND_CONFLICT", "A logical id cannot change kind or chapter", 4)
    if r.expected_source_hash is not None:
        require(old is not None and old["hash"] == r.expected_source_hash,
                "SOURCE_CONFLICT", "Source changed since it was read", 4)
    if r.kind == "review":
        target = book.source(r.review.source_version)
        require(target["hash"] == r.review.source_hash and target["kind"] == "chapter", "STALE_REVIEW", "Review must reference exact chapter source", 4)
        for finding in r.review.findings:
            require(not finding.quote or finding.quote in target["content"], "INVALID_EVIDENCE", "Review quotes must exist in source", 2)
    source = book.save_source(r.kind, r.logical_id, r.content, r.chapter, r.context_id,
                              r.review.model_dump() if r.review else None, r.run_id)
    # Drafts have their own paths, and never replace accepted prose before author adoption.
    if r.kind == "chapter":
        path = str(Path("草稿") / (source["id"] + ".md"))
        book.db.execute("INSERT INTO projections VALUES (?,?,?,?)", (path, source["id"], None, "pending"))
    return {"source_version": source["id"], "source_hash": source["hash"], "review_id": source["id"] if r.kind == "review" else None}


def memory_stage(book, r):
    require(r.base_revision == book.revision, "REVISION_CONFLICT", "Memory changed; rebase delta", 4)
    source = book.source(r.source_version)
    require(source["kind"] != "review", "SOURCE_KIND", "Review is not a story source", 2)
    if source["kind"] not in ("chapter", "setting", "decision"):
        require(not (r.delta.entities or r.delta.facts or r.delta.close_facts or r.delta.knowledge or r.delta.hooks),
                "SCOPE_VIOLATION", "Plans and research cannot establish canon facts", 2)
    validate_at_source(book, source, r.delta)
    batch_id = uid("batch")
    book.db.execute("INSERT INTO batches VALUES (?,?,?,?,0)", (batch_id, source["id"], r.base_revision, r.delta.model_dump_json()))
    return {"batch_id": batch_id, "source_version": source["id"], "source_hash": source["hash"]}


def source_accept(book, r):
    from .retrieval import index_source
    require(not book.active_job(), "SYNC_IN_PROGRESS", "Finish the active memory synchronization before accepting more content", 4)
    require(r.expected_revision == book.revision, "REVISION_CONFLICT", "Memory revision changed", 4)
    source = book.source(r.source_version)
    require(source["kind"] != "review", "SOURCE_KIND", "Reviews are workflow records, not canon sources", 2)
    latest = book.db.execute("SELECT id FROM sources WHERE logical_id=? ORDER BY created_at DESC LIMIT 1", (source["logical_id"],)).fetchone()
    require(latest[0] == source["id"], "SUPERSEDED_DRAFT", "A newer candidate exists; review that version", 4)
    previous = book.db.execute("SELECT source_id FROM accepted WHERE logical_id=?", (source["logical_id"],)).fetchone()
    require(not previous or previous[0] != source["id"], "ALREADY_ACCEPTED", "This version is already accepted; reuse its original operation_id", 4)
    batch = book.db.execute("SELECT * FROM batches WHERE id=? AND source_id=?", (r.batch_id, source["id"])).fetchone() if r.batch_id else None
    if source["kind"] == "chapter":
        context_ticket(book, source["context_id"], source["chapter"])
        require(batch is not None, "MEMORY_REQUIRED", "Stage exact-version memory before acceptance")
        require(r.review_id is not None, "REVIEW_REQUIRED", "Review exact-version prose before acceptance")
        review = book.source(r.review_id)
        details = json.loads(review["review_json"] or "{}")
        require(review["kind"] == "review" and details.get("source_version") == source["id"] and details.get("source_hash") == source["hash"],
                "STALE_REVIEW", "Review belongs to a different prose version", 4)
        require(previous is not None or source["chapter"] == book.latest_chapter() + 1,
                "CHAPTER_GAP", "Accept chapters sequentially")
    if batch:
        require(batch["base_revision"] == book.revision, "STALE_DELTA", "Delta was staged against old memory", 4)
        delta = MemoryDelta.model_validate_json(batch["delta"])
        validate_at_source(book, source, delta)
    else:
        require(source["kind"] not in ("setting", "decision"), "MEMORY_REQUIRED", "Stage a delta (empty if appropriate) for canonical settings/decisions")
        delta = MemoryDelta(source_hash=source["hash"])
    book.db.execute("INSERT OR REPLACE INTO accepted VALUES (?,?)", (source["logical_id"], source["id"]))
    job_id = None
    if source["kind"] == "chapter" and previous:
        chapter = source["chapter"]
        replay_prefix(book, chapter)
        book.db.execute("UPDATE ledger SET valid=0 WHERE chapter>=?", (chapter,))
        manifest = [r[0] for r in book.db.execute("SELECT s.id FROM accepted a JOIN sources s ON s.id=a.source_id WHERE s.chapter>=? ORDER BY s.chapter", (chapter,))]
        add_ledger(book, source, delta)
        book.set_meta("frontier", chapter)
        job_id = uid("sync")
        book.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job_id, "revision", dumps(manifest), 1, "active" if len(manifest) > 1 else "complete", time.time_ns()))
    elif source["kind"] in ("setting", "decision") and previous:
        # Replacing a global rule retracts its former assertions. Chapters that
        # depended on that rule are reconstructed from their immutable prose.
        book.db.execute("UPDATE ledger SET valid=0 WHERE source_id=? OR chapter IS NOT NULL", (previous[0],))
        replay_prefix(book, 1)
        add_ledger(book, source, delta)
        manifest = [row[0] for row in book.db.execute("SELECT s.id FROM accepted a JOIN sources s ON s.id=a.source_id WHERE s.kind='chapter' ORDER BY s.chapter")]
        book.set_meta("frontier", 0)
        if manifest:
            job_id = uid("sync")
            book.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (job_id, "setting_revision", dumps(manifest), 0, "active", time.time_ns()))
    else:
        add_ledger(book, source, delta)
        if source["kind"] == "chapter":
            book.set_meta("frontier", source["chapter"])
    if batch:
        book.db.execute("UPDATE batches SET applied=1 WHERE id=?", (batch["id"],))
    index_source(book, source)
    book.queue_projection(source)
    book.bump()
    return {"source_version": source["id"], "accepted": True, "job_id": job_id, "memory_frontier": book.frontier()}


def memory_sync(book, r):
    job = book.active_job()
    require(job is not None and job["id"] == r.job_id, "SYNC_JOB_NOT_ACTIVE", "No matching active synchronization job", 4)
    manifest = json.loads(job["manifest"])
    source = book.source(manifest[job["position"]])
    for sid in manifest:
        pinned = book.source(sid)
        row = book.db.execute("SELECT source_id FROM accepted WHERE logical_id=?", (pinned["logical_id"],)).fetchone()
        require(row is not None and row[0] == sid, "SYNC_MANIFEST_CHANGED", "Accepted source changed during synchronization", 4)
    if r.mode == "next":
        return {"job_id": job["id"], "next_source_version": source["id"], "source_hash": source["hash"], "chapter": source["chapter"], "position": job["position"], "total": len(manifest)}
    require(r.source_version == source["id"] and r.delta is not None, "SYNC_ORDER", "Read and extract the job's next immutable source", 4)
    require(r.base_revision == book.revision, "REVISION_CONFLICT", "Memory changed; retry at current revision", 4)
    add_ledger(book, source, r.delta)
    position = job["position"] + 1
    book.db.execute("UPDATE jobs SET position=?,status=? WHERE id=?", (position, "complete" if position == len(manifest) else "active", job["id"]))
    book.set_meta("frontier", source["chapter"])
    book.bump()
    return {"job_id": job["id"], "position": position, "total": len(manifest), "memory_frontier": book.frontier()}


def split_manuscript(text, split_rule=None):
    pattern = split_rule or r"(?m)^(?:第[0-9零〇一二三四五六七八九十百千万两]+[章节回卷][^\n]*|#{1,6}\s+[^\n]+)\s*$"
    try:
        headers = list(re.finditer(pattern, text))
    except re.error as exc:
        raise NovelError("SPLIT_RULE", "Invalid chapter split regex", 2) from exc
    if not headers:
        return [{"title": "导入章节", "content": text, "chapter": 1}]
    result = []
    if text[:headers[0].start()].strip():
        result.append({"title": "序言", "content": text[:headers[0].start()], "chapter": 1})
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        result.append({"title": header.group().strip(), "content": text[header.start():end], "chapter": len(result) + 1})
    return result


def book_import(book, r):
    from .retrieval import index_source
    if r.mode == "preview":
        require(r.files, "FILES_REQUIRED", "Preview requires files", 2)
        files, mapping = [], []
        for name in r.files:
            path = Path(name).resolve()
            require(path.suffix.lower() in (".txt", ".md", ".markdown"), "IMPORT_FORMAT", "Only TXT/Markdown are supported", 2)
            raw = path.read_bytes()
            encodings = [r.encoding] if r.encoding else ["utf-8-sig", "gb18030"]
            text = None
            for encoding in encodings:
                try:
                    text = raw.decode(encoding)
                    break
                except (UnicodeError, LookupError):
                    continue
            require(text is not None, "IMPORT_ENCODING", "Could not decode manuscript; specify encoding", 2)
            files.append({"path": str(path), "hash": __import__("hashlib").sha256(raw).hexdigest()})
            for item in split_manuscript(text, r.split_rule):
                item["chapter"] = len(mapping) + 1
                mapping.append(item)
        mid = uid("mapping")
        book.db.execute("INSERT INTO import_previews VALUES (?,?,?)", (mid, dumps(files), dumps(mapping)))
        return {"mapping_id": mid, "mapping": mapping, "files": files}
    require(not book.active_job(), "SYNC_IN_PROGRESS", "Finish active synchronization first", 4)
    require(book.latest_chapter() == 0, "IMPORT_INTO_NONEMPTY_BOOK", "Import into a fresh book to avoid overwriting chapters", 4)
    preview = book.db.execute("SELECT * FROM import_previews WHERE id=?", (r.mapping_id,)).fetchone()
    require(preview is not None, "MAPPING_REQUIRED", "Preview and confirm a chapter mapping first")
    for entry in json.loads(preview["files"]):
        current = __import__("hashlib").sha256(Path(entry["path"]).read_bytes()).hexdigest()
        require(current == entry["hash"], "IMPORT_SOURCE_CHANGED", "Original manuscript changed; preview again", 4)
    mapping = [m.model_dump() for m in r.mapping] if r.mapping is not None else json.loads(preview["mapping"])
    require(mapping and [m["chapter"] for m in mapping] == list(range(1, len(mapping) + 1)), "IMPORT_MAPPING", "Mapping must be a nonempty sequential chapter list", 2)
    manifest = []
    for item in mapping:
        source = book.save_source("chapter", f"chapter:{item['chapter']}", item["content"], item["chapter"], run_id=r.run_id)
        book.db.execute("INSERT INTO accepted VALUES (?,?)", (source["logical_id"], source["id"]))
        book.queue_projection(source)
        index_source(book, source)
        manifest.append(source["id"])
    jid = uid("sync")
    book.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)", (jid, "import", dumps(manifest), 0, "active", time.time_ns()))
    book.bump()
    return {"job_id": jid, "chapters": len(mapping), "memory_frontier": 0}


def status(book, *, brief=False):
    pending = []
    latest = book.db.execute("""SELECT s.id,s.hash,s.context_id,s.run_id FROM sources s
        JOIN (SELECT logical_id,MAX(created_at) AS t FROM sources WHERE kind='chapter' GROUP BY logical_id) l
        ON s.logical_id=l.logical_id AND s.created_at=l.t
        WHERE NOT EXISTS (SELECT 1 FROM accepted a WHERE a.source_id=s.id)""").fetchall()
    reviewed_versions = set()
    if latest:
        for row in book.db.execute("SELECT review_json FROM sources WHERE kind='review'"):
            review = json.loads(row[0] or "{}")
            reviewed_versions.add((review.get("source_version"), review.get("source_hash")))
    revision = book.revision
    fingerprint = book.fingerprint() if latest else None
    for source in latest:
        batch = book.db.execute("SELECT id FROM batches WHERE source_id=? AND base_revision=?", (source["id"], revision)).fetchone()
        reviewed = (source["id"], source["hash"]) in reviewed_versions
        ctx = book.db.execute("SELECT revision,fingerprint FROM contexts WHERE id=?", (source["context_id"],)).fetchone()
        fresh = bool(ctx and ctx["revision"] == revision and ctx["fingerprint"] == fingerprint)
        needs = ([] if fresh else ["context.build"]) + ([] if batch else ["memory.stage"]) + ([] if reviewed else ["review"])
        pending.append({"source_version": source["id"], "run_id": source["run_id"], "needs": needs, "awaiting_author": not needs})
    job = book.active_job()
    if job:
        manifest = json.loads(job["manifest"])
        job = {"job_id": job["id"], "kind": job["kind"], "position": job["position"], "total": len(manifest), "next_source_version": manifest[job["position"]]}
    data = {"project": str(book.root), "title": book.meta("title"), "latest_chapter": book.latest_chapter(),
            "memory_frontier": book.frontier(), "active_job": job, "pending_work": pending,
            "awaiting_author": bool(pending) and all(not p["needs"] for p in pending)}
    if not brief:
        data.update(changed_projections=book.projection_changes(), index_pending=index_status(book)["pending_vectors"])
    return data


def index_status(book):
    from .retrieval import embedding_config
    total = book.db.execute("SELECT COUNT(*) FROM chunks c JOIN accepted a ON a.source_id=c.source_id").fetchone()[0]
    embedded = book.db.execute("SELECT COUNT(*) FROM embeddings e JOIN chunks c ON c.id=e.chunk_id JOIN accepted a ON a.source_id=c.source_id").fetchone()[0]
    config = embedding_config()
    if config and book.meta("embedding_config") != digest(dumps(config)):
        embedded = 0
    return {"chunks": total, "embedded": embedded, "pending_vectors": total - embedded if embedding_config() else 0,
            "embedding_configured": bool(embedding_config()), "embedding_profile": book.meta("embedding_profile")}


def next_actions(data):
    actions = []
    if data.get("active_job"):
        actions.append({"action": "memory.sync", **data["active_job"]})
    for pending in data.get("pending_work", []):
        for need in pending["needs"]:
            actions.append({"action": need, "source_version": pending["source_version"], "run_id": pending["run_id"]})
    if data.get("index_pending"):
        actions.append({"action": "index.update"})
    return actions


def handle(book, action, r):
    from . import retrieval
    warnings = []
    if action == "source_save":
        return source_save(book, r), warnings
    if action == "memory_stage":
        return memory_stage(book, r), warnings
    if action == "source_accept":
        return source_accept(book, r), warnings
    if action == "memory_sync":
        return memory_sync(book, r), warnings
    if action == "book_import":
        return book_import(book, r), warnings
    if action == "source_get":
        source = book.source(r.source_version)
        end = min(len(source["content"]), r.offset + r.max_chars)
        return {"source_version": source["id"], "source_hash": source["hash"], "kind": source["kind"],
                "chapter": source["chapter"], "content": source["content"][r.offset:end], "total_chars": len(source["content"]),
                "next_offset": end if end < len(source["content"]) else None, "offset": r.offset}, warnings
    if action == "search":
        return retrieval.search(book, r)
    if action == "graph_query":
        return retrieval.graph(book, r), warnings
    if action == "index_status":
        return index_status(book), warnings
    if action in ("index_update", "index_rebuild"):
        if r.mode == "rebuild" or action == "index_rebuild":
            retrieval.refresh_index(book)
            book.db.execute("DELETE FROM meta WHERE key IN ('embedding_profile','embedding_config')")
        if r.embedding:
            retrieval.update_vectors(book)
        return index_status(book), warnings
    if action in ("doctor_check", "doctor_repair"):
        integrity = book.db.execute("PRAGMA quick_check").fetchone()[0]
        data = status(book)
        data["integrity"] = integrity
        data["pending_projections"] = book.db.execute("SELECT COUNT(*) FROM projections WHERE state!='done'").fetchone()[0]
        if action == "doctor_repair":
            retrieval.refresh_index(book)
            for projection in book.db.execute("SELECT path FROM projections WHERE state='done'").fetchall():
                if not (book.root / projection["path"]).exists():
                    book.db.execute("UPDATE projections SET state='pending',expected_hash=NULL WHERE path=?", (projection["path"],))
            data["index_rebuilt"] = True
        return data, warnings
    raise NovelError("UNKNOWN_ACTION", "Unsupported action", 2)


def execute(action: str, payload: dict) -> dict:
    book = None
    try:
        require(action in ACTION_MODELS, "UNKNOWN_ACTION", "Unsupported action", 2)
        request = ACTION_MODELS[action].model_validate(payload)
        if action == "book_init":
            data = initialize(request.project, request.title, request.operation_id)
            result = envelope(data=data)
            result.update(book_id=data["book_id"], revision=0)
            return result
        root = Path(request.project).resolve() if request.project else discover()
        write = action in WRITE_ACTIONS and not (action == "memory_sync" and request.mode == "next")
        context_ticket_required = action == "context_build" and request.task in {"write", "revise"}
        book = Book(root, request.book_id, readonly=not write and not context_ticket_required)
        if action == "context_build":
            from .retrieval import build_context
            with book.transaction(readonly=not context_ticket_required):
                data, warnings = build_context(book, request)
                return envelope(book, data, warnings)
        if action == "book_status":
            with book.transaction(readonly=True):
                data = status(book, brief=request.brief)
                state = "awaiting_author" if data["awaiting_author"] and not data["active_job"] else "ok"
                return envelope(book, data, status=state, next_actions=next_actions(data))
        if not write:
            data, warnings = handle(book, action, request)
            actions = next_actions(data) if action == "doctor_check" else []
            state = "awaiting_author" if data.get("awaiting_author") and not data.get("active_job") else "ok"
            return envelope(book, data, warnings, state, actions)
        fingerprint = digest(dumps({"action": action, "request": request.model_dump()}))
        with book.transaction():
            previous = book.db.execute("SELECT * FROM operations WHERE id=?", (request.operation_id,)).fetchone()
            if previous:
                require(previous["fingerprint"] == fingerprint, "OPERATION_CONFLICT", "operation_id was already used for another request", 4)
                result = json.loads(previous["response"])
            else:
                data, warnings = handle(book, action, request)
                result = envelope(book, data, warnings)
                if action == "source_save" and request.kind == "chapter":
                    result["next_actions"] = [{"action": a, "source_version": data["source_version"], "run_id": request.run_id} for a in ("memory.stage", "review")]
                elif action in ("source_accept", "memory_sync", "book_import", "doctor_repair"):
                    state = status(book)
                    result["next_actions"] = next_actions(state)
                book.db.execute("INSERT INTO operations VALUES (?,?,?)", (request.operation_id, fingerprint, dumps(result)))
        warnings = book.flush_projections() if action in ("source_save", "source_accept", "book_import", "doctor_repair") else []
        if warnings:
            result["warnings"].extend(warnings)
            result["status"] = "partial"
        return result
    except ValidationError as exc:
        error = NovelError("INVALID_INPUT", str(exc), 2)
    except NovelError as exc:
        error = exc
    except sqlite3.OperationalError as exc:
        error = NovelError("BOOK_BUSY" if "locked" in str(exc).lower() else "DATABASE_ERROR", str(exc), 4 if "locked" in str(exc).lower() else 1, "locked" in str(exc).lower())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError) as exc:
        error = NovelError("INTERNAL_ERROR", type(exc).__name__ + ": " + str(exc), 1)
    finally:
        if book:
            book.close()
    result = envelope()
    result.update(status="error", error={"code": error.code, "message": error.message, "retryable": error.retryable, "exit_code": error.exit_code})
    return result

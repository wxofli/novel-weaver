"""Book-scoped, provenance-preserving retrieval. No model generation here."""
import json
import logging
import math
import os
import re
import unicodedata
from collections import defaultdict, deque
from functools import lru_cache

from .errors import NovelError, require
from .memory import fact_rows, historical_graph, historical_entity, resolve_entity
from .store import digest, dumps, uid


@lru_cache(maxsize=8)
def _tokenizer(book_key, names):
    import jieba
    jieba.setLogLevel(logging.ERROR)
    tokenizer = jieba.Tokenizer()
    for name in names:
        tokenizer.add_word(name, freq=100000)
    return tokenizer


def tokenize(book, text):
    names = []
    for row in book.db.execute("SELECT name,aliases FROM entities"):
        names.extend([row["name"], *json.loads(row["aliases"])])
    tokenizer = _tokenizer((str(book.root), book.id), tuple(sorted(set(names))))
    normalized = unicodedata.normalize("NFKC", text).lower()
    return [t for t in tokenizer.cut_for_search(normalized) if any(c.isalnum() for c in t)]


def chunks(text, target=600, maximum=1000):
    """Preserve exact offsets; never reconstruct normalized text as evidence."""
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + target, end)
            if boundary < 0:
                boundaries = [text.rfind(c, start + target, end) for c in "。！？.!?"]
                boundary = max(boundaries)
            if boundary >= start + target:
                end = boundary + 1
        yield start, text[start:end]
        start = end


def source_scope(kind):
    if kind == "chapter":
        return "canon"
    if kind == "research":
        return "reference"
    return "plan"


def index_source(book, source):
    for row in book.db.execute("SELECT id FROM chunks WHERE source_id=?", (source["id"],)).fetchall():
        book.db.execute("DELETE FROM search_index WHERE chunk_id=?", (row["id"],))
        book.db.execute("DELETE FROM embeddings WHERE chunk_id=?", (row["id"],))
    book.db.execute("DELETE FROM chunks WHERE source_id=?", (source["id"],))
    if source["kind"] == "review":
        return
    for offset, text in chunks(source["content"]):
        cid = digest(source["id"] + ":" + str(offset))
        book.db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", (
            cid, source["id"], source["chapter"] or 0, source_scope(source["kind"]), offset, text, digest(text)))
        book.db.execute("INSERT INTO search_index VALUES (?,?)", (cid, " ".join(tokenize(book, text))))


def refresh_index(book):
    # Accepted pointers filter stale chunks, so removed versions are never queryable.
    book.db.execute("DELETE FROM search_index")
    book.db.execute("DELETE FROM chunks")
    book.db.execute("DELETE FROM embeddings")
    for row in book.db.execute("SELECT s.* FROM accepted a JOIN sources s ON s.id=a.source_id").fetchall():
        index_source(book, dict(row))


def coverage(book, chapter=None):
    limit = book.frontier() if book.active_job() else book.latest_chapter()
    require(chapter is None or chapter <= limit, "MEMORY_NOT_READY", f"Reliable memory currently covers chapters 0..{limit}")
    return chapter if chapter is not None else limit


def embedding_config():
    base = os.environ.get("NOVEL_EMBED_BASE_URL")
    model = os.environ.get("NOVEL_EMBED_MODEL")
    if not base or not model:
        return None
    return {"base_url": base.rstrip("/"), "model": model}


def embed(texts):
    import httpx
    config = embedding_config()
    require(config, "EMBEDDING_NOT_CONFIGURED", "Set NOVEL_EMBED_BASE_URL and NOVEL_EMBED_MODEL", 5)
    headers = {}
    if os.environ.get("NOVEL_EMBED_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["NOVEL_EMBED_API_KEY"]
    try:
        response = httpx.post(config["base_url"] + "/embeddings", json={"model": config["model"], "input": texts}, headers=headers, timeout=30)
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda x: x["index"])
        require(len(rows) == len(texts), "EMBEDDING_RESPONSE", "Provider returned wrong number of vectors", 5)
        vectors = [r["embedding"] for r in rows]
        require(bool(vectors) and bool(vectors[0]) and all(
            len(v) == len(vectors[0]) and all(isinstance(x, (float, int)) and math.isfinite(x) for x in v) for v in vectors),
            "EMBEDDING_RESPONSE", "Provider returned invalid vectors", 5)
        return vectors
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # Never echo response bodies/headers, which may contain credentials.
        raise NovelError("EMBEDDING_UNAVAILABLE", "Embedding provider failed: " + type(exc).__name__, 5, True) from exc


def vector_profile(dim):
    return digest(dumps(dict(embedding_config() or {}, dimension=dim, chunker="paragraph-v1")))


def update_vectors(book):
    config = embedding_config()
    require(config, "EMBEDDING_NOT_CONFIGURED", "Configure an embedding service before updating vectors", 5)
    config_hash = digest(dumps(config))
    previous = book.meta("embedding_config")
    if previous != config_hash:
        book.db.execute("DELETE FROM embeddings")
    rows = book.db.execute("SELECT c.* FROM chunks c JOIN accepted a ON a.source_id=c.source_id LEFT JOIN embeddings e ON e.chunk_id=c.id WHERE e.chunk_id IS NULL").fetchall()
    count = 0
    for start in range(0, len(rows), 32):
        batch = rows[start:start + 32]
        vectors = embed([r["content"] for r in batch])
        profile = vector_profile(len(vectors[0]))
        if book.meta("embedding_profile") not in (None, profile):
            book.db.execute("DELETE FROM embeddings")
            raise NovelError("EMBEDDING_PROFILE_CHANGED", "Embedding dimension changed; run index rebuild --embedding", 5)
        for row, vector in zip(batch, vectors):
            book.db.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?,?)", (row["id"], profile, dumps(vector)))
        book.set_meta("embedding_profile", profile)
        book.set_meta("embedding_config", config_hash)
        count += len(batch)
    return count


def vector_hits(book, query, chapter, scope):
    if not embedding_config() or not book.meta("embedding_profile"):
        return [], []
    config_hash = digest(dumps(embedding_config()))
    if config_hash != book.meta("embedding_config"):
        return [], [{"code": "VECTOR_PROFILE_STALE", "message": "Embedding configuration changed; reindex required"}]
    try:
        import sqlite_vec
        book.db.enable_load_extension(True)
        try:
            sqlite_vec.load(book.db)
        finally:
            book.db.enable_load_extension(False)
        vector = embed([query])[0]
        require(vector_profile(len(vector)) == book.meta("embedding_profile"), "VECTOR_PROFILE_STALE", "Query vector profile differs", 5)
        rows = book.db.execute("""SELECT c.*,vec_distance_cosine(e.vector,?) AS distance
            FROM chunks c JOIN embeddings e ON e.chunk_id=c.id JOIN accepted a ON a.source_id=c.source_id
            WHERE c.scope=? AND c.chapter<=? AND e.profile=? ORDER BY distance,c.id LIMIT 50""",
            (dumps(vector), scope, chapter, book.meta("embedding_profile"))).fetchall()
        return [dict(r) for r in rows], []
    except Exception as exc:
        return [], [{"code": "VECTOR_DEGRADED", "message": "Semantic retrieval unavailable; using graph and BM25", "reason": type(exc).__name__}]


def search(book, request):
    chapter = coverage(book, request.chapter) if request.scope == "canon" else 2147483647
    terms = list(dict.fromkeys(tokenize(book, request.query)))[:40]
    rows = []
    if terms:
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = [dict(r) for r in book.db.execute("""SELECT c.*,bm25(search_index) AS rank FROM search_index
            JOIN chunks c ON c.id=search_index.chunk_id JOIN accepted a ON a.source_id=c.source_id
            WHERE search_index MATCH ? AND c.scope=? AND c.chapter<=? ORDER BY rank,c.id LIMIT 50""", (expression, request.scope, chapter))]
    vector_rows, warnings = vector_hits(book, request.query, chapter, request.scope)
    scores, hits = defaultdict(float), {}
    for channel, candidates in (("bm25", rows), ("vector", vector_rows)):
        for rank, row in enumerate(candidates, 1):
            cid = row["id"]
            scores[cid] += 1 / (60 + rank)
            if cid not in hits:
                hits[cid] = dict(row, channels=[])
            hits[cid]["channels"].append(channel)
    result = []
    for cid in sorted(scores, key=lambda i: (-scores[i], i))[:request.limit]:
        row = hits[cid]
        source = book.source(row["source_id"])
        result.append({"chunk_id": cid, "source_version": row["source_id"], "source_hash": source["hash"],
                       "chapter": row["chapter"], "scope": row["scope"], "offset": row["offset"],
                       "quote": row["content"], "path": book.projection_path(source),
                       "channels": row["channels"], "score": scores[cid]})
    rerank_url = os.environ.get("NOVEL_RERANK_URL")
    if rerank_url and result:
        import httpx
        headers = {"Authorization": "Bearer " + os.environ["NOVEL_RERANK_API_KEY"]} if os.environ.get("NOVEL_RERANK_API_KEY") else {}
        try:
            response = httpx.post(rerank_url, headers=headers, json={"model": os.environ.get("NOVEL_RERANK_MODEL", ""), "query": request.query, "documents": [h["quote"] for h in result]}, timeout=15)
            response.raise_for_status()
            ranked = response.json()["results"]
            order = [int(r["index"]) for r in sorted(ranked, key=lambda r: -r["relevance_score"])]
            require(sorted(order) == list(range(len(result))), "RERANK_RESPONSE", "Invalid reranker permutation", 5)
            result = [result[i] for i in order]
        except Exception:
            warnings.append({"code": "RERANK_DEGRADED", "message": "Using deterministic RRF ordering"})
    return {"hits": result, "coverage_chapter": chapter if request.scope == "canon" else None}, warnings


def graph(book, request):
    chapter = coverage(book, request.chapter)
    entity = resolve_entity(book, request.entity, chapter=chapter, require_id=bool(request.pov)) if request.entity else None
    rows = fact_rows(book, chapter, request.pov, seeds={entity}) if request.mode == "entity" else []
    if request.mode == "entity":
        require(entity is not None, "ENTITY_REQUIRED", "Entity query needs an entity")
        node = historical_entity(book, entity, chapter, request.pov)
        return {"entity": node, "facts": [r for r in rows if r["subject"] == entity or r["object"] == entity][:100], "chapter": chapter}
    if request.mode == "timeline":
        rows = [dict(r) for r in book.db.execute("SELECT * FROM facts WHERE introduced<=? ORDER BY introduced,id", (chapter,))]
        if request.pov:
            person = "reader" if request.pov == "reader" else resolve_entity(book, request.pov, chapter=chapter, require_id=True)
            known = {r["fact"]: dict(r) for r in book.db.execute("SELECT * FROM knowledge WHERE character=? AND chapter<=? ORDER BY chapter", (person, chapter))}
            rows = [dict(r, knowledge_state=known[r["id"]]["state"], knowledge_evidence=known[r["id"]])
                    for r in rows if r["id"] in known and known[r["id"]]["state"] != "rejects"]
        rows = [r for r in rows if not entity or entity in (r["subject"], r["object"])][:100]
        for fact in rows:
            if request.pov or (fact["valid_to"] is not None and fact["valid_to"] > chapter):
                fact["valid_to"] = None
            if fact["valid_to"] is not None:
                closure = book.db.execute("""SELECT l.source_id,l.chapter,json_extract(j.value,'$.evidence') AS evidence
                    FROM ledger l,json_each(l.delta,'$.close_facts') j
                    WHERE l.valid=1 AND json_extract(j.value,'$.id')=? AND l.chapter<=? ORDER BY l.seq DESC LIMIT 1""", (fact["id"], chapter)).fetchone()
                if closure:
                    fact["closing_evidence"] = dict(source_version=closure["source_id"], chapter=closure["chapter"], **json.loads(closure["evidence"]))
        return {"facts": rows, "chapter": chapter}
    require(entity is not None, "ENTITY_REQUIRED", "Graph traversal requires an entity")
    target = resolve_entity(book, request.target, chapter=chapter, require_id=bool(request.pov)) if request.target else None
    if request.mode == "path":
        require(target is not None, "TARGET_REQUIRED", "Path queries require a target entity", 2)
    queue, visited, found = deque([(entity, [], 0)]), {entity}, []
    while queue and len(found) < 100:
        node, path, depth = queue.popleft()
        if depth >= request.depth:
            continue
        for fact in fact_rows(book, chapter, request.pov, seeds={node}):
            if node not in (fact["subject"], fact["object"]):
                continue
            new_path = path + [fact]
            if request.mode == "path" and target in (fact["subject"], fact["object"]):
                return {"path": new_path, "chapter": chapter}
            if fact not in found:
                found.append(fact)
            if len(found) >= 100:
                break
            other = fact["object"] if node == fact["subject"] else fact["subject"]
            if other and other not in visited:
                visited.add(other)
                queue.append((other, new_path, depth + 1))
    return {"path": [], "truncated": len(found) >= 100} if request.mode == "path" else {"facts": found[:100], "chapter": chapter, "truncated": len(found) >= 100}


def context_seeds(book, request, cutoff, query):
    seeds = {resolve_entity(book, e, chapter=cutoff) for e in request.entity_ids}
    if request.pov and request.pov != "reader":
        seeds.add(resolve_entity(book, request.pov, chapter=cutoff, require_id=True))
    for row in book.db.execute("SELECT * FROM entities"):
        if query and any(n in query for n in [row["name"], *json.loads(row["aliases"])]):
            try:
                historical = historical_entity(book, row["id"], cutoff)
            except NovelError as exc:
                if exc.code == "ENTITY_NOT_YET_INTRODUCED":
                    continue
                raise
            if any(n in query for n in [historical["name"], *historical["aliases"]]):
                seeds.add(row["id"])
    return seeds


def _fit_items(payload, target, items, budget):
    complete = True
    for item in items:
        target.append(item)
        if len(dumps(payload)) > budget:
            target.pop()
            complete = False
    return complete


def _draft_reference(book, source_version, chapter):
    draft = book.source(source_version)
    require(draft["kind"] == "chapter" and draft["chapter"] == chapter, "DRAFT_MISMATCH", "Working overlay belongs to another chapter", 4)
    staged = book.db.execute("SELECT id,base_revision FROM batches WHERE source_id=? ORDER BY rowid DESC LIMIT 1", (draft["id"],)).fetchone()
    return {"source_version": draft["id"], "source_hash": draft["hash"], "total_chars": len(draft["content"]),
            "candidate_memory": {"batch_id": staged["id"], "base_revision": staged["base_revision"],
                                 "source_hash": draft["hash"]} if staged else None}


def _pov_fact(fact):
    evidence = fact["knowledge_evidence"]
    return {**{key: fact[key] for key in ("id", "subject", "predicate", "object", "value", "knowledge_state")},
            "source_version": evidence["source_id"], "offset": evidence["offset"]}


def _author_material(book, request, payload, seeds, query, open_hooks, warnings):
    from .schemas import Search

    cutoff = payload["as_of_chapter"]
    budget = request.budget_chars
    truncated = []

    def fill(section, items, limit):
        if not _fit_items(payload, payload[section], items[:limit], budget) or len(items) > limit:
            truncated.append(section)

    plan_hits, canon_hits = [], []
    if query:
        for scope, target in (("plan", plan_hits), ("canon", canon_hits)):
            result, messages = search(book, Search(query=query, chapter=cutoff, scope=scope))
            warnings.extend(messages)
            target.extend(result["hits"])
    kinds = {row["id"]: row["kind"] for row in book.db.execute("SELECT s.id,s.kind FROM accepted a JOIN sources s ON s.id=a.source_id WHERE s.kind!='chapter'")}
    constraints = [{"source_version": hit["source_version"], "kind": kinds[hit["source_version"]],
                    "offset": hit["offset"], "text": hit["quote"][:600]}
                   for hit in plan_hits if kinds.get(hit["source_version"]) in {"setting", "decision"}]
    if not constraints:
        constraints = [dict(row) for row in book.db.execute("""SELECT s.id AS source_version,s.kind,0 AS offset,substr(s.content,1,600) AS text
            FROM accepted a JOIN sources s ON s.id=a.source_id WHERE s.kind IN ('setting','decision')
            ORDER BY s.created_at DESC,s.id LIMIT 5""")]
    fill("author_constraints", constraints, 4)
    facts = fact_rows(book, cutoff, seeds=seeds)
    facts.sort(key=lambda fact: (-fact["introduced"], fact["id"]))
    fill("facts", facts, 12)
    visible_facts = {f["id"] for f in payload["facts"]}
    for person in dict.fromkeys(([request.pov] if request.pov else []) + ["reader"]):
        known = fact_rows(book, cutoff, person, seeds=seeds)
        details = {"known": [], "not_established_as_known": []}
        payload["knowledge"][person] = details
        if len(dumps(payload)) > budget:
            del payload["knowledge"][person]
            truncated.append("knowledge")
            continue
        unknown_ids = sorted(visible_facts - {f["id"] for f in known})
        fitted_known = _fit_items(payload, details["known"], [_pov_fact(f) for f in known[:8]], budget)
        fitted_unknown = _fit_items(payload, details["not_established_as_known"], unknown_ids, budget)
        if not fitted_known or not fitted_unknown or len(known) > 8:
            truncated.append("knowledge")
    previous = book.db.execute("""SELECT substr(s.content,-1000) FROM accepted a JOIN sources s ON s.id=a.source_id
        WHERE s.kind='chapter' AND s.chapter=?""", (min(payload["chapter"] - 1, cutoff),)).fetchone()
    if previous:
        payload["previous_tail"] = previous[0]
        if len(dumps(payload)) > budget:
            payload["previous_tail"] = ""
            truncated.append("previous_tail")
    fill("passages", [hit for hit in canon_hits if hit["source_version"] != request.draft_id], 4)
    fill("plan", [hit for hit in plan_hits if kinds.get(hit["source_version"]) not in {"setting", "decision", "style"}], 3)
    fill("style_examples", [hit for hit in plan_hits if kinds.get(hit["source_version"]) == "style"], 2)
    open_hooks.sort(key=lambda h: (h.get("target_chapter") or 2147483647, h["id"]))
    fill("hooks", open_hooks, 8)
    payload["additional_open_hooks"] = len(open_hooks) - len(payload["hooks"])
    recent = [dict(r) for r in book.db.execute("SELECT * FROM summaries WHERE chapter<=? ORDER BY chapter DESC LIMIT 3", (cutoff,))]
    fill("recent_summaries", recent, 3)
    return truncated


def build_context(book, request):
    writing = request.task in {"write", "revise"}
    limited = writing and request.pov is not None
    latest = book.latest_chapter()
    chapter = request.chapter or latest + 1
    cutoff = chapter - 1 if writing else min(chapter, latest)
    coverage(book, cutoff)
    brief = request.scene_brief.model_dump() if request.scene_brief else None
    query = request.query or (request.scene_brief.goal if request.scene_brief else "")
    open_hooks = [] if limited else [h for h in historical_graph(book, cutoff) if h["status"] != "resolved"]
    payload = {"task": request.task, "chapter": chapter, "as_of_chapter": cutoff, "query": request.query,
               "view": "pov" if limited else "author", "pov": request.pov, "scene_brief": brief,
               "context_id": uid("ctx") if writing else None, "revision": book.revision, "budget_chars": request.budget_chars,
               "author_constraints": [], "facts": [], "knowledge": {}, "hooks": [], "additional_open_hooks": len(open_hooks),
               "recent_summaries": [], "previous_tail": "", "plan": [], "style_examples": [], "passages": [], "draft": None,
               "instruction": "Follow the scene brief and reveal limit. Use only the selected viewpoint's knowledge." if limited else
                              "Keep author truth, reader knowledge, character beliefs and planned events separate."}
    if request.draft_id:
        payload["draft"] = _draft_reference(book, request.draft_id, chapter)
    if limited:
        payload["knowledge"][request.pov] = {"known": []}
    require(len(dumps(payload)) <= request.budget_chars, "BUDGET_EXCEEDED", "Scene brief and required metadata exceed the context budget; shorten the brief or increase the budget")
    seeds = context_seeds(book, request, cutoff, query)
    warnings = []
    if limited:
        known = [_pov_fact(f) for f in fact_rows(book, cutoff, request.pov, seeds=seeds)]
        complete = _fit_items(payload, payload["knowledge"][request.pov]["known"], known[:16], request.budget_chars)
        trimmed = ["knowledge"] if not complete or len(known) > 16 else []
    else:
        trimmed = _author_material(book, request, payload, seeds, query, open_hooks, warnings)
    if trimmed:
        warnings.append({"code": "CONTEXT_TRIMMED", "sections": sorted(set(trimmed)),
                         "message": "Some optional material was omitted. Retrieve only what the current task needs."})
    changed = book.projection_changes() if request.task in {"write", "revise", "review"} else []
    if changed:
        warnings.append({"code": "SOURCE_FILES_CHANGED", "paths": [c["path"] for c in changed[:6]], "message": "Inspect external edits; this context uses the accepted immutable versions."})
    if writing:
        book.db.execute("INSERT INTO contexts VALUES (?,?,?,?,?,?,?)", (
            payload["context_id"], payload["revision"], chapter, request.task, book.fingerprint(), request.run_id, dumps(payload)))
    return payload, warnings

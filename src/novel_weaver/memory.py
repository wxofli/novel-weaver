"""Typed evidence validation and deterministic temporal graph updates."""
import json
from .errors import require
from .store import dumps


def validate_delta(book, source, delta, chapter):
    require(delta.source_hash == source["hash"], "SOURCE_HASH_MISMATCH", "Delta is for a different text version", 4)
    ids = [e.id for e in delta.entities]
    require(len(set(ids)) == len(ids), "DUPLICATE_ENTITY", "Repeated entity id in delta", 2)
    known = {r[0] for r in book.db.execute("SELECT id FROM entities")} | set(ids)
    existing_facts = {r[0] for r in book.db.execute("SELECT id FROM facts")}
    new_facts = [f.id for f in delta.facts]
    require(len(set(new_facts)) == len(new_facts), "DUPLICATE_FACT", "Repeated fact id", 2)
    require(not existing_facts.intersection(new_facts), "FACT_EXISTS", "Use a new fact id and close the prior fact", 4)
    known_facts = existing_facts | set(new_facts)

    def evidence(ev):
        require(source["content"][ev.offset:ev.offset + len(ev.quote)] == ev.quote,
                "INVALID_EVIDENCE", "Evidence quote/offset does not match immutable source", 2)

    for entity in delta.entities:
        old = book.db.execute("SELECT name,kind FROM entities WHERE id=?", (entity.id,)).fetchone()
        require(not old or (old["name"] == entity.name and old["kind"] == entity.kind),
                "ENTITY_ID_CONFLICT", "Entity id already names another entity", 4)
    for fact in delta.facts:
        require(fact.subject in known and (fact.object is None or fact.object in known),
                "UNKNOWN_ENTITY", "Every fact endpoint must reference an entity in this book", 2)
        require(fact.valid_from is None or fact.valid_from <= chapter,
                "FUTURE_FACT", "Future plans cannot be established as current story facts", 2)
        evidence(fact.evidence)
    for closed in delta.close_facts:
        row = book.db.execute("SELECT * FROM facts WHERE id=?", (closed.id,)).fetchone()
        require(row is not None and row["valid_to"] is None, "INVALID_CLOSE", "Cannot close missing or closed fact", 4)
        require(row["valid_from"] <= chapter, "INVALID_CLOSE", "Fact closes before it starts", 2)
        evidence(closed.evidence)
    for knowledge in delta.knowledge:
        require(knowledge.character == "reader" or knowledge.character in known,
                "UNKNOWN_ENTITY", "Knowledge requires a known character", 2)
        require(knowledge.fact in known_facts, "UNKNOWN_FACT", "Knowledge references an unknown fact", 2)
        evidence(knowledge.evidence)
    if source["kind"] in ("setting", "decision"):
        declared = set(ids)
        for fact in delta.facts:
            require(fact.subject in declared and (fact.object is None or fact.object in declared),
                    "BASELINE_ENTITIES_REQUIRED", "Declare every entity used by a setting/decision delta", 2)
        require(not delta.close_facts and all(k.fact in new_facts for k in delta.knowledge),
                "BASELINE_DEPENDENCY", "Setting/decision deltas must be self-contained. Replace the original source to retract its assertions.", 2)
        require(all(k.character == "reader" or k.character in declared for k in delta.knowledge),
                "BASELINE_ENTITIES_REQUIRED", "Declare knowledge-bearing characters in this setting delta", 2)
    for hook in delta.hooks:
        evidence(hook.evidence)


def apply_delta(book, source, delta):
    chapter = source["chapter"] or 0
    validate_delta(book, source, delta, chapter)
    for entity in delta.entities:
        old = book.db.execute("SELECT aliases FROM entities WHERE id=?", (entity.id,)).fetchone()
        aliases = sorted(set(entity.aliases) | (set(json.loads(old[0])) if old else set()))
        book.db.execute("INSERT OR REPLACE INTO entities VALUES (?,?,?,?)", (entity.id, entity.name, entity.kind, dumps(aliases)))
    for fact in delta.facts:
        book.db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            fact.id, fact.subject, fact.predicate, fact.object, fact.value, source["id"],
            fact.evidence.quote, fact.evidence.offset, chapter,
            fact.valid_from if fact.valid_from is not None else chapter,
            None, fact.certainty, fact.story_time))
    for closed in delta.close_facts:
        book.db.execute("UPDATE facts SET valid_to=? WHERE id=?", (chapter, closed.id))
    for k in delta.knowledge:
        book.db.execute("INSERT OR REPLACE INTO knowledge VALUES (?,?,?,?,?,?,?)", (
            k.character, k.fact, k.state, chapter, source["id"], k.evidence.quote, k.evidence.offset))
    for hook in delta.hooks:
        old = book.db.execute("SELECT planted FROM hooks WHERE id=?", (hook.id,)).fetchone()
        book.db.execute("INSERT OR REPLACE INTO hooks VALUES (?,?,?,?,?,?,?,?)", (
            hook.id, hook.summary, hook.status, old[0] if old else chapter,
            chapter, hook.target_chapter, source["id"], hook.evidence.quote))
    if source["chapter"] is not None:
        book.db.execute("INSERT OR REPLACE INTO summaries VALUES (?,?,?)", (source["id"], chapter, delta.summary))


def resolve_entity(book, name, chapter=None, require_id=False):
    if name is None:
        return None
    exact = book.db.execute("SELECT id FROM entities WHERE id=?", (name,)).fetchone()
    if exact:
        return exact[0]
    require(not require_id, "POV_ENTITY_ID_REQUIRED", "POV queries require stable entity IDs, not name/alias resolution", 2)
    matches = []
    for row in book.db.execute("SELECT * FROM entities"):
        if name not in [row["name"], *json.loads(row["aliases"])]:
            continue
        if chapter is not None:
            try:
                historical = historical_entity(book, row["id"], chapter)
            except Exception:
                continue
            if name not in [historical["name"], *historical["aliases"]]:
                continue
        matches.append(row["id"])
    require(len(matches) == 1, "AMBIGUOUS_ENTITY" if matches else "ENTITY_NOT_FOUND",
            "Use a stable entity id; name is ambiguous or unknown")
    return matches[0]


def fact_rows(book, chapter, pov=None, seeds=None):
    params = [chapter, chapter]
    sql = "SELECT * FROM facts WHERE introduced<=? AND valid_from<=?"
    if not pov:
        sql += " AND (valid_to IS NULL OR ?<valid_to)"
        params.append(chapter)
    if seeds is not None:
        if not seeds:
            return []
        placeholders = ",".join("?" for _ in seeds)
        sql += f" AND (subject IN ({placeholders}) OR object IN ({placeholders}))"
        params.extend(list(seeds) * 2)
    rows = [dict(r) for r in book.db.execute(sql, params)]
    for row in rows:
        if pov or (row["valid_to"] is not None and row["valid_to"] > chapter):
            row["valid_to"] = None  # Do not reveal a future transition date.
    if pov:
        character = "reader" if pov == "reader" else resolve_entity(book, pov, chapter=chapter, require_id=True)
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        knowledge = {r["fact"]: dict(r) for r in book.db.execute(
            f"SELECT * FROM knowledge WHERE character=? AND chapter<=? AND fact IN ({placeholders}) ORDER BY chapter", [character, chapter, *ids])}
        rows = [dict(r, knowledge_state=knowledge[r["id"]]["state"], knowledge_evidence=knowledge[r["id"]], view="character_memory")
                for r in rows if r["id"] in knowledge and knowledge[r["id"]]["state"] != "rejects"]
    return rows


def reset_graph(book):
    for table in ("knowledge", "facts", "entities", "hooks", "summaries"):
        book.db.execute(f"DELETE FROM {table}")


def historical_graph(book, chapter):
    """Temporal facts are append/close; hook snapshots must use the ledger at the requested chapter."""
    hooks = {}
    for row in book.db.execute("SELECT l.delta,l.source_id,s.chapter FROM ledger l JOIN sources s ON s.id=l.source_id WHERE l.valid=1 ORDER BY l.seq"):
        if row["chapter"] is not None and row["chapter"] > chapter:
            continue
        for hook in json.loads(row["delta"]).get("hooks", []):
            previous = hooks.get(hook["id"], {})
            hooks[hook["id"]] = dict(hook, source_version=row["source_id"], planted=previous.get("planted", row["chapter"] or 0), advanced=row["chapter"] or 0)
    return list(hooks.values())


def historical_entity(book, entity_id, chapter, pov=None):
    if pov:
        # Alias knowledge has to be represented as a sourced fact; a global name
        # dictionary is never evidence that a character knows a secret identity.
        return {"id": entity_id}
    node = None
    for row in book.db.execute("SELECT l.delta,s.chapter FROM ledger l JOIN sources s ON s.id=l.source_id WHERE l.valid=1 ORDER BY l.seq"):
        if row["chapter"] is not None and row["chapter"] > chapter:
            continue
        for entity in json.loads(row["delta"]).get("entities", []):
            if entity["id"] == entity_id:
                aliases = sorted(set(entity.get("aliases", [])) | set((node or {}).get("aliases", [])))
                node = dict(entity, aliases=aliases)
    require(node is not None, "ENTITY_NOT_YET_INTRODUCED", "Entity is not introduced at this chapter")
    return node

"""Disposable, job-bound candidate graph snapshots; never authoritative memory.

The blob holds only the five graph tables. It is opened in RAM, advanced there,
then persisted in the same book transaction as the batch and cursor. Cache misses
rebuild from evidence-backed deltas. Commit always replays authoritative deltas.
"""
from contextlib import contextmanager
import hashlib
import sqlite3
from types import SimpleNamespace

from .store import dumps

TABLES = ("entities", "facts", "knowledge", "hooks", "summaries")
FORMAT = 1  # Bump whenever graph schema or validation semantics change.


def ensure_table(book):
    book.db.execute("""CREATE TABLE IF NOT EXISTS revision_snapshots(
        job_id TEXT PRIMARY KEY,binding TEXT NOT NULL,payload BLOB NOT NULL,checksum TEXT NOT NULL)""")


def discard(book, job_id):
    if book.db.execute("SELECT 1 FROM sqlite_master WHERE name='revision_snapshots'").fetchone():
        book.db.execute("DELETE FROM revision_snapshots WHERE job_id=?", (job_id,))


def binding(book, job, manifest):
    """Include actual source/delta bytes, not just IDs, to invalidate stale caches."""
    h = hashlib.sha256(dumps([FORMAT, book.id, job["id"], job["position"], manifest]).encode())
    def feed(row):
        h.update(dumps(tuple(row)).encode("utf-8"))
    for row in book.db.execute("""SELECT l.seq,l.source_id,l.delta,s.hash,s.content
        FROM ledger l JOIN sources s ON s.id=l.source_id
        WHERE l.valid=1 AND (s.chapter IS NULL OR s.chapter<?) ORDER BY l.seq""", (manifest["first_chapter"],)):
        feed(row)
    for sid, bid in zip(manifest["sources"], manifest["batches"]):
        row = book.db.execute("""SELECT b.id,b.source_id,b.base_revision,b.delta,s.hash,s.content
            FROM batches b JOIN sources s ON s.id=b.source_id WHERE b.id=?""", (bid,)).fetchone()
        feed(row if row else (sid, bid, "missing"))
    return h.hexdigest()


def copy_graph(book, db):
    for table in TABLES:
        sql = book.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        db.execute(sql)
        rows = book.db.execute(f"SELECT * FROM {table}").fetchall()
        if rows:
            db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in rows[0])})", [tuple(r) for r in rows])
    for row in book.db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='facts' AND sql IS NOT NULL"):
        db.execute(row[0])
    db.commit()


@contextmanager
def candidate(book, job, manifest):
    from .revisions import _replay

    ensure_table(book)
    expected = binding(book, job, manifest)
    row = book.db.execute("SELECT * FROM revision_snapshots WHERE job_id=?", (job["id"],)).fetchone()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        restored = False
        if row and row["binding"] == expected and hashlib.sha256(row["payload"]).hexdigest() == row["checksum"]:
            try:
                db.deserialize(row["payload"])
                restored = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                restored = restored and names == set(TABLES)
            except sqlite3.DatabaseError:
                restored = False
        if not restored:
            db.close()
            db = sqlite3.connect(":memory:")
            db.row_factory = sqlite3.Row
            book.db.execute("SAVEPOINT candidate_seed")
            try:
                _replay(book, manifest, manifest["batches"])
                copy_graph(book, db)
            finally:
                book.db.execute("ROLLBACK TO candidate_seed")
                book.db.execute("RELEASE candidate_seed")
        yield SimpleNamespace(db=db, restored=restored)
    finally:
        db.close()


def capture(graph):
    graph.db.commit()
    return graph.db.serialize()


def save(book, job, manifest, payload):
    book.db.execute("INSERT OR REPLACE INTO revision_snapshots VALUES (?,?,?,?)",
                    (job["id"], binding(book, job, manifest), payload, hashlib.sha256(payload).hexdigest()))

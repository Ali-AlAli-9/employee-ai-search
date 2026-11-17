"""Portable persistence layer: SQLite by default, Postgres via ``DATABASE_URL``.

SQLite stays the zero-setup default (stdlib ``sqlite3``, no ORM). When
``DATABASE_URL`` points at Postgres the same public functions talk to
``psycopg`` 3 through a small connection wrapper, so callers never see the
dialect. The driver and its pool are imported lazily: a SQLite install does not
need them.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from .config import settings

_lock = threading.Lock()

try:  # optional dependency: only needed when DATABASE_URL is a Postgres URL
    from psycopg import IntegrityError as _PgIntegrityError
except Exception:  # pragma: no cover - exercised by the SQLite-only install
    _PgIntegrityError = None

# Both drivers raise their own class; uploads catch this tuple instead of
# importing either driver into the HTTP layer.
IntegrityErrors: tuple[type[BaseException], ...] = (sqlite3.IntegrityError,)
if _PgIntegrityError is not None:
    IntegrityErrors = IntegrityErrors + (_PgIntegrityError,)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    owner_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    chunks_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    content_hash TEXT,
    workspace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    workspace_id TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    results_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT,
    created_at TEXT NOT NULL,
    workspace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_user ON queries(user_id, created_at);

CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_query ON traces(query_id);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    display_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_guest INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    workspace_id TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_agent TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Account-keyed login failures. The email is already normalised by the helper
-- below, so case/whitespace variants share one row. Unknown emails are recorded
-- too: otherwise a 429 would reveal that an address exists.
CREATE TABLE IF NOT EXISTS login_attempts (
    email TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_updated ON login_attempts(updated_at);

-- Read model of Supabase Auth users (spec 005). Supabase owns identity and this
-- table exists because GoTrue's admin list cannot search or filter, and because
-- an admin must be able to disable an account without waiting for a JWT to
-- expire. Only `local` mode ignores it.
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'viewer',
    display_name TEXT,
    is_guest INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_sign_in_at TEXT,
    workspace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email);
CREATE INDEX IF NOT EXISTS idx_profiles_role ON profiles(role, is_active);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Dialect selection
# --------------------------------------------------------------------------- #
# Supabase's dashboard shows its connection-string template with square
# placeholders: ``postgres.[PROJECT-REF]``, ``aws-0-[REGION].pooler...`` and
# ``[YOUR-PASSWORD]``. A partially edited copy can therefore leave brackets
# anywhere in the URL. ``urlparse`` treats any bracket in the netloc as IPv6 and
# raises ValueError, which used to crash the app at import time. Strip every
# bracket pair that does not contain a real IPv6 address, wherever it appears.
_BRACKETED_RE = re.compile(r"\[([^\[\]]*)\]")


def _normalise_database_url(url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1)
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return inner
        return match.group(0)

    return _BRACKETED_RE.sub(replace, url)


def _database_url() -> str:
    url = _normalise_database_url((settings.database_url or "").strip())
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _is_postgres() -> bool:
    return _database_url().startswith(("postgresql://", "postgres://"))


def dialect() -> str:
    """``"postgres"`` or ``"sqlite"`` for the configured backend."""
    return "postgres" if _is_postgres() else "sqlite"


class CompatConnection:
    """The tiny slice of the DB-API that this project uses, dialect-neutral.

    * ``?`` placeholders are translated to ``%s`` for Postgres.
    * ``execute``/``executemany``/``commit``/``rollback``/``close`` match both
      ``sqlite3.Connection`` and ``psycopg.Connection``.
    """

    def __init__(self, raw: Any, engine: str):
        self._raw = raw
        self.engine = engine

    def _sql(self, sql: str) -> str:
        if self.engine == "sqlite":
            return sql
        # The project never puts a literal '?' in SQL, only placeholders.
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Any = None):
        if params is None:
            return self._raw.execute(self._sql(sql))
        return self._raw.execute(self._sql(sql), params)

    def executemany(self, sql: str, params: Any):
        # psycopg 3 exposes execute() on Connection but executemany() only on
        # Cursor; sqlite3 exposes both on Connection. Always go through a
        # cursor for Postgres so a 7.6 MB upload does not fail at the final
        # chunk insert with "'Connection' object has no attribute 'executemany'".
        if self.engine == "postgres":
            with self._raw.cursor() as cur:
                return cur.executemany(self._sql(sql), params)
        return self._raw.executemany(self._sql(sql), params)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


_pg_pool: Any = None
_pg_pool_url = ""
_pg_pool_lock = threading.Lock()


def _pool_kwargs(url: str) -> dict[str, Any]:
    """Connection options for the configured URL.

    Supabase's transaction pooler (port 6543) multiplexes many clients over one
    server connection, so server-side prepared statements leak between clients.
    psycopg must therefore skip them (`prepare_threshold=None` means "never").
    Direct connections keep the default so the common path stays fast.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError as exc:  # malformed URL must not crash the whole app
        # The host portion is safe to show: the password lives before the last @.
        host_hint = url.rpartition("@")[-1][:120]
        raise RuntimeError(
            "DATABASE_URL is not a valid PostgreSQL URL. "
            "Use the Transaction pooler string from Supabase: "
            "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres "
            f"(no square brackets). Host portion: {host_hint!r}"
        ) from exc
    host = parsed.hostname or ""
    kwargs: dict[str, Any] = {
        "row_factory": None,  # replaced below; keeps the dict shape explicit
        "application_name": "employee-ai-search",
    }
    from psycopg.rows import dict_row

    kwargs["row_factory"] = dict_row
    if parsed.port == 6543 or "pooler.supabase.com" in host:
        kwargs["prepare_threshold"] = None
    return kwargs


def _get_pool() -> Any:
    """Create (once) the psycopg connection pool for the configured URL."""
    global _pg_pool, _pg_pool_url

    url = _database_url()
    with _pg_pool_lock:
        if _pg_pool is not None and _pg_pool_url == url:
            return _pg_pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise RuntimeError(
                "DATABASE_URL points at Postgres but the driver is missing. "
                "Install 'psycopg[binary,pool]' (backend/requirements.txt) or "
                "leave DATABASE_URL empty to use SQLite."
            ) from exc

        if _pg_pool is not None:
            try:
                _pg_pool.close()
            except Exception:  # noqa: BLE001 - a stale pool must not block startup
                pass
        # min_size=0: a sleeping free instance should not hold idle sessions.
        _pg_pool = ConnectionPool(
            url,
            min_size=0,
            max_size=4,
            kwargs=_pool_kwargs(url),
        )
        _pg_pool_url = url
        return _pg_pool


def reset_pool() -> None:
    """Drop the pool so tests can switch ``settings.database_url`` safely."""
    global _pg_pool, _pg_pool_url
    with _pg_pool_lock:
        if _pg_pool is not None:
            try:
                _pg_pool.close()
            except Exception:  # noqa: BLE001
                pass
        _pg_pool = None
        _pg_pool_url = ""


def connect() -> sqlite3.Connection:
    """A raw SQLite connection (kept for backwards compatibility)."""
    if _is_postgres():
        raise RuntimeError("connect() is SQLite-only; use get_conn()")
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn() -> Iterator[CompatConnection]:
    if _is_postgres():
        pool = _get_pool()
        raw = pool.getconn()
        conn = CompatConnection(raw, "postgres")
        try:
            yield conn
            raw.commit()
        except BaseException:
            try:
                raw.rollback()
            except Exception:  # noqa: BLE001 - broken connection is discarded below
                pass
            raise
        finally:
            pool.putconn(raw)
        return

    raw = connect()
    conn = CompatConnection(raw, "sqlite")
    try:
        yield conn
        raw.commit()
    except BaseException:
        raw.rollback()
        raise
    finally:
        raw.close()


def _table_columns(conn: CompatConnection, table: str) -> set[str]:
    if conn.engine == "postgres":
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = current_schema()",
            (table,),
        ).fetchall()
        return {row["column_name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def init_db() -> None:
    settings.ensure_dirs()
    with _lock, get_conn() as conn:
        # SQLite's executescript() does not exist in psycopg, so walk the
        # statement list. There are no semicolons inside string literals.
        for statement in _SCHEMA.split(";"):
            text = statement.strip()
            if text:
                conn.execute(text)

        # In-place migration for databases created before duplicate detection.
        # SQLite has no "ADD COLUMN IF NOT EXISTS", so inspect the table first.
        columns = _table_columns(conn, "documents")
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")

        # Workspace columns are optional: NULL means "not scoped" in every
        # helper below, so callers written before isolation keep their behaviour.
        for table in ("documents", "chunks", "queries", "users", "profiles"):
            if "workspace_id" not in _table_columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT")

        # The default workspace must exist before legacy rows are backfilled.
        _ensure_default_workspace(conn)
        for table in ("documents", "chunks", "queries", "users", "profiles"):
            conn.execute(
                f"UPDATE {table} SET workspace_id = ? WHERE workspace_id IS NULL",
                (settings.default_workspace_id,),
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash)"
        )
        # Duplicate detection is per workspace: identical bytes may be uploaded
        # to two workspaces. The pre-isolation index covered only content_hash,
        # so retire it and create the workspace-aware one instead.
        conn.execute("DROP INDEX IF EXISTS idx_documents_hash_unique")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash_workspace_unique "
            "ON documents(workspace_id, content_hash) "
            "WHERE content_hash IS NOT NULL AND status != 'failed'"
        )
        # Two NULLs are distinct in a unique index, so the legacy unscoped API
        # still needs its own guard against concurrent duplicate uploads.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash_legacy_unique "
            "ON documents(content_hash) "
            "WHERE content_hash IS NOT NULL AND status != 'failed' AND workspace_id IS NULL"
        )


# --------------------------------------------------------------------------- #
# Workspaces
# --------------------------------------------------------------------------- #
def _ensure_default_workspace(conn: CompatConnection) -> dict[str, Any]:
    """Get-or-create the configured default workspace on an open connection."""
    ws_id = settings.default_workspace_id
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    if row is None:
        ts = now_iso()
        conn.execute(
            "INSERT INTO workspaces "
            "(id, name, invite_code, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, ?, ?)",
            (ws_id, settings.default_workspace_name, secrets.token_urlsafe(12), ts, ts),
        )
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    assert row is not None
    return dict(row)


def create_workspace(
    name: str, invite_code: str, owner_id: str | None = None
) -> dict[str, Any]:
    ws_id = new_id()
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO workspaces "
            "(id, name, invite_code, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ws_id, name, invite_code, owner_id, ts, ts),
        )
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
    assert row is not None
    return dict(row)


def get_workspace(workspace_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
    return dict(row) if row else None


def get_workspace_by_invite(invite_code: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM workspaces WHERE invite_code = ?", (invite_code,)
        ).fetchone()
    return dict(row) if row else None


def default_workspace() -> dict[str, Any]:
    """The well-known home workspace, created on first use."""
    with get_conn() as conn:
        return _ensure_default_workspace(conn)


def public_workspace(ws: dict[str, Any]) -> dict[str, Any]:
    """The safe projection of a workspace row (no owner id or timestamps)."""
    return {
        "id": ws["id"],
        "name": ws["name"],
        "invite_code": ws["invite_code"],
    }


def set_workspace_owner(workspace_id: str, owner_id: str) -> None:
    """Attach the employer account after its signup succeeded."""

    with get_conn() as conn:
        conn.execute(
            "UPDATE workspaces SET owner_id = ?, updated_at = ? WHERE id = ?",
            (owner_id, now_iso(), workspace_id),
        )


def delete_workspace(workspace_id: str) -> None:
    """Roll back a workspace whose owner signup failed."""

    with get_conn() as conn:
        conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def create_document(
    *,
    filename: str,
    stored_filename: str,
    content_type: str,
    size_bytes: int,
    uploaded_by: str,
    content_hash: str | None = None,
    workspace_id: str | None = None,
) -> str:
    doc_id = new_id()
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents
                (id, filename, stored_filename, content_type, size_bytes, status,
                 chunks_count, uploaded_by, created_at, updated_at, content_hash, workspace_id)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?)
            """,
            (
                doc_id,
                filename,
                stored_filename,
                content_type,
                size_bytes,
                uploaded_by,
                ts,
                ts,
                content_hash,
                workspace_id,
            ),
        )
    return doc_id


def find_document_by_hash(
    content_hash: str, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    """The newest document with these exact bytes, ignoring failed ingests."""
    sql = "SELECT * FROM documents WHERE content_hash = ? AND status != 'failed'"
    params: list[Any] = [content_hash]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql + " ORDER BY created_at DESC LIMIT 1", params).fetchone()
    return _doc_row(row) if row else None


def update_document(
    document_id: str, *, workspace_id: str | None = None, **fields: Any
) -> None:
    # ``workspace_id`` is a scope, never a settable field: callers that pass it
    # inside ``fields`` get the same behaviour as omitting it.
    allowed = {"status", "chunks_count", "error_message", "completed_at", "updated_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates.setdefault("updated_at", now_iso())
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [document_id]
    sql = f"UPDATE documents SET {assignments} WHERE id = ?"
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        values.append(workspace_id)
    with get_conn() as conn:
        conn.execute(sql, values)


def _doc_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    data.pop("stored_filename", None)
    return data


def get_document(
    document_id: str, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    sql = "SELECT * FROM documents WHERE id = ?"
    params: list[Any] = [document_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return _doc_row(row) if row else None


def list_documents(
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    content_type: str | None = None,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if content_type:
        where.append("content_type = ?")
        params.append(content_type)
    if workspace_id is not None:
        where.append("workspace_id = ?")
        params.append(workspace_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    offset = max(0, (page - 1) * page_size)
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM documents {clause}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM documents {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
    return [_doc_row(r) for r in rows], int(total)


def all_documents(*, workspace_id: str | None = None) -> list[dict[str, Any]]:
    """Every document row, regardless of status (used by the consistency tools)."""
    sql = "SELECT * FROM documents"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY created_at, id", params).fetchall()
    return [_doc_row(row) for row in rows]


def completed_document_ids(
    allowed: list[str] | None = None, *, workspace_id: str | None = None
) -> list[str]:
    """Ids of indexed documents, optionally restricted to a caller's subset.

    Retrieval must not consider `pending`, `processing` or `failed` rows: their
    chunks may not exist yet, or may have been rolled back after an error.
    """
    params: list[Any] = []
    clause = ""
    if allowed is not None:
        if not allowed:
            return []
        placeholders = ",".join("?" for _ in allowed)
        clause = f" AND id IN ({placeholders})"
        params.extend(allowed)
    if workspace_id is not None:
        clause += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE status = 'completed'"
            + clause
            + " ORDER BY created_at, id",
            params,
        ).fetchall()
    return [str(row["id"]) for row in rows]


def delete_document(document_id: str, *, workspace_id: str | None = None) -> bool:
    sql = "DELETE FROM documents WHERE id = ?"
    params: list[Any] = [document_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Chunks
# --------------------------------------------------------------------------- #
def insert_chunks(
    chunks: list[dict[str, Any]], *, workspace_id: str | None = None
) -> None:
    if not chunks:
        return
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO chunks
                (id, document_id, chunk_index, text, token_count, metadata_json,
                 created_at, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                document_id = excluded.document_id,
                chunk_index = excluded.chunk_index,
                text = excluded.text,
                token_count = excluded.token_count,
                metadata_json = excluded.metadata_json
            """,
            [
                (
                    c["id"],
                    c["document_id"],
                    c["chunk_index"],
                    c["text"],
                    c["token_count"],
                    json.dumps(c.get("metadata", {}), ensure_ascii=False),
                    c.get("created_at", now_iso()),
                    workspace_id,
                )
                for c in chunks
            ],
        )


def _chunk_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    try:
        data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        data["metadata"] = {}
    return data


def get_chunks(
    chunk_ids: list[str], *, workspace_id: str | None = None
) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" for _ in chunk_ids)
    sql = (
        "SELECT c.*, d.filename AS document_filename "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        f"WHERE c.id IN ({placeholders})"
    )
    params: list[Any] = list(chunk_ids)
    if workspace_id is not None:
        sql += " AND c.workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row["id"]: _chunk_row(row) for row in rows}


def chunks_after(
    document_id: str,
    chunk_index: int,
    limit: int,
    *,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """The next ``limit`` chunks of one document, in reading order."""
    if limit <= 0:
        return []
    sql = (
        "SELECT c.*, d.filename AS document_filename "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.document_id = ? AND c.chunk_index > ?"
    )
    params: list[Any] = [document_id, chunk_index]
    if workspace_id is not None:
        sql += " AND c.workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY c.chunk_index LIMIT ?", [*params, limit]).fetchall()
    return [_chunk_row(row) for row in rows]


def all_chunks(
    limit: int = 10000, *, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    sql = (
        "SELECT c.*, d.filename AS document_filename "
        "FROM chunks c JOIN documents d ON d.id = c.document_id"
    )
    params: list[Any] = []
    if workspace_id is not None:
        sql += " WHERE c.workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY c.created_at DESC LIMIT ?", [*params, limit]).fetchall()
    return [_chunk_row(r) for r in rows]


def chunks_version(*, workspace_id: str | None = None) -> tuple[int, str]:
    """Cheap fingerprint of the chunk table, used to cache corpus statistics.

    ``MAX(rowid)`` is not usable: SQLite reuses rowids after a delete, so an
    upload could look like a version the cache has already seen. Insertion
    timestamps only move forward.
    """
    sql = "SELECT COUNT(*) AS total, COALESCE(MAX(created_at), '') AS newest FROM chunks"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["total"]), str(row["newest"])


def delete_chunks_by_document(
    document_id: str, *, workspace_id: str | None = None
) -> None:
    sql = "DELETE FROM chunks WHERE document_id = ?"
    params: list[Any] = [document_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        conn.execute(sql, params)


def delete_chunks(chunk_ids: list[str], *, workspace_id: str | None = None) -> int:
    """Delete explicit chunk ids; used by the opt-in consistency repair."""
    if not chunk_ids:
        return 0
    placeholders = ",".join("?" for _ in chunk_ids)
    where = f"id IN ({placeholders})"
    params: list[Any] = list(chunk_ids)
    if workspace_id is not None:
        where += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        found = conn.execute(
            f"SELECT COUNT(*) AS c FROM chunks WHERE {where}", params
        ).fetchone()["c"]
        conn.execute(f"DELETE FROM chunks WHERE {where}", params)
    return int(found)


def document_chunk_counts(*, workspace_id: str | None = None) -> dict[str, int]:
    sql = "SELECT document_id, COUNT(*) AS c FROM chunks"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " GROUP BY document_id", params).fetchall()
    return {str(row["document_id"]): int(row["c"]) for row in rows}


def all_chunk_refs(*, workspace_id: str | None = None) -> dict[str, str]:
    """Map every chunk id to its document id, including orphan chunks."""
    sql = "SELECT id, document_id FROM chunks"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " WHERE workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {str(row["id"]): str(row["document_id"]) for row in rows}


def stale_documents(
    status: str, older_than: str, *, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    """Rows still in `status` whose last update predates `older_than`."""
    sql = "SELECT * FROM documents WHERE status = ? AND updated_at < ?"
    params: list[Any] = [status, older_than]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY updated_at", params).fetchall()
    return [_doc_row(row) for row in rows]


# --------------------------------------------------------------------------- #
# Queries & traces
# --------------------------------------------------------------------------- #
def record_query(
    query_id: str,
    query_text: str,
    query_type: str,
    user_id: str,
    results_count: int,
    latency_ms: int,
    trace_id: str | None = None,
    *,
    workspace_id: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO queries
                (id, query_text, query_type, user_id, results_count, latency_ms,
                 trace_id, created_at, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query_id,
                query_text,
                query_type,
                user_id,
                results_count,
                latency_ms,
                trace_id,
                now_iso(),
                workspace_id,
            ),
        )


def record_trace(query_id: str, data: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO traces (id, query_id, data_json, created_at) VALUES (?, ?, ?, ?)",
            (new_id(), query_id, json.dumps(data, ensure_ascii=False), now_iso()),
        )


def list_chat_history(
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    *,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    offset = max(0, (page - 1) * page_size)
    where = "user_id = ? AND query_type = 'chat'"
    params: list[Any] = [user_id]
    if workspace_id is not None:
        where += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM queries WHERE {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM queries WHERE {where} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            answer = ""
            citations: list[dict[str, Any]] = []
            trace = conn.execute(
                "SELECT data_json FROM traces WHERE query_id = ? ORDER BY created_at DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if trace:
                try:
                    data = json.loads(trace["data_json"])
                    answer = data.get("answer", "")
                    citations = data.get("citations", [])
                except json.JSONDecodeError:
                    pass
            items.append(
                {"role": "user", "content": row["query_text"], "timestamp": row["created_at"]}
            )
            if answer:
                items.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "citations": citations,
                        "timestamp": row["created_at"],
                    }
                )
    return items, int(total)


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
_USER_FIELDS = {"password_hash", "role", "display_name", "is_active", "last_login_at"}


def create_user(
    *,
    email: str,
    password_hash: str,
    role: str = "user",
    display_name: str | None = None,
    is_guest: bool = False,
    is_active: bool = True,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    user_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users
                (id, email, password_hash, role, display_name, is_active, is_guest,
                 created_at, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                email,
                password_hash,
                role,
                display_name,
                1 if is_active else 0,
                1 if is_guest else 0,
                now_iso(),
                workspace_id,
            ),
        )
    user = get_user(user_id, workspace_id=workspace_id)
    assert user is not None
    return user


def get_user(user_id: str, *, workspace_id: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM users WHERE id = ?"
    params: list[Any] = [user_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def get_user_by_email(
    email: str, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    sql = "SELECT * FROM users WHERE email = ?"
    params: list[Any] = [email]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def update_user(user_id: str, *, workspace_id: str | None = None, **fields: Any) -> None:
    updates = {k: v for k, v in fields.items() if k in _USER_FIELDS}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [user_id]
    sql = f"UPDATE users SET {assignments} WHERE id = ?"
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        values.append(workspace_id)
    with get_conn() as conn:
        conn.execute(sql, values)


def delete_user(user_id: str, *, workspace_id: str | None = None) -> bool:
    sql = "DELETE FROM users WHERE id = ?"
    params: list[Any] = [user_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


def list_users(
    *,
    q: str = "",
    include_guests: bool = False,
    page: int = 1,
    page_size: int = 20,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Search and paginate the local (spec-004) account table.

    Mirrors :func:`list_profiles` so the admin API can stay provider-neutral.
    """
    safe_page = max(1, page)
    safe_size = max(1, min(100, page_size))
    clauses: list[str] = []
    params: list[Any] = []
    if not include_guests:
        clauses.append("is_guest = 0")
    term = (q or "").strip()
    if term:
        pattern = _like_pattern(term)
        clauses.append(
            "(LOWER(COALESCE(email, '')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(display_name, '')) LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_conn() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM users {where}", params
        ).fetchone()
        total = int(total_row["total"] if total_row else 0)
        rows = conn.execute(
            f"SELECT * FROM users {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, safe_size, (safe_page - 1) * safe_size],
        ).fetchall()
    return [dict(row) for row in rows], total


def count_active_user_admins(*, workspace_id: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS total FROM users WHERE role = 'admin' AND is_active = 1"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["total"] if row else 0)


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def create_session(
    *,
    user_id: str,
    token_hash: str,
    csrf_hash: str,
    expires_at: str,
    user_agent: str | None = None,
) -> str:
    session_id = new_id()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions
                (id, user_id, token_hash, csrf_hash, expires_at, created_at, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                token_hash,
                csrf_hash,
                expires_at,
                now_iso(),
                user_agent,
            ),
        )
    return session_id


def get_session(token_hash: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return dict(row) if row else None


def delete_session(token_hash: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        return cur.rowcount > 0


def delete_expired_sessions(now: str | None = None) -> int:
    moment = now or now_iso()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (moment,))
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Login attempts (account-keyed lockout)
# --------------------------------------------------------------------------- #
_LOGIN_ATTEMPT_TTL_HOURS = 24


def normalise_login_key(email: str) -> str:
    """One key for every spelling of an address, including unknown ones."""
    return (email or "").strip().casefold()


def _parse_login_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def login_lock_status(email: str, *, now: datetime | None = None) -> tuple[bool, int]:
    """Return ``(locked, retry_after_seconds)`` for a normalised email.

    An expired lock row is removed here, so a later valid password starts from
    a fresh counter instead of immediately re-locking the account.
    """
    key = normalise_login_key(email)
    if not key:
        return False, 0
    moment = now or datetime.now(timezone.utc)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT locked_until FROM login_attempts WHERE email = ?", (key,)
        ).fetchone()
    if row is None:
        return False, 0

    locked_until = _parse_login_time(row["locked_until"])
    if locked_until is None:
        return False, 0
    remaining = (locked_until - moment).total_seconds()
    if remaining > 0:
        return True, max(1, int(math.ceil(remaining)))

    with get_conn() as conn:
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (key,))
    return False, 0


def record_login_failure(email: str, *, now: datetime | None = None) -> tuple[bool, int]:
    """Count one credential failure and return the new lock state.

    The attempt that reaches the threshold is itself refused, so an attacker
    cannot keep probing for one extra request after the counter fills up.
    """
    key = normalise_login_key(email)
    if not key:
        return False, 0
    moment = now or datetime.now(timezone.utc)
    locked, retry_after = login_lock_status(email, now=moment)
    if locked:
        return True, retry_after

    threshold = max(1, int(settings.login_lock_max_failures))
    lock_minutes = max(1, int(settings.login_lock_minutes))
    with get_conn() as conn:
        row = conn.execute(
            "SELECT failures FROM login_attempts WHERE email = ?", (key,)
        ).fetchone()
        failures = int(row["failures"]) + 1 if row is not None else 1
        locked_until = (
            (moment + timedelta(minutes=lock_minutes)).isoformat()
            if failures >= threshold
            else None
        )
        conn.execute(
            """
            INSERT INTO login_attempts (email, failures, locked_until, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                failures = excluded.failures,
                locked_until = excluded.locked_until,
                updated_at = excluded.updated_at
            """,
            (key, failures, locked_until, moment.isoformat()),
        )
    if locked_until is None:
        return False, 0
    return True, lock_minutes * 60


def clear_login_attempts(email: str) -> None:
    """Forget failures after a successful sign-in."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM login_attempts WHERE email = ?", (normalise_login_key(email),)
        )


def sweep_login_attempts(*, now: datetime | None = None) -> int:
    """Drop stale counters so probing invented addresses cannot grow the table."""
    moment = now or datetime.now(timezone.utc)
    cutoff = (moment - timedelta(hours=_LOGIN_ATTEMPT_TTL_HOURS)).isoformat()
    current = moment.isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM login_attempts WHERE updated_at < ? "
            "AND (locked_until IS NULL OR locked_until < ?)",
            (cutoff, current),
        )
        return int(cur.rowcount)


# --------------------------------------------------------------------------- #
# Profiles (Supabase read model)
# --------------------------------------------------------------------------- #
_PROFILE_FIELDS = {
    "email",
    "role",
    "display_name",
    "is_guest",
    "is_active",
    "last_sign_in_at",
}


def _like_pattern(value: str) -> str:
    """Escape LIKE wildcards so a search for ``%`` is not a wildcard."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def upsert_profile(
    *,
    profile_id: str,
    email: str | None,
    role: str,
    display_name: str | None = None,
    is_guest: bool = False,
    is_active: bool | None = None,
    last_sign_in_at: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Insert or refresh one profile.

    ``is_active=None`` preserves the current flag on conflict: a disabled user
    must not be re-enabled just by signing in. Passing a boolean is the admin
    action and overwrites it.
    """
    created_at = now_iso()
    lookup_sql = "SELECT id FROM profiles WHERE id = ?"
    lookup_params: list[Any] = [profile_id]
    if workspace_id is not None:
        lookup_sql += " AND workspace_id = ?"
        lookup_params.append(workspace_id)
    with get_conn() as conn:
        existing = conn.execute(lookup_sql, lookup_params).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO profiles
                    (id, email, role, display_name, is_guest, is_active,
                     created_at, last_sign_in_at, workspace_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    email,
                    role,
                    display_name,
                    1 if is_guest else 0,
                    1 if (is_active is None or is_active) else 0,
                    created_at,
                    last_sign_in_at,
                    workspace_id,
                ),
            )
        else:
            active_sql = "" if is_active is None else ", is_active = ?"
            params: list[Any] = [
                email,
                role,
                display_name,
                1 if is_guest else 0,
                last_sign_in_at,
            ]
            if is_active is not None:
                params.append(1 if is_active else 0)
            params.append(profile_id)
            where = " WHERE id = ?"
            if workspace_id is not None:
                where += " AND workspace_id = ?"
                params.append(workspace_id)
            conn.execute(
                "UPDATE profiles SET email = ?, role = ?, display_name = ?, "
                "is_guest = ?, last_sign_in_at = ?"
                + active_sql
                + where,
                params,
            )
    profile = get_profile(profile_id, workspace_id=workspace_id)
    assert profile is not None
    return profile


def get_profile(
    profile_id: str, *, workspace_id: str | None = None
) -> dict[str, Any] | None:
    sql = "SELECT * FROM profiles WHERE id = ?"
    params: list[Any] = [profile_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def list_profiles(
    *,
    q: str = "",
    include_guests: bool = False,
    page: int = 1,
    page_size: int = 20,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Search and paginate the profile index.

    ``LOWER(...) LIKE`` is deliberately used instead of ``ILIKE`` so the same SQL
    runs on SQLite and Postgres. The table is small (people, not documents), so
    a scan is cheaper than maintaining per-dialect indexes or a search engine.
    """
    safe_page = max(1, page)
    safe_size = max(1, min(100, page_size))
    clauses: list[str] = []
    params: list[Any] = []
    if not include_guests:
        clauses.append("is_guest = 0")
    term = (q or "").strip()
    if term:
        pattern = _like_pattern(term)
        clauses.append(
            "(LOWER(COALESCE(email, '')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(display_name, '')) LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_conn() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM profiles {where}", params
        ).fetchone()
        total = int(total_row["total"] if total_row else 0)
        rows = conn.execute(
            f"SELECT * FROM profiles {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, safe_size, (safe_page - 1) * safe_size],
        ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["is_guest"] = bool(item.get("is_guest"))
        item["is_active"] = bool(item.get("is_active"))
        items.append(item)
    return items, total


def update_profile(
    profile_id: str, *, workspace_id: str | None = None, **fields: Any
) -> dict[str, Any] | None:
    updates = {key: value for key, value in fields.items() if key in _PROFILE_FIELDS}
    if not updates:
        return get_profile(profile_id, workspace_id=workspace_id)
    if "is_guest" in updates:
        updates["is_guest"] = 1 if updates["is_guest"] else 0
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [*updates.values(), profile_id]
    sql = f"UPDATE profiles SET {assignments} WHERE id = ?"
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        values.append(workspace_id)
    with get_conn() as conn:
        conn.execute(sql, values)
    return get_profile(profile_id, workspace_id=workspace_id)


def delete_profile(profile_id: str, *, workspace_id: str | None = None) -> bool:
    sql = "DELETE FROM profiles WHERE id = ?"
    params: list[Any] = [profile_id]
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


def count_active_admins(*, workspace_id: str | None = None) -> int:
    sql = "SELECT COUNT(*) AS total FROM profiles WHERE role = 'admin' AND is_active = 1"
    params: list[Any] = []
    if workspace_id is not None:
        sql += " AND workspace_id = ?"
        params.append(workspace_id)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row["total"] if row else 0)


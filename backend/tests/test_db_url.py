"""DATABASE_URL parsing survives common copy/paste artefacts from Supabase."""

from __future__ import annotations

from app import db
from app.config import settings


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def executemany(self, sql: str, params: object) -> None:
        self.calls.append((sql, params))


class _FakePgConnection:
    """psycopg 3 has no Connection.executemany - only Cursor.executemany."""

    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_compat_executemany_uses_cursor_for_postgres() -> None:
    raw = _FakePgConnection()
    conn = db.CompatConnection(raw, "postgres")

    conn.executemany("INSERT INTO chunks VALUES (?, ?)", [(1, 2), (3, 4)])

    assert raw.cursor_obj.calls == [
        ("INSERT INTO chunks VALUES (%s, %s)", [(1, 2), (3, 4)])
    ]


def test_compat_executemany_stays_on_connection_for_sqlite() -> None:
    class FakeSqliteConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def executemany(self, sql: str, params: object) -> None:
            self.calls.append((sql, params))

    raw = FakeSqliteConnection()
    conn = db.CompatConnection(raw, "sqlite")

    conn.executemany("INSERT INTO chunks VALUES (?, ?)", [(1, 2)])

    assert raw.calls == [("INSERT INTO chunks VALUES (?, ?)", [(1, 2)])]


def _normalise(value: str) -> str:
    previous = settings.database_url
    object.__setattr__(settings, "database_url", value)
    try:
        return db._database_url()
    finally:
        object.__setattr__(settings, "database_url", previous)


def test_bracketed_dns_host_is_repaired():
    raw = "postgresql://postgres.ref:pw@[aws-0-ap-southeast-1.pooler.supabase.com]:6543/postgres"

    result = _normalise(raw)

    assert "@aws-0-ap-southeast-1.pooler.supabase.com:6543" in result
    assert "[" not in result and "]" not in result


def test_bracketed_region_in_host_is_repaired():
    raw = "postgresql://postgres.ref:pw@aws-0-[ap-southeast-1].pooler.supabase.com:6543/postgres"
    result = _normalise(raw)
    assert "aws-0-ap-southeast-1.pooler.supabase.com" in result
    assert "[" not in result and "]" not in result


def test_bracketed_project_ref_in_user_is_repaired():
    raw = "postgresql://postgres.[PROJECT-REF]:pw@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
    result = _normalise(raw)
    assert "postgres.PROJECT-REF:" in result
    assert "[" not in result and "]" not in result


def test_real_ipv6_host_keeps_its_brackets():
    raw = "postgresql://user:pw@[::1]:5432/postgres"
    assert _normalise(raw) == raw


def test_postgres_scheme_is_upgraded():
    assert _normalise("postgres://u:p@host/db") == "postgresql://u:p@host/db"


def test_empty_url_stays_empty():
    assert _normalise("") == ""

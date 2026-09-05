"""Deterministic in-memory Supabase fake for contract tests.

The real client is `supabase-py`'s ``AsyncClient``; production code only ever
uses the narrow surface exercised here:

    client.table(name).select(cols).eq(col, val).in_(col, vals)
          .order(col, desc=...).limit(n).single()/.maybe_single().execute()
    client.table(name).insert(payload).select("*").single().execute()
    client.table(name).upsert(payload, on_conflict="a,b").execute()
    client.table(name).update(payload).eq(...).execute()
    client.table(name).delete().eq(...).execute()
    client.rpc(name, params).execute()

Rows live in a plain dict of lists, so tests assert against real data instead
of `AsyncMock` call chains (which silently pass regardless of query shape).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


class FakeDatabaseError(Exception):
    """Raised by the fake to simulate a PostgREST-level failure."""


@dataclass
class _Result:
    data: Any
    count: int | None = None


class _Query:
    def __init__(self, store: "FakeSupabase", table: str) -> None:
        self._store = store
        self._table = table
        self._rows: list[dict[str, Any]] = list(store.rows.get(table, []))
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._mode = "select"
        self._payload: Any = None
        self._on_conflict: list[str] = []
        self._single = False
        self._maybe_single = False
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None
        self._count_mode: str | None = None
        self._head = False
        self._or_filter: str | None = None
        self._columns = "*"

    # -- builder surface ---------------------------------------------------

    def select(self, columns: str = "*", **kwargs: Any) -> "_Query":
        self._columns = columns
        self._count_mode = kwargs.get("count")
        self._head = bool(kwargs.get("head"))
        return self

    def insert(self, payload: Any, **_: Any) -> "_Query":
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: Any, *, on_conflict: str = "", **_: Any) -> "_Query":
        self._mode = "upsert"
        self._payload = payload
        self._on_conflict = [part.strip() for part in on_conflict.split(",") if part.strip()]
        return self

    def update(self, payload: Any, **_: Any) -> "_Query":
        self._mode = "update"
        self._payload = payload
        return self

    def delete(self, **_: Any) -> "_Query":
        self._mode = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._filters.append(lambda row: row.get(column) == value)
        return self

    def neq(self, column: str, value: Any) -> "_Query":
        self._filters.append(lambda row: row.get(column) != value)
        return self

    def is_(self, column: str, value: Any) -> "_Query":
        if value is None or value == "null":
            self._filters.append(lambda row: row.get(column) is None)
        else:
            self._filters.append(lambda row: row.get(column) == value)
        return self

    def in_(self, column: str, values: Iterable[Any]) -> "_Query":
        allowed = list(values)
        self._filters.append(lambda row: row.get(column) in allowed)
        return self

    def lte(self, column: str, value: Any) -> "_Query":
        self._filters.append(
            lambda row: row.get(column) is not None and row.get(column) <= value
        )
        return self

    def gte(self, column: str, value: Any) -> "_Query":
        self._filters.append(
            lambda row: row.get(column) is not None and row.get(column) >= value
        )
        return self

    def lt(self, column: str, value: Any) -> "_Query":
        self._filters.append(
            lambda row: row.get(column) is not None and row.get(column) < value
        )
        return self

    def gt(self, column: str, value: Any) -> "_Query":
        self._filters.append(
            lambda row: row.get(column) is not None and row.get(column) > value
        )
        return self

    def ilike(self, column: str, pattern: str) -> "_Query":
        needle = pattern.strip("%").lower()

        def _check(row: dict[str, Any]) -> bool:
            value = row.get(column)
            return isinstance(value, str) and needle in value.lower()

        self._filters.append(_check)
        return self

    def or_(self, expression: str) -> "_Query":
        self._or_filter = expression
        return self

    def order(self, column: str, *, desc: bool = False, **_: Any) -> "_Query":
        self._order = (column, desc)
        return self

    def limit(self, count: int) -> "_Query":
        self._limit = count
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    def maybe_single(self) -> "_Query":
        self._maybe_single = True
        return self

    # -- execution ---------------------------------------------------------

    def _matching(self) -> list[dict[str, Any]]:
        rows = [row for row in self._rows if all(check(row) for check in self._filters)]
        if self._or_filter:
            rows = [row for row in rows if _matches_or(row, self._or_filter)]
        if self._order:
            column, desc = self._order
            rows = sorted(rows, key=lambda row: (row.get(column) is None, row.get(column)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    async def execute(self) -> _Result:
        self._store.calls.append((self._table, self._mode))
        failure = self._store.failures.get(self._table) or self._store.failures.get("*")
        if failure is not None:
            raise failure

        table_rows = self._store.rows.setdefault(self._table, [])

        if self._mode == "select":
            rows = self._matching()
            if self._count_mode:
                return _Result(data=[] if self._head else rows, count=len(rows))
            if self._single:
                if len(rows) != 1:
                    raise FakeDatabaseError("single() expected exactly one row")
                return _Result(data=rows[0])
            if self._maybe_single:
                return _Result(data=rows[0] if rows else None)
            return _Result(data=rows)

        if self._mode == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            created: list[dict[str, Any]] = []
            for payload in payloads:
                row = dict(payload)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", self._store.clock())
                _enforce_unique(self._store, self._table, row)
                table_rows.append(row)
                created.append(row)
            data: Any = created[0] if (self._single or self._maybe_single) else created
            return _Result(data=data)

        if self._mode == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            written: list[dict[str, Any]] = []
            for payload in payloads:
                key_columns = self._on_conflict or ["id"]
                existing = next(
                    (
                        row
                        for row in table_rows
                        if all(row.get(col) == payload.get(col) for col in key_columns)
                    ),
                    None,
                )
                if existing is not None:
                    existing.update(payload)
                    written.append(existing)
                else:
                    row = dict(payload)
                    row.setdefault("id", str(uuid.uuid4()))
                    row.setdefault("created_at", self._store.clock())
                    table_rows.append(row)
                    written.append(row)
            return _Result(data=written)

        if self._mode == "update":
            updated = []
            for row in self._matching():
                row.update(self._payload)
                updated.append(row)
            data = updated[0] if (self._single or self._maybe_single) and updated else updated
            return _Result(data=data)

        if self._mode == "delete":
            doomed = self._matching()
            for row in doomed:
                table_rows.remove(row)
            return _Result(data=doomed)

        raise AssertionError(f"unsupported mode {self._mode}")


def _matches_or(row: dict[str, Any], expression: str) -> bool:
    """Support the `col.ilike.%term%` OR syntax adminService.ts used."""
    for clause in expression.split(","):
        parts = clause.split(".", 2)
        if len(parts) != 3:
            continue
        column, operator, value = parts
        current = row.get(column)
        if current is None:
            continue
        if operator == "ilike" and value.strip("%").lower() in str(current).lower():
            return True
        if operator == "eq" and str(current) == value:
            return True
    return False


# Composite uniqueness the real schema enforces (migrate_to_v2.sql). The fake
# mirrors them so idempotency tests are meaningful.
_UNIQUE_KEYS: dict[str, list[list[str]]] = {
    "user_journey_tasks": [["user_id", "task_id"]],
    "user_vouchers": [["user_id", "voucher_id"]],
    "post_likes": [["post_id", "user_id"]],
}


def _enforce_unique(store: "FakeSupabase", table: str, row: dict[str, Any]) -> None:
    for key_columns in _UNIQUE_KEYS.get(table, []):
        if any(row.get(col) is None for col in key_columns):
            continue
        clash = any(
            all(existing.get(col) == row.get(col) for col in key_columns)
            for existing in store.rows.get(table, [])
        )
        if clash:
            error = FakeDatabaseError("duplicate key value violates unique constraint")
            error.code = "23505"  # type: ignore[attr-defined]
            raise error


@dataclass
class FakeSupabase:
    """A caller-scoped fake client backed by shared row storage."""

    rows: dict[str, list[dict[str, Any]]]
    rpc_results: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    rpc_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    auth_uid: str | None = None
    timestamp: str = "2026-08-06T00:00:00+00:00"

    def clock(self) -> str:
        return self.timestamp

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def from_(self, name: str) -> _Query:  # parity with supabase-py alias
        return _Query(self, name)

    def rpc(self, name: str, params: dict[str, Any] | None = None) -> "_Rpc":
        return _Rpc(self, name, params or {})


class _Rpc:
    def __init__(self, store: FakeSupabase, name: str, params: dict[str, Any]) -> None:
        self._store = store
        self._name = name
        self._params = params

    async def execute(self) -> _Result:
        self._store.rpc_calls.append((self._name, self._params))
        failure = self._store.failures.get(f"rpc:{self._name}") or self._store.failures.get("*")
        if failure is not None:
            raise failure
        handler = self._store.rpc_results.get(self._name)
        if callable(handler):
            return _Result(data=handler(self._params, self._store))
        return _Result(data=handler)

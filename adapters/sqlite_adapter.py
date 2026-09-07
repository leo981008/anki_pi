# adapters/sqlite_adapter.py
from __future__ import annotations
import sqlite3
from typing import Any, Callable
from adapters.schema import SCHEMA_SQL


class SqliteAdapter:
    """生產環境 SQLite 適配器：直接包裝現有連線邏輯，零 SQL 變更。"""

    def __init__(self, path: str = "flashcards.db", auto_init: bool = True):
        self.path = path
        if auto_init:
            self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.path, timeout=30.0)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def execute(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn:
                cursor = conn.execute(sql, params)
                return (
                    [dict(r) for r in cursor.fetchall()] if cursor.description else []
                )
        finally:
            conn.close()

    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.executemany(sql, params_list)
        finally:
            conn.close()

    def transaction(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """在同一連線執行多條 SQL，自動 commit/rollback。"""
        conn = self._connect()
        try:
            with conn:
                return fn(conn)
        finally:
            conn.close()

    def last_row_id(self) -> int:
        raise NotImplementedError("Use conn.lastrow_id inside transaction(fn)")

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_iso TEXT,
                    completed INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    external_provider TEXT,
                    external_id TEXT,
                    external_list_id TEXT,
                    created_at_iso TEXT NOT NULL,
                    updated_at_iso TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    start_iso TEXT NOT NULL,
                    end_iso TEXT NOT NULL,
                    location TEXT,
                    notes TEXT,
                    source TEXT,
                    external_provider TEXT,
                    external_id TEXT,
                    external_calendar_id TEXT,
                    created_at_iso TEXT NOT NULL,
                    updated_at_iso TEXT NOT NULL
                )
                """
            )

            self._migrate_tasks(conn)
            self._migrate_events(conn)

    def _migrate_tasks(self, conn: sqlite3.Connection) -> None:
        cols = conn.execute("PRAGMA table_info(tasks)").fetchall()
        existing = {r[1] for r in cols}

        if "external_provider" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN external_provider TEXT")
        if "external_id" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN external_id TEXT")
        if "external_list_id" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN external_list_id TEXT")

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_external ON tasks(external_provider, external_id)"
        )

    def _migrate_events(self, conn: sqlite3.Connection) -> None:
        cols = conn.execute("PRAGMA table_info(events)").fetchall()
        existing = {r[1] for r in cols}

        if "external_provider" not in existing:
            conn.execute("ALTER TABLE events ADD COLUMN external_provider TEXT")
        if "external_id" not in existing:
            conn.execute("ALTER TABLE events ADD COLUMN external_id TEXT")
        if "external_calendar_id" not in existing:
            conn.execute("ALTER TABLE events ADD COLUMN external_calendar_id TEXT")

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_external ON events(external_provider, external_id)"
        )

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, due_iso, completed, notes, external_provider, external_id, external_list_id, created_at_iso, updated_at_iso FROM tasks ORDER BY completed ASC, due_iso IS NULL, due_iso ASC, id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_events(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, start_iso, end_iso, location, notes, source, external_provider, external_id, external_calendar_id, created_at_iso, updated_at_iso FROM events ORDER BY start_iso ASC, id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def add_task(
        self,
        title: str,
        now_iso: str,
        due_iso: Optional[str] = None,
        notes: Optional[str] = None,
        external_provider: Optional[str] = None,
        external_id: Optional[str] = None,
        external_list_id: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (title, due_iso, completed, notes, external_provider, external_id, external_list_id, created_at_iso, updated_at_iso) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?)",
                (title, due_iso, notes, external_provider, external_id, external_list_id, now_iso, now_iso),
            )
            return int(cur.lastrowid)

    def upsert_external_task(
        self,
        external_provider: str,
        external_id: str,
        external_list_id: Optional[str],
        title: str,
        now_iso: str,
        due_iso: Optional[str] = None,
        completed: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            completed_int = None if completed is None else (1 if completed else 0)
            conn.execute(
                """
                INSERT INTO tasks (
                    title, due_iso, completed, notes,
                    external_provider, external_id, external_list_id,
                    created_at_iso, updated_at_iso
                ) VALUES (?, ?, COALESCE(?, 0), ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_provider, external_id)
                DO UPDATE SET
                    title = excluded.title,
                    due_iso = excluded.due_iso,
                    completed = excluded.completed,
                    notes = excluded.notes,
                    external_list_id = excluded.external_list_id,
                    updated_at_iso = excluded.updated_at_iso
                """,
                (
                    title,
                    due_iso,
                    completed_int,
                    notes,
                    external_provider,
                    external_id,
                    external_list_id,
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                "SELECT id FROM tasks WHERE external_provider = ? AND external_id = ?",
                (external_provider, external_id),
            ).fetchone()
            return int(row[0])

    def update_task(
        self,
        task_id: int,
        now_iso: str,
        title: Optional[str] = None,
        due_iso: Optional[str] = None,
        completed: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> None:
        fields: List[Tuple[str, Any]] = []
        if title is not None:
            fields.append(("title", title))
        if due_iso is not None:
            fields.append(("due_iso", due_iso))
        if completed is not None:
            fields.append(("completed", 1 if completed else 0))
        if notes is not None:
            fields.append(("notes", notes))

        if not fields:
            return

        set_sql = ", ".join([f"{k} = ?" for k, _ in fields] + ["updated_at_iso = ?"])
        params = [v for _, v in fields] + [now_iso, task_id]

        with self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {set_sql} WHERE id = ?", params)

    def delete_task(self, task_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def add_event(
        self,
        title: str,
        start_iso: str,
        end_iso: str,
        now_iso: str,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        source: Optional[str] = None,
        external_provider: Optional[str] = None,
        external_id: Optional[str] = None,
        external_calendar_id: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO events (title, start_iso, end_iso, location, notes, source, external_provider, external_id, external_calendar_id, created_at_iso, updated_at_iso) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    start_iso,
                    end_iso,
                    location,
                    notes,
                    source,
                    external_provider,
                    external_id,
                    external_calendar_id,
                    now_iso,
                    now_iso,
                ),
            )
            return int(cur.lastrowid)

    def upsert_external_event(
        self,
        external_provider: str,
        external_id: str,
        external_calendar_id: Optional[str],
        title: str,
        start_iso: str,
        end_iso: str,
        now_iso: str,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    title, start_iso, end_iso, location, notes, source,
                    external_provider, external_id, external_calendar_id,
                    created_at_iso, updated_at_iso
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_provider, external_id)
                DO UPDATE SET
                    title = excluded.title,
                    start_iso = excluded.start_iso,
                    end_iso = excluded.end_iso,
                    location = excluded.location,
                    notes = excluded.notes,
                    source = excluded.source,
                    external_calendar_id = excluded.external_calendar_id,
                    updated_at_iso = excluded.updated_at_iso
                """,
                (
                    title,
                    start_iso,
                    end_iso,
                    location,
                    notes,
                    source,
                    external_provider,
                    external_id,
                    external_calendar_id,
                    now_iso,
                    now_iso,
                ),
            )
            row = conn.execute(
                "SELECT id FROM events WHERE external_provider = ? AND external_id = ?",
                (external_provider, external_id),
            ).fetchone()
            return int(row[0])

    def update_event(
        self,
        event_id: int,
        now_iso: str,
        title: Optional[str] = None,
        start_iso: Optional[str] = None,
        end_iso: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        fields: List[Tuple[str, Any]] = []
        if title is not None:
            fields.append(("title", title))
        if start_iso is not None:
            fields.append(("start_iso", start_iso))
        if end_iso is not None:
            fields.append(("end_iso", end_iso))
        if location is not None:
            fields.append(("location", location))
        if notes is not None:
            fields.append(("notes", notes))

        if not fields:
            return

        set_sql = ", ".join([f"{k} = ?" for k, _ in fields] + ["updated_at_iso = ?"])
        params = [v for _, v in fields] + [now_iso, event_id]

        with self._connect() as conn:
            conn.execute(f"UPDATE events SET {set_sql} WHERE id = ?", params)

    def delete_event(self, event_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get_events_between(self, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, start_iso, end_iso, location, notes, source, created_at_iso, updated_at_iso FROM events WHERE start_iso >= ? AND start_iso < ? ORDER BY start_iso ASC",
                (start_iso, end_iso),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_tasks_due_between(self, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, title, due_iso, completed, notes, created_at_iso, updated_at_iso FROM tasks WHERE due_iso IS NOT NULL AND due_iso >= ? AND due_iso < ? ORDER BY due_iso ASC",
                (start_iso, end_iso),
            ).fetchall()
            return [dict(r) for r in rows]

"""SQLite access. One file, in the Home Assistant config directory (section 10).

Synchronous by design: volume is tiny and the calls are short. The Home
Assistant layer runs these in an executor. No Home Assistant imports here.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Sequence
from typing import Any

from .const import (
    OPEN_RUN_STATUSES,
    QUIRK_ACTIVE,
    QUIRK_RETRACTED,
    QUIRK_SUPERSEDED,
    RUN_ABANDONED,
    RUN_DONE,
    SCHEMA_VERSION,
    SUBJECT_ACTIVE,
    SUBJECT_REPLACED,
    SUBJECT_RETIRED,
)
from .models import Amendment, Procedure, Quirk, Run, RunEvent, Step, Subject
from .util import iso, normalise, short_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    make TEXT,
    model TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',
    attributes TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    replaced_by TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subjects_kind ON subjects (kind, status);

CREATE TABLE IF NOT EXISTS procedures (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT,
    subject_kind TEXT,
    yields TEXT,
    prep_notes TEXT,
    source TEXT NOT NULL DEFAULT 'generated',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_procedures_title ON procedures (title, subject_kind);

CREATE TABLE IF NOT EXISTS procedure_steps (
    procedure_id TEXT NOT NULL REFERENCES procedures (id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    speakable TEXT,
    ingredients TEXT NOT NULL DEFAULT '[]',
    duration_s INTEGER,
    awaits TEXT NOT NULL DEFAULT 'none',
    settings TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (procedure_id, n)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    procedure_id TEXT NOT NULL REFERENCES procedures (id) ON DELETE CASCADE,
    reference TEXT NOT NULL,
    subject_id TEXT REFERENCES subjects (id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    current_step INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    user_id TEXT,
    subject_loose INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_subject ON runs (subject_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS run_steps (
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    speakable TEXT,
    ingredients TEXT NOT NULL DEFAULT '[]',
    duration_s INTEGER,
    awaits TEXT NOT NULL DEFAULT 'none',
    settings TEXT NOT NULL DEFAULT '{}',
    source_n INTEGER,
    PRIMARY KEY (run_id, n)
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    step_n INTEGER,
    text TEXT,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events (run_id, id);

CREATE TABLE IF NOT EXISTS run_amendments (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    step_n INTEGER NOT NULL,
    was TEXT NOT NULL,
    now TEXT NOT NULL,
    why TEXT,
    scope TEXT NOT NULL DEFAULT 'run',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_amendments_run ON run_amendments (run_id, step_n);

CREATE TABLE IF NOT EXISTS quirks (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    claim TEXT NOT NULL,
    learned_from TEXT NOT NULL DEFAULT 'user',
    confidence TEXT NOT NULL DEFAULT 'medium',
    material INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    learned_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    last_stated_at TEXT,
    times_applied INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_quirks_subject ON quirks (subject_id, status);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    subject_id TEXT REFERENCES subjects (id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts (subject_id);
"""


class Store:
    """Everything Stepwise remembers, apart from long-lived facts."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # Lifecycle ---------------------------------------------------------
    def connect(self) -> Store:
        with self._lock:
            if self._conn is None:
                self._conn = sqlite3.connect(self.path, check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys=ON")
                self._migrate()
        return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    # Columns added after the first release. CREATE TABLE above covers new
    # databases; these bring an existing one up to the same shape.
    ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
        ("runs", "subject_loose", "INTEGER NOT NULL DEFAULT 0"),
        ("quirks", "last_stated_at", "TEXT"),
    )

    def _migrate(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.executescript(SCHEMA)
        for table, column, definition in self.ADDED_COLUMNS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    def schema_version(self) -> int:
        row = self._row("SELECT value FROM meta WHERE key = 'schema_version'")
        return int(row["value"]) if row else 0

    # Plumbing ----------------------------------------------------------
    def _write(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _rows(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def _row(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    @staticmethod
    def _upsert(table: str, row: dict[str, Any], key: str = "id") -> str:
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        updates = ", ".join(f"{name} = excluded.{name}" for name in row if name != key)
        return (
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT({key}) DO UPDATE SET {updates}"
        )

    # Subjects ----------------------------------------------------------
    def save_subject(self, subject: Subject) -> Subject:
        row = subject.to_row()
        self._write(self._upsert("subjects", row), row)
        return subject

    def get_subject(self, subject_id: str) -> Subject | None:
        row = self._row("SELECT * FROM subjects WHERE id = ?", (subject_id,))
        return Subject.from_row(row) if row else None

    def list_subjects(
        self, kind: str | None = None, include_retired: bool = False
    ) -> list[Subject]:
        sql = "SELECT * FROM subjects"
        clauses: list[str] = []
        params: list[Any] = []
        if not include_retired:
            clauses.append("status = ?")
            params.append(SUBJECT_ACTIVE)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_seen_at DESC"
        return [Subject.from_row(row) for row in self._rows(sql, params)]

    def touch_subject(self, subject_id: str, when: str | None = None) -> None:
        self._write(
            "UPDATE subjects SET last_seen_at = ? WHERE id = ?", (when or iso(), subject_id)
        )

    def retire_subject(self, subject_id: str, replaced_by: str | None = None) -> None:
        """Retired subjects stop matching but stay readable (section 7)."""
        self._write(
            "UPDATE subjects SET status = ?, replaced_by = ? WHERE id = ?",
            (SUBJECT_REPLACED if replaced_by else SUBJECT_RETIRED, replaced_by, subject_id),
        )

    def unique_subject_id(self, base: str) -> str:
        candidate, suffix = base, 2
        while self._row("SELECT 1 FROM subjects WHERE id = ?", (candidate,)):
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    # Procedures --------------------------------------------------------
    def save_procedure(self, procedure: Procedure) -> Procedure:
        row = procedure.to_row()
        row["updated_at"] = iso()
        with self._lock:
            self.conn.execute(self._upsert("procedures", row), row)
            self.conn.execute(
                "DELETE FROM procedure_steps WHERE procedure_id = ?", (procedure.id,)
            )
            for step in procedure.steps:
                step_row = step.to_row(procedure.id)
                columns = ", ".join(step_row)
                placeholders = ", ".join(f":{name}" for name in step_row)
                self.conn.execute(
                    f"INSERT INTO procedure_steps ({columns}) VALUES ({placeholders})", step_row
                )
            self.conn.commit()
        procedure.updated_at = row["updated_at"]
        return procedure

    def get_procedure(self, procedure_id: str) -> Procedure | None:
        row = self._row("SELECT * FROM procedures WHERE id = ?", (procedure_id,))
        if row is None:
            return None
        return Procedure.from_row(row, self.get_steps(procedure_id))

    def get_steps(self, procedure_id: str) -> list[Step]:
        return [
            Step.from_row(row)
            for row in self._rows(
                "SELECT * FROM procedure_steps WHERE procedure_id = ? ORDER BY n", (procedure_id,)
            )
        ]

    def save_step(self, procedure_id: str, step: Step) -> None:
        row = step.to_row(procedure_id)
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        updates = ", ".join(
            f"{name} = excluded.{name}" for name in row if name not in ("procedure_id", "n")
        )
        self._write(
            f"INSERT INTO procedure_steps ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(procedure_id, n) DO UPDATE SET {updates}",
            row,
        )

    def find_procedure(self, title: str, subject_kind: str | None = None) -> Procedure | None:
        """Deduplicated by title and subject kind (section 10)."""
        target = normalise(title)
        for row in self._rows("SELECT * FROM procedures ORDER BY updated_at DESC"):
            if normalise(row["title"]) != target:
                continue
            if subject_kind and row["subject_kind"] and row["subject_kind"] != subject_kind:
                continue
            return Procedure.from_row(row, self.get_steps(row["id"]))
        return None

    def list_procedures(self, subject_kind: str | None = None, limit: int = 50) -> list[Procedure]:
        sql = "SELECT * FROM procedures"
        params: list[Any] = []
        if subject_kind:
            sql += " WHERE subject_kind = ?"
            params.append(subject_kind)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [
            Procedure.from_row(row, self.get_steps(row["id"]))
            for row in self._rows(sql, params)
        ]

    # Runs --------------------------------------------------------------
    def save_run(self, run: Run) -> Run:
        row = run.to_row()
        self._write(self._upsert("runs", row), row)
        return run

    def get_run(self, run_id: str) -> Run | None:
        row = self._row("SELECT * FROM runs WHERE id = ?", (run_id,))
        return Run.from_row(row) if row else None

    def open_runs(self, user_id: str | None = None, subject_id: str | None = None) -> list[Run]:
        """Every live run, most recently touched first. Several may be live."""
        placeholders = ", ".join("?" for _ in OPEN_RUN_STATUSES)
        sql = f"SELECT * FROM runs WHERE status IN ({placeholders})"
        params: list[Any] = list(OPEN_RUN_STATUSES)
        if user_id:
            sql += " AND (user_id IS NULL OR user_id = ?)"
            params.append(user_id)
        if subject_id:
            sql += " AND subject_id = ?"
            params.append(subject_id)
        sql += " ORDER BY updated_at DESC"
        return [Run.from_row(row) for row in self._rows(sql, params)]

    def recent_runs(self, subject_id: str | None = None, limit: int = 10) -> list[Run]:
        sql = "SELECT * FROM runs"
        params: list[Any] = []
        if subject_id:
            sql += " WHERE subject_id = ?"
            params.append(subject_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return [Run.from_row(row) for row in self._rows(sql, params)]

    def touch_run(self, run_id: str, when: str | None = None) -> None:
        """Any contact resets the clock (section 6, rolling not fixed)."""
        self._write("UPDATE runs SET updated_at = ? WHERE id = ?", (when or iso(), run_id))

    # Run steps ---------------------------------------------------------
    # A run owns its steps. Amending one changes this run, never the template
    # somebody else might be following (section 9, amendments are scoped).
    def save_run_steps(self, run_id: str, steps: Sequence[Step]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM run_steps WHERE run_id = ?", (run_id,))
            for step in steps:
                row = step.to_row("")
                row.pop("procedure_id", None)
                row["run_id"] = run_id
                row.setdefault("source_n", step.n)
                columns = ", ".join(row)
                placeholders = ", ".join(f":{name}" for name in row)
                self.conn.execute(
                    f"INSERT INTO run_steps ({columns}) VALUES ({placeholders})", row
                )
            self.conn.commit()

    def save_run_step(self, run_id: str, step: Step, source_n: int | None = None) -> None:
        row = step.to_row("")
        row.pop("procedure_id", None)
        row["run_id"] = run_id
        row["source_n"] = source_n if source_n is not None else step.n
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        updates = ", ".join(
            f"{name} = excluded.{name}" for name in row if name not in ("run_id", "n")
        )
        self._write(
            f"INSERT INTO run_steps ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(run_id, n) DO UPDATE SET {updates}",
            row,
        )

    def get_run_steps(self, run_id: str) -> list[Step]:
        return [
            Step.from_row(row)
            for row in self._rows(
                "SELECT * FROM run_steps WHERE run_id = ? ORDER BY n", (run_id,)
            )
        ]

    def run_step_sources(self, run_id: str) -> dict[int, int | None]:
        """Which template step each run step came from, after any reordering."""
        return {
            row["n"]: row["source_n"]
            for row in self._rows(
                "SELECT n, source_n FROM run_steps WHERE run_id = ? ORDER BY n", (run_id,)
            )
        }

    # Events ------------------------------------------------------------
    def add_event(self, event: RunEvent) -> RunEvent:
        row = event.to_row()
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        cur = self._write(f"INSERT INTO run_events ({columns}) VALUES ({placeholders})", row)
        event.id = cur.lastrowid
        return event

    def events(self, run_id: str, kinds: Iterable[str] | None = None) -> list[RunEvent]:
        sql = "SELECT * FROM run_events WHERE run_id = ?"
        params: list[Any] = [run_id]
        kinds = list(kinds or [])
        if kinds:
            sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
            params.extend(kinds)
        sql += " ORDER BY id"
        return [RunEvent.from_row(row) for row in self._rows(sql, params)]

    def last_event(self, run_id: str, kinds: Iterable[str] | None = None) -> RunEvent | None:
        found = self.events(run_id, kinds)
        return found[-1] if found else None

    # Amendments --------------------------------------------------------
    def add_amendment(self, amendment: Amendment) -> Amendment:
        row = amendment.to_row()
        self._write(self._upsert("run_amendments", row), row)
        return amendment

    def amendments(self, run_id: str) -> list[Amendment]:
        return [
            Amendment.from_row(row)
            for row in self._rows(
                "SELECT * FROM run_amendments WHERE run_id = ? ORDER BY at", (run_id,)
            )
        ]

    # Quirks ------------------------------------------------------------
    def add_quirk(self, quirk: Quirk, supersedes: str | None = None) -> Quirk:
        """Quirks supersede on the same subject rather than appending."""
        if supersedes is None:
            target = normalise(quirk.claim)
            for existing in self.quirks(quirk.subject_id):
                if normalise(existing.claim) == target:
                    supersedes = existing.id
                    break
        if supersedes:
            self._write(
                "UPDATE quirks SET status = ?, superseded_by = ? WHERE id = ?",
                (QUIRK_SUPERSEDED, quirk.id, supersedes),
            )
        row = quirk.to_row()
        self._write(self._upsert("quirks", row), row)
        return quirk

    def quirks(self, subject_id: str, include_inactive: bool = False) -> list[Quirk]:
        sql = "SELECT * FROM quirks WHERE subject_id = ?"
        params: list[Any] = [subject_id]
        if not include_inactive:
            sql += " AND status = ?"
            params.append(QUIRK_ACTIVE)
        sql += " ORDER BY learned_at"
        return [Quirk.from_row(row) for row in self._rows(sql, params)]

    def get_quirk(self, quirk_id: str) -> Quirk | None:
        row = self._row("SELECT * FROM quirks WHERE id = ?", (quirk_id,))
        return Quirk.from_row(row) if row else None

    def confirm_quirk(self, quirk_id: str, when: str | None = None) -> None:
        self._write(
            "UPDATE quirks SET last_confirmed_at = ? WHERE id = ?", (when or iso(), quirk_id)
        )

    def retract_quirk(self, quirk_id: str) -> None:
        self._write("UPDATE quirks SET status = ? WHERE id = ?", (QUIRK_RETRACTED, quirk_id))

    def quirk_stated(self, quirk_id: str, when: str | None = None) -> None:
        """Counted and dated, but not confirmed.

        Stating a quirk is the system talking. Only the person can confirm one,
        which is why this never touches last_confirmed_at: otherwise a quirk
        confirms itself the first time it is spoken and then asserts itself
        forever, which is exactly what section 9 rule 2 exists to prevent.
        """
        self._write(
            "UPDATE quirks SET times_applied = times_applied + 1, last_stated_at = ? "
            "WHERE id = ?",
            (when or iso(), quirk_id),
        )

    # Facts ---------------------------------------------------------------
    # Only for the built-in memory backend. Long-lived facts belong in a memory
    # integration; this is here for people who do not want a second one.
    def add_fact(self, text: str, subject_id: str | None = None, source: str = "user") -> str:
        existing = self.facts(subject_id)
        target = normalise(text)
        for fact in existing:
            if normalise(fact["text"]) == target:
                return str(fact["id"])
        fact_id = short_id("fct")
        self._write(
            "INSERT INTO facts (id, subject_id, text, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (fact_id, subject_id, text, source, iso()),
        )
        return fact_id

    def facts(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        if subject_id:
            rows = self._rows(
                "SELECT * FROM facts WHERE subject_id = ? ORDER BY created_at", (subject_id,)
            )
        else:
            rows = self._rows("SELECT * FROM facts ORDER BY created_at")
        return [dict(row) for row in rows]

    def forget_fact(self, fact_id: str) -> None:
        self._write("DELETE FROM facts WHERE id = ?", (fact_id,))

    # Housekeeping ------------------------------------------------------
    def prune_runs(self, keep_per_subject: int) -> int:
        """Bounded by construction: keep the last N closed runs per subject."""
        if keep_per_subject <= 0:
            return 0
        closed = self._rows(
            "SELECT id, subject_id FROM runs WHERE status IN (?, ?) ORDER BY updated_at DESC",
            (RUN_DONE, RUN_ABANDONED),
        )
        seen: dict[str | None, int] = {}
        doomed: list[str] = []
        for row in closed:
            key = row["subject_id"]
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > keep_per_subject:
                doomed.append(row["id"])
        for run_id in doomed:
            self._write("DELETE FROM runs WHERE id = ?", (run_id,))
        return len(doomed)

    def stats(self) -> dict[str, int]:
        counts = {}
        for table in (
            "subjects",
            "procedures",
            "runs",
            "run_steps",
            "run_events",
            "run_amendments",
            "quirks",
            "facts",
        ):
            row = self._row(f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = int(row["n"]) if row else 0
        return counts

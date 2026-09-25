"""SQLite storage for gold candidates, silver labels and reviews.

Silver labels and reviews are append-only: triggers reject updates and deletes,
so provenance is never lost. The latest review of a NOTAM is its current one,
and the latest label from each named run (A or B) is that run's current label.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from notam_gold.paths import DATABASE

SCHEMA = """
CREATE TABLE IF NOT EXISTS notam (
    id TEXT PRIMARY KEY,
    notam_id TEXT NOT NULL,
    icao_location TEXT NOT NULL,
    effective_start TEXT,
    effective_end TEXT,
    notam_text TEXT NOT NULL,
    nms_type TEXT,
    source TEXT NOT NULL,
    strata TEXT NOT NULL,
    selected_stratum TEXT NOT NULL,
    selection_rank INTEGER NOT NULL,
    selection_seed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS label_run (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    batch_id TEXT,
    notam_keys TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS silver_label (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES label_run(id),
    notam_key TEXT NOT NULL REFERENCES notam(id),
    extraction TEXT,
    evidence TEXT NOT NULL,
    note TEXT,
    problems TEXT NOT NULL,
    response TEXT NOT NULL,
    usage TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, notam_key)
);

CREATE TRIGGER IF NOT EXISTS silver_label_no_update BEFORE UPDATE ON silver_label
BEGIN SELECT RAISE(ABORT, 'silver labels are immutable'); END;
CREATE TRIGGER IF NOT EXISTS silver_label_no_delete BEFORE DELETE ON silver_label
BEGIN SELECT RAISE(ABORT, 'silver labels are immutable'); END;

CREATE VIEW IF NOT EXISTS latest_silver AS
SELECT silver_label.*, label_run.name AS run_name, label_run.model, label_run.prompt_version
FROM silver_label JOIN label_run ON label_run.id = silver_label.run_id
WHERE silver_label.id IN (
    SELECT MAX(label.id) FROM silver_label AS label JOIN label_run AS run ON run.id = label.run_id
    GROUP BY label.notam_key, run.name
);

CREATE TABLE IF NOT EXISTS disagreement (
    notam_key TEXT PRIMARY KEY REFERENCES notam(id),
    label_a_id INTEGER NOT NULL REFERENCES silver_label(id),
    label_b_id INTEGER NOT NULL REFERENCES silver_label(id),
    paths TEXT NOT NULL,
    score INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS review (
    id INTEGER PRIMARY KEY,
    notam_key TEXT NOT NULL REFERENCES notam(id),
    silver_label_id INTEGER REFERENCES silver_label(id),
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'edited', 'ambiguous', 'skipped')),
    extraction TEXT,
    note TEXT,
    edited INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS review_notam ON review (notam_key, id);

CREATE TRIGGER IF NOT EXISTS review_no_update BEFORE UPDATE ON review
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS review_no_delete BEFORE DELETE ON review
BEGIN SELECT RAISE(ABORT, 'reviews are append-only'); END;

CREATE VIEW IF NOT EXISTS current_review AS
SELECT * FROM review WHERE id IN (SELECT MAX(id) FROM review GROUP BY notam_key);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path = DATABASE) -> sqlite3.Connection:
    """Open (creating if needed) the gold database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(SCHEMA)
    return connection


def dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def loads(value: str | None):
    return None if value is None else json.loads(value)

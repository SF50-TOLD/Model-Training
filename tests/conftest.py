import pytest

from notam_gold import db
from notam_gold.disagreement import diff, score


class GoldDatabase:
    """A temporary gold database with helpers for the rows a pipeline stage leaves behind."""

    def __init__(self, path):
        self.path = path
        self.connection = db.connect(path)
        self.run_ids = {
            name: self._add_run(name, model) for name, model in (("A", "claude-opus-5-5"), ("B", "claude-opus-5"))
        }
        self.run_id = self.run_ids["A"]

    def _add_run(self, name, model):
        return self.connection.execute(
            "INSERT INTO label_run (name, model, prompt_version, schema_version, batch_id, notam_keys, created_at)"
            " VALUES (?, ?, 'abc123', '1.0.0', 'batch', '[]', ?)",
            (name, model, db.now()),
        ).lastrowid

    def add_notam(self, notam_id, location="KSFO", text="RWY 28L CLSD", nms_type="N", stratum="full_closure", rank=0):
        key = f"{location} {notam_id}"
        self.connection.execute(
            "INSERT INTO notam VALUES (?, ?, ?, '2026-09-01T00:00:00.000Z', NULL, ?, ?, '2026-09', ?, ?, ?, 1)",
            (key, notam_id, location, text, nms_type, db.dumps([stratum]), stratum, rank),
        )
        return key

    def add_silver(self, key, extraction, run="A", evidence=(), note=None):
        return self.connection.execute(
            "INSERT INTO silver_label (run_id, notam_key, extraction, evidence, note, problems, response, usage,"
            " created_at) VALUES (?, ?, ?, ?, ?, '[]', '{}', '{}', ?)",
            (self.run_ids[run], key, db.dumps(extraction), db.dumps(list(evidence)), note, db.now()),
        ).lastrowid

    def add_disagreement(self, key, label_a, label_b, a, b):
        differences = diff(a, b)
        self.connection.execute(
            "INSERT INTO disagreement VALUES (?, ?, ?, ?, ?)",
            (key, label_a, label_b, db.dumps([d.to_dict() for d in differences]), score(differences)),
        )

    def add_review(self, key, status, extraction, silver_id=None, edited=False):
        self.connection.execute(
            "INSERT INTO review (notam_key, silver_label_id, reviewer, reviewed_at, status, extraction, note, edited)"
            " VALUES (?, ?, 'Tester', ?, ?, ?, NULL, ?)",
            (key, silver_id, db.now(), status, db.dumps(extraction), int(edited)),
        )

    def reviews(self, key) -> list[dict]:
        """Every review of ``key``, oldest first, with JSON columns decoded."""
        rows = self.connection.execute("SELECT * FROM review WHERE notam_key = ? ORDER BY id", (key,)).fetchall()
        return [dict(row) | {"extraction": db.loads(row["extraction"])} for row in rows]


@pytest.fixture
def gold_db(tmp_path):
    return GoldDatabase(tmp_path / "gold.sqlite")

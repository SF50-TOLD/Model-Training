import pytest

from notam_gold import db


class GoldDatabase:
    """A temporary gold database with helpers for the rows a pipeline stage leaves behind."""

    def __init__(self, path):
        self.path = path
        self.connection = db.connect(path)
        self.run_id = self.connection.execute(
            "INSERT INTO label_run (name, model, prompt_version, schema_version, batch_id, notam_keys, created_at)"
            " VALUES ('A', 'claude-opus-5-5', 'abc123', '1.0.0', 'batch', '[]', ?)",
            (db.now(),),
        ).lastrowid

    def add_notam(self, notam_id, location="KSFO", text="RWY 28L CLSD", nms_type="N", stratum="full_closure"):
        key = f"{location} {notam_id}"
        self.connection.execute(
            "INSERT INTO notam VALUES (?, ?, ?, '2026-09-01T00:00:00.000Z', NULL, ?, ?, '2026-09', ?, ?, 0, 1)",
            (key, notam_id, location, text, nms_type, db.dumps([stratum]), stratum),
        )
        return key

    def add_silver(self, key, extraction):
        return self.connection.execute(
            "INSERT INTO silver_label (run_id, notam_key, extraction, evidence, note, problems, response, usage,"
            " created_at) VALUES (?, ?, ?, '[]', NULL, '[]', '{}', '{}', ?)",
            (self.run_id, key, db.dumps(extraction), db.now()),
        ).lastrowid

    def add_review(self, key, status, extraction, silver_id=None, edited=False):
        self.connection.execute(
            "INSERT INTO review (notam_key, silver_label_id, reviewer, reviewed_at, status, extraction, note, edited)"
            " VALUES (?, ?, 'Tester', ?, ?, ?, NULL, ?)",
            (key, silver_id, db.now(), status, db.dumps(extraction), int(edited)),
        )


@pytest.fixture
def gold_db(tmp_path):
    return GoldDatabase(tmp_path / "gold.sqlite")

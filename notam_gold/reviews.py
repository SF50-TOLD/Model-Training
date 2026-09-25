"""Which saved reviews the labelling rules have since overtaken."""

import sqlite3

from notam_gold import db
from notam_gold.disagreement import Difference, diff

STALE_SQL = """
SELECT review.notam_key, review.extraction AS reviewed, silver.extraction AS silver
FROM current_review AS review
JOIN silver_label AS silver ON silver.id = (
    SELECT MAX(latest.id) FROM silver_label AS latest
    JOIN label_run ON label_run.id = latest.run_id
    WHERE latest.notam_key = review.notam_key AND label_run.name = 'A'
)
WHERE review.status != 'skipped' AND silver.created_at > review.reviewed_at AND silver.extraction IS NOT NULL
"""


def stale_reviews(connection: sqlite3.Connection) -> dict[str, list[Difference]]:
    """Reviews saved before their newest run-A silver label and differing from it, keyed by NOTAM.

    Each maps to how the saved label differs from the relabelled silver one. A review whose
    label matches the new silver label already follows the current rules and is not stale.
    """
    stale = {}
    for row in connection.execute(STALE_SQL):
        reviewed, silver = db.loads(row["reviewed"]), db.loads(row["silver"])
        differences = diff(reviewed, silver) if reviewed is not None else [Difference("", None, silver)]
        if differences:
            stale[row["notam_key"]] = differences
    return stale

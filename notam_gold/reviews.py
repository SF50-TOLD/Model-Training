"""Which saved reviews the labelling rules have since overtaken."""

import sqlite3

from notam_gold import db
from notam_gold.db import UNREVIEWED_REVIEWER_PREFIX
from notam_gold.disagreement import Difference, diff
from notam_gold.migrate import current

__all__ = ["UNREVIEWED_REVIEWER_PREFIX", "stale_reviews"]

STALE_SQL = """
SELECT review.notam_key, review.extraction AS reviewed, silver.extraction AS silver, notam.notam_text
FROM current_review AS review
JOIN latest_silver AS silver ON silver.notam_key = review.notam_key AND silver.run_name = 'A'
JOIN notam ON notam.id = review.notam_key
WHERE review.status != 'skipped' AND silver.created_at > review.reviewed_at AND silver.extraction IS NOT NULL
"""


def stale_reviews(connection: sqlite3.Connection) -> dict[str, list[Difference]]:
    """Reviews saved before their newest run-A silver label and differing from it, keyed by NOTAM.

    Each maps to how the saved label differs from the relabelled silver one. A review whose
    label matches the new silver label already follows the current rules and is not stale.
    """
    stale = {}
    for row in connection.execute(STALE_SQL):
        reviewed, silver = (current(db.loads(row[k]), row["notam_text"]) for k in ("reviewed", "silver"))
        differences = diff(reviewed, silver) if reviewed is not None else [Difference("", None, silver)]
        if differences:
            stale[row["notam_key"]] = differences
    return stale

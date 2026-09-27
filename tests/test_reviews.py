import pytest

from notam_gold.reviews import stale_reviews
from tests.factories import effect, extraction, length

OLD_RULES = extraction(effect("06", thresholdDisplacement=length(300)))
NEW_RULES = extraction(effect("06", "full", thresholdDisplacement=length(300)))

BEFORE, REVIEWED, AFTER = "2026-09-24T20:00:00+00:00", "2026-09-24T21:00:00+00:00", "2026-09-25T09:00:00+00:00"


@pytest.fixture
def relabelled(gold_db):
    """A NOTAM reviewed against an old silver label, then relabelled under new rules."""
    key = gold_db.add_notam("A1/2026")
    gold_db.add_silver(key, OLD_RULES, created_at=BEFORE)
    return key


def test_a_review_the_relabel_disagrees_with_is_stale(gold_db, relabelled):
    gold_db.add_review(relabelled, "accepted", OLD_RULES, reviewed_at=REVIEWED)
    gold_db.add_silver(relabelled, NEW_RULES, created_at=AFTER)
    [difference] = stale_reviews(gold_db.connection)[relabelled]
    assert (difference.path, difference.a, difference.b) == ("effects[0].closure", "none", "full")


@pytest.mark.parametrize(
    ("status", "saved", "reviewed_at"),
    [
        ("edited", NEW_RULES, REVIEWED),  # the reviewer already applied the new rules
        ("accepted", OLD_RULES, "2026-09-25T10:00:00+00:00"),  # reviewed after the relabel
        ("skipped", OLD_RULES, REVIEWED),
    ],
)
def test_reviews_the_relabel_does_not_overtake_are_current(gold_db, relabelled, status, saved, reviewed_at):
    gold_db.add_review(relabelled, status, saved, reviewed_at=reviewed_at)
    gold_db.add_silver(relabelled, NEW_RULES, created_at=AFTER)
    assert stale_reviews(gold_db.connection) == {}

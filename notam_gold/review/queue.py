"""The order the review queue presents NOTAMs in."""

from collections import Counter

from notam_gold.strata import ALL_STRATA

STRATUM_ORDER = {stratum: position for position, stratum in enumerate(ALL_STRATA)}
GOLD_STATUSES = ("accepted", "edited")


def _group(item: dict) -> int:
    """Re-reviews first, then unreviewed NOTAMs, then everything already decided."""
    return {"stale": 0, "unreviewed": 1}.get(item["status"], 2)


def review_order(items: list[dict]) -> list[dict]:
    """Queue ``items`` (given in selection order) so the thinnest strata fill first.

    Each unreviewed NOTAM's turn is the number of gold labels its stratum already has in its
    half, plus its place among that stratum's unreviewed NOTAMs. Review therefore goes to
    whichever half-and-stratum has the fewest labels, one NOTAM at a time, instead of
    exhausting the largest stratum first. Within a stratum, the NOTAMs the two silver runs
    disagree on most come first.
    """
    gold = Counter((item["half"], item["stratum"]) for item in items if item["status"] in GOLD_STATUSES)
    by_priority = sorted(items, key=lambda item: (_group(item), -item["score"]))
    turn: dict[str, int] = {}
    taken = Counter()
    for item in by_priority:
        if _group(item) == 1:
            lane = (item["half"], item["stratum"])
            turn[item["key"]] = gold[lane] + taken[lane]
            taken[lane] += 1
    return sorted(
        by_priority,
        key=lambda item: (
            _group(item),
            turn.get(item["key"], 0),
            STRATUM_ORDER[item["stratum"]] if item["key"] in turn else 0,
            item["half"] if item["key"] in turn else "",
        ),
    )

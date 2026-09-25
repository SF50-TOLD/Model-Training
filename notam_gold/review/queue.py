"""The order the review queue presents NOTAMs in."""

from collections import Counter

from notam_gold.strata import ALL_STRATA

STRATUM_ORDER = {stratum: position for position, stratum in enumerate(ALL_STRATA)}


def _group(item: dict) -> int:
    """Re-reviews first, then the unreviewed dev half, then the unreviewed test half, then the rest."""
    if item["status"] == "stale":
        return 0
    if item["status"] == "unreviewed":
        return 1 if item["half"] == "dev" else 2
    return 3


def review_order(items: list[dict]) -> list[dict]:
    """Queue ``items`` (given in selection order) so each half fills every stratum evenly.

    Unreviewed NOTAMs are interleaved one stratum at a time, so review covers every stratum
    early instead of exhausting the largest first; within a stratum, the NOTAMs the two silver
    runs disagree on most come first. The dev half comes before the test half because
    instruction tuning needs it first.
    """
    by_priority = sorted(items, key=lambda item: (_group(item), -item["score"]))
    turn: dict[str, int] = {}
    taken = Counter()
    for item in by_priority:
        if _group(item) in (1, 2):
            lane = (_group(item), item["stratum"])
            turn[item["key"]] = taken[lane]
            taken[lane] += 1
    return sorted(
        by_priority,
        key=lambda item: (
            _group(item),
            turn.get(item["key"], 0),
            STRATUM_ORDER[item["stratum"]] if item["key"] in turn else 0,
        ),
    )

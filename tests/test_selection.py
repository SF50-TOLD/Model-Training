from collections import Counter

import pytest

from notam_gold import strata as s
from notam_gold.selection import Candidate, SelectionConfig, select, stratum_counts


def candidate(index, *strata, airport=None, template=None):
    return Candidate(
        id=f"N{index:05}",
        icao_location=airport or f"K{index % 40:03}",
        strata=strata,
        template=("X", template or f"T{index}"),
    )


@pytest.fixture
def corpus():
    pools = {
        s.DECLARED_DISTANCES: 30,
        s.DISPLACED_THRESHOLD: 10,
        s.FICON_RWYCC: 200,
        s.FICON_NO_RWYCC: 50,
        s.PARTIAL_CLOSURE: 45,
        s.FULL_CLOSURE: 100,
        s.OBSTACLE: 80,
        s.CANCELLED: 300,
        s.PLAUSIBLE_NEGATIVE: 500,
        s.OTHER_NEGATIVE: 2000,
    }
    index = 0
    candidates = []
    for stratum, count in pools.items():
        for _ in range(count):
            candidates.append(candidate(index, stratum))
            index += 1
    return candidates


def test_selection_is_reproducible(corpus):
    config = SelectionConfig(seed=7)
    assert select(corpus, config) == select(list(reversed(corpus)), config)
    assert select(corpus, config) != select(corpus, SelectionConfig(seed=8))


def test_takes_every_numeric_candidate_and_fills_quotas(corpus):
    counts = stratum_counts(select(corpus, SelectionConfig()))
    assert counts[s.DECLARED_DISTANCES] == 30
    assert counts[s.DISPLACED_THRESHOLD] == 10
    assert counts[s.FICON_RWYCC] == 60
    assert counts[s.PARTIAL_CLOSURE] == 40


def test_caps_numeric_candidates_keeping_displaced_thresholds(corpus):
    counts = stratum_counts(select(corpus, SelectionConfig(numeric_cap=25)))
    assert counts[s.DISPLACED_THRESHOLD] == 10
    assert counts[s.DECLARED_DISTANCES] == 15


def test_at_least_a_quarter_negatives_mostly_plausible(corpus):
    counts = stratum_counts(select(corpus, SelectionConfig()))
    negatives = counts[s.PLAUSIBLE_NEGATIVE] + counts[s.OTHER_NEGATIVE]
    assert negatives / sum(counts.values()) >= 0.25
    assert counts[s.PLAUSIBLE_NEGATIVE] > counts[s.OTHER_NEGATIVE]


def test_cancelled_numeric_notams_count_as_cancelled():
    corpus = [candidate(0, s.DECLARED_DISTANCES, s.CANCELLED), candidate(1, s.DECLARED_DISTANCES)]
    selected = {c.id: stratum for c, stratum in select(corpus, SelectionConfig())}
    assert selected == {"N00000": s.CANCELLED, "N00001": s.DECLARED_DISTANCES}


def test_collapses_reissues_and_spreads_airports():
    corpus = [candidate(i, s.FICON_RWYCC, airport="PAFA", template="same") for i in range(20)]
    corpus += [candidate(100 + i, s.FICON_RWYCC, airport="PAFA") for i in range(10)]
    corpus += [candidate(200 + i, s.FICON_RWYCC, airport=f"K{i:03}") for i in range(10)]
    chosen = [c for c, _ in select(corpus, SelectionConfig(quotas={s.FICON_RWYCC: 12}, per_airport=3))]
    assert sum(c.template == ("X", "same") for c in chosen) <= 1
    assert Counter(c.icao_location for c in chosen)["PAFA"] <= 3

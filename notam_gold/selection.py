"""Seeded, stratified selection of gold candidates from the tagged corpus."""

import math
import random
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from notam_gold import strata as s

NUMERIC_STRATA = (s.DECLARED_DISTANCES, s.DISPLACED_THRESHOLD)
PRIMARY_PRIORITY = (s.CANCELLED, *s.POSITIVE_STRATA, s.PLAUSIBLE_NEGATIVE, s.OTHER_NEGATIVE)

DEFAULT_QUOTAS = {
    s.FICON_RWYCC: 60,
    s.FICON_NO_RWYCC: 30,
    s.PARTIAL_CLOSURE: 40,
    s.FULL_CLOSURE: 40,
    s.OBSTACLE: 50,
    s.CANCELLED: 40,
}


@dataclass(frozen=True)
class Candidate:
    """A tagged corpus NOTAM eligible for selection."""

    id: str
    icao_location: str
    strata: tuple[str, ...]
    template: tuple[str, str]

    @property
    def primary(self) -> str:
        return next(stratum for stratum in PRIMARY_PRIORITY if stratum in self.strata)


@dataclass
class SelectionConfig:
    seed: int = 2026
    numeric_cap: int = 150
    quotas: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_QUOTAS))
    negative_share: float = 0.25
    plausible_share: float = 0.7
    per_airport: int = 3


def collapse_reissues(candidates: Iterable[Candidate], rng: random.Random) -> list[Candidate]:
    """One representative per reissued-NOTAM template, chosen at random."""
    groups: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda c: c.id):
        groups.setdefault(candidate.template, []).append(candidate)
    return [rng.choice(group) for _, group in sorted(groups.items())]


def sample(pool: list[Candidate], count: int, per_airport: int, rng: random.Random) -> list[Candidate]:
    """``count`` candidates, preferring airport diversity, relaxing the airport cap if the pool runs short."""
    shuffled = sorted(pool, key=lambda c: c.id)
    rng.shuffle(shuffled)
    chosen, per = [], Counter()
    for candidate in shuffled:
        if len(chosen) < count and per[candidate.icao_location] < per_airport:
            chosen.append(candidate)
            per[candidate.icao_location] += 1
    taken = set(chosen)
    remaining = [c for c in shuffled if c not in taken]
    return chosen + remaining[: count - len(chosen)]


def _numeric_stratum(candidate: Candidate) -> str:
    return s.DISPLACED_THRESHOLD if s.DISPLACED_THRESHOLD in candidate.strata else s.DECLARED_DISTANCES


def _numeric(by_primary: dict[str, list[Candidate]], config: SelectionConfig, rng: random.Random) -> list[Candidate]:
    """Every numeric-stratum candidate up to the cap; displaced thresholds (the rarer) are taken first."""
    pool = [c for stratum in NUMERIC_STRATA for c in by_primary.get(stratum, [])]
    displaced = [c for c in pool if _numeric_stratum(c) == s.DISPLACED_THRESHOLD]
    declared = [c for c in pool if _numeric_stratum(c) == s.DECLARED_DISTANCES]
    chosen = sample(displaced, config.numeric_cap, config.per_airport, rng)
    chosen += sample(declared, config.numeric_cap - len(chosen), config.per_airport, rng)
    return sorted(chosen, key=lambda c: c.id)


def select(candidates: Iterable[Candidate], config: SelectionConfig) -> list[tuple[Candidate, str]]:
    """Gold candidates with the stratum each was selected for, in selection order."""
    rng = random.Random(config.seed)
    by_primary: dict[str, list[Candidate]] = {}
    for candidate in collapse_reissues(candidates, rng):
        by_primary.setdefault(candidate.primary, []).append(candidate)

    selected = [(c, _numeric_stratum(c)) for c in _numeric(by_primary, config, rng)]

    for stratum, quota in config.quotas.items():
        selected += [(c, stratum) for c in sample(by_primary.get(stratum, []), quota, config.per_airport, rng)]

    negatives = math.ceil(len(selected) * config.negative_share / (1 - config.negative_share))
    plausible = round(negatives * config.plausible_share)
    for stratum, count in ((s.PLAUSIBLE_NEGATIVE, plausible), (s.OTHER_NEGATIVE, negatives - plausible)):
        selected += [(c, stratum) for c in sample(by_primary.get(stratum, []), count, config.per_airport, rng)]
    return selected


def stratum_counts(selected: Iterable[tuple[Candidate, str]]) -> dict[str, int]:
    counts = Counter(stratum for _, stratum in selected)
    return {stratum: counts[stratum] for stratum in s.ALL_STRATA if counts[stratum]}

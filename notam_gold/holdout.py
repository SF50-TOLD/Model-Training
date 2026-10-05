"""Candidates for the held-out test set: NOTAMs that no model has trained or been tuned on.

They come from two places:

- the NOTAMs ``download_notams.py --holdout`` collects, which are newer than the corpus;
- the dataset published with "A semi-supervised approach to multi-label classification of NOTAMs
  using BERT" (Zenodo record 17208970, CC BY 4.0), mostly ICAO NOTAMs from 2018.

A NOTAM sharing a reissue template with the corpus is never a candidate, because training and the
gold set are drawn from the corpus. Zenodo NOTAMs are rewritten into the text the NOTAM API serves:
an ICAO NOTAM's E) item (a cancellation keeps its whole message), or an FAA domestic NOTAM without
its accountability header and validity times.
"""

import random
from collections.abc import Iterable, Iterator

import openpyxl

from notam_gold import corpus, rewrite
from notam_gold import strata as s
from notam_gold.paths import EXTERNAL_DIR, HOLDOUT_DIR
from notam_gold.selection import Candidate, collapse_reissues, sample

ZENODO_SOURCE = "zenodo-17208970"
ZENODO_FILES = ("labelled_dataset.xlsx", "unlabelled_dataset.xlsx")
SEED = 2028
PER_AIRPORT = 3
QUOTAS = {
    s.DECLARED_DISTANCES: 20,
    s.DISPLACED_THRESHOLD: 20,
    s.PARTIAL_CLOSURE: 20,
    s.FULL_CLOSURE: 20,
    s.FICON_RWYCC: 20,
    s.FICON_NO_RWYCC: 20,
    s.OBSTACLE: 20,
    s.CANCELLED: 20,
    s.PLAUSIBLE_NEGATIVE: 28,
    s.OTHER_NEGATIVE: 12,
}
# A second batch, weighted toward the strata that state values, for a gate that needs at least 299 NOTAMs.
ADDITION_SEED = 2029
ADDITION_QUOTAS = {
    s.DECLARED_DISTANCES: 25,
    s.DISPLACED_THRESHOLD: 25,
    s.PARTIAL_CLOSURE: 25,
    s.FICON_RWYCC: 20,
    s.FICON_NO_RWYCC: 15,
    s.OBSTACLE: 20,
    s.FULL_CLOSURE: 10,
    s.PLAUSIBLE_NEGATIVE: 10,
}


def zenodo_record(location: str, raw: str, domestic_locations: dict[str, str]) -> dict | None:
    """A Zenodo NOTAM as a corpus record, or None when its text or ICAO location can't be recovered."""
    return rewrite.message_record(location, raw, domestic_locations, ZENODO_SOURCE)


def zenodo_records(locations: dict[str, str]) -> Iterator[dict]:
    for name in ZENODO_FILES:
        rows = openpyxl.load_workbook(EXTERNAL_DIR / ZENODO_SOURCE / name, read_only=True).active.iter_rows(
            values_only=True
        )
        next(rows)
        for location, raw, *_ in rows:
            if raw and (record := zenodo_record(location or "", str(raw), locations)):
                yield record


def api_records() -> Iterator[dict]:
    for path in sorted(HOLDOUT_DIR.glob("notams_*.jsonl.gz")):
        yield from corpus.read_jsonl_gz(path)


def candidates(records: Iterable[dict], excluded_templates: set) -> list[Candidate]:
    """Tagged candidates from ``records``, minus empty texts and reissues of an excluded template."""
    return [
        Candidate(record["id"], record["icao_location"], tuple(s.strata(text, record["nms_type"])), template)
        for record in records
        if (text := record["notam_text"]).strip()
        and (template := s.template_key(record["icao_location"], text)) not in excluded_templates
    ]


def select(
    api: list[Candidate], zenodo: list[Candidate], seed: int = SEED, quotas: dict[str, int] = QUOTAS
) -> list[tuple[Candidate, str]]:
    """Each stratum's quota, filled from the collected API NOTAMs first and then from Zenodo."""
    rng = random.Random(seed)
    api_ids = {c.id for c in api}
    pools: dict[tuple[bool, str], list[Candidate]] = {}
    for candidate in collapse_reissues([*api, *zenodo], rng):
        pools.setdefault((candidate.id in api_ids, candidate.primary), []).append(candidate)
    selected = []
    for stratum, quota in quotas.items():
        chosen = sample(pools.get((True, stratum), []), quota, PER_AIRPORT, rng)
        chosen += sample(pools.get((False, stratum), []), quota - len(chosen), PER_AIRPORT, rng)
        selected += [(candidate, stratum) for candidate in chosen]
    return selected

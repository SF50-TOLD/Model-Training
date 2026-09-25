"""Select the training corpus for the on-device NOTAM model and write it to the training database.

Training NOTAMs come from data/corpus.jsonl.gz, minus:

- every gold candidate, matched by ID, reissue template and whitespace-normalised text, so neither
  half of the gold set can leak into training through a reissue or a verbatim copy;
- every NOTAM the app's formatted-report parsers read whole (the list `notam-corpus` writes), since
  those never reach the model.

Reissues collapse to one NOTAM per template. Each stratum is sampled to its quota, preferring airport
diversity; the labelling plan (both runs, or run A alone) follows from the stratum. Selection ranks
interleave the strata, so a --pilot of the first N requests is a mix.

    python -m training.select_training --parsed parsed.jsonl
"""

import argparse
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path

from notam_gold import corpus, db
from notam_gold import strata as s
from notam_gold.paths import CORPUS, DATABASE
from notam_gold.selection import Candidate, collapse_reissues, sample
from training.paths import TRAINING_DATABASE

SEED = 2027
PER_AIRPORT = 6

# Strata where run A alone was wrong on reviewed gold get both runs and keep only agreements; the
# others, where run A made 1 error in 82, get run A alone.
DUAL_RUN_QUOTAS = {
    s.DECLARED_DISTANCES: 400,
    s.DISPLACED_THRESHOLD: 400,
    s.PARTIAL_CLOSURE: 400,
    s.FULL_CLOSURE: 900,
    s.OBSTACLE: 900,
    s.FICON_RWYCC: 300,
    s.FICON_NO_RWYCC: 150,
}
SINGLE_RUN_QUOTAS = {s.CANCELLED: 500, s.PLAUSIBLE_NEGATIVE: 1200, s.OTHER_NEGATIVE: 500}


def normalized_text(text: str) -> str:
    return " ".join(text.upper().split())


def gold_exclusions(connection: sqlite3.Connection) -> tuple[set, set, set]:
    """IDs, reissue templates and normalised texts of every gold candidate."""
    rows = connection.execute("SELECT id, icao_location, notam_text FROM notam").fetchall()
    return (
        {r["id"] for r in rows},
        {s.template_key(r["icao_location"], r["notam_text"]) for r in rows},
        {normalized_text(r["notam_text"]) for r in rows},
    )


def parser_read_ids(path: Path) -> set[str]:
    """Corpus IDs the formatted-report parsers read whole, from `notam-corpus` output."""
    with path.open(encoding="utf-8") as lines:
        return {record["id"] for record in map(json.loads, lines) if record.get("extraction")}


def eligible(records: dict, excluded: tuple[set, set, set], parsed: set[str]) -> list[Candidate]:
    ids, templates, texts = excluded
    candidates = []
    for record in records.values():
        text = record["notam_text"]
        template = s.template_key(record["icao_location"], text)
        if record["id"] in ids or record["id"] in parsed or template in templates or normalized_text(text) in texts:
            continue
        candidates.append(
            Candidate(
                id=record["id"],
                icao_location=record["icao_location"],
                strata=tuple(s.strata(text, record["nms_type"])),
                template=template,
            )
        )
    return candidates


def select(candidates: list[Candidate], rng: random.Random) -> list[tuple[Candidate, str]]:
    by_primary: dict[str, list[Candidate]] = {}
    for candidate in collapse_reissues(candidates, rng):
        by_primary.setdefault(candidate.primary, []).append(candidate)
    per_stratum = {
        stratum: sample(by_primary.get(stratum, []), quota, PER_AIRPORT, rng)
        for stratum, quota in {**DUAL_RUN_QUOTAS, **SINGLE_RUN_QUOTAS}.items()
    }
    return interleave(per_stratum)


def interleave(per_stratum: dict[str, list[Candidate]]) -> list[tuple[Candidate, str]]:
    """Round-robin across strata, so any prefix of the selection is a mix."""
    queues = {stratum: list(chosen) for stratum, chosen in per_stratum.items()}
    order = []
    while any(queues.values()):
        for stratum, queue in queues.items():
            if queue:
                order.append((queue.pop(0), stratum))
    return order


def write(connection: sqlite3.Connection, records: dict, selected: list[tuple[Candidate, str]]):
    if connection.execute("SELECT COUNT(*) FROM silver_label").fetchone()[0]:
        raise SystemExit("Training labels exist; refusing to change the training set under them.")
    connection.execute("DELETE FROM notam")
    connection.executemany(
        "INSERT INTO notam VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                c.id,
                records[c.id]["notam_id"],
                c.icao_location,
                records[c.id]["effective_start"],
                records[c.id]["effective_end"],
                records[c.id]["notam_text"],
                records[c.id]["nms_type"],
                records[c.id]["source"],
                db.dumps(list(c.strata)),
                stratum,
                rank,
                SEED,
            )
            for rank, (c, stratum) in enumerate(selected)
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parsed", type=Path, required=True, help="notam-corpus output for data/corpus.jsonl.gz")
    args = parser.parse_args()

    records = {r["id"]: r for r in corpus.read_jsonl_gz(CORPUS) if r["notam_text"].strip()}
    with db.connect(DATABASE) as gold:
        excluded = gold_exclusions(gold)
    candidates = eligible(records, excluded, parser_read_ids(args.parsed))
    selected = select(candidates, random.Random(SEED))

    with db.connect(TRAINING_DATABASE) as connection:
        write(connection, records, selected)
    counts = Counter(stratum for _, stratum in selected)
    for stratum in s.ALL_STRATA:
        plan = "A+B" if stratum in DUAL_RUN_QUOTAS else "A"
        print(f"  {stratum:<22} {counts[stratum]:>6,}  ({plan})")
    print(f"  {'total':<22} {len(selected):>6,}")


if __name__ == "__main__":
    main()

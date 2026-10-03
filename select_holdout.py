#!/usr/bin/env python3
"""Select candidates for the held-out test set and write them to data/notam_holdout.sqlite.

Candidates are NOTAMs no model has trained on: those `download_notams.py --holdout` collected, then
the Zenodo dataset in data/external/ for the strata they can't fill (see notam_gold/holdout.py).
Selection is reproducible, and refuses to change once silver labels exist.

--append adds a second batch (holdout.ADDITION_QUOTAS) to a labelled set, leaving every existing
candidate in place and excluding its reissues. It runs once.
"""

import argparse
import sqlite3
from collections import Counter

from notam_gold import corpus, db, holdout
from notam_gold import strata as s
from notam_gold.paths import CORPUS, HOLDOUT_DATABASE


def existing(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT id, icao_location, notam_text, selection_seed FROM notam").fetchall()


def insert(connection: sqlite3.Connection, records: dict, selected: list, seed: int, first_rank: int):
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
                seed,
            )
            for rank, (c, stratum) in enumerate(selected, start=first_rank)
        ],
    )


def report(selected: list, zenodo_ids: set[str]):
    from_zenodo = Counter(stratum for c, stratum in selected if c.id in zenodo_ids)
    total = Counter(stratum for _, stratum in selected)
    print(f"{'stratum':<22}{'selected':>9}{'zenodo':>8}")
    for stratum in s.ALL_STRATA:
        if total[stratum]:
            print(f"{stratum:<22}{total[stratum]:>9}{from_zenodo[stratum]:>8}")
    print(f"{'total':<22}{sum(total.values()):>9}{sum(from_zenodo.values()):>8}  → {HOLDOUT_DATABASE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--append", action="store_true", help="add the second, value-weighted batch")
    args = parser.parse_args()

    corpus_records = list(corpus.read_jsonl_gz(CORPUS))
    excluded = {s.template_key(r["icao_location"], r["notam_text"]) for r in corpus_records}
    with db.connect(HOLDOUT_DATABASE) as connection:
        current = existing(connection) if args.append else []
        if args.append and any(row["selection_seed"] == holdout.ADDITION_SEED for row in current):
            raise SystemExit("The second batch is already in the held-out set.")
        if not args.append and connection.execute("SELECT COUNT(*) FROM silver_label").fetchone()[0]:
            raise SystemExit("Silver labels exist; refusing to change the candidate set under them.")
    excluded |= {s.template_key(r["icao_location"], r["notam_text"]) for r in current}
    taken = {r["id"] for r in current}

    api_records = {r["id"]: r for r in holdout.api_records() if r["id"] not in taken}
    zenodo_records = {
        r["id"]: r
        for r in holdout.zenodo_records(holdout.domestic_locations(corpus_records))
        if r["id"] not in api_records and r["id"] not in taken
    }
    seed, quotas = (holdout.ADDITION_SEED, holdout.ADDITION_QUOTAS) if args.append else (holdout.SEED, holdout.QUOTAS)
    selected = holdout.select(
        holdout.candidates(api_records.values(), excluded),
        holdout.candidates(zenodo_records.values(), excluded),
        seed,
        quotas,
    )

    with db.connect(HOLDOUT_DATABASE) as connection:
        if not args.append:
            connection.execute("DELETE FROM notam")
        insert(connection, api_records | zenodo_records, selected, seed, first_rank=len(current))
    report(selected, set(zenodo_records))


if __name__ == "__main__":
    main()

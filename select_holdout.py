#!/usr/bin/env python3
"""Select candidates for the held-out test set and write them to data/notam_holdout.sqlite.

Candidates are NOTAMs no model has trained on: those `download_notams.py --holdout` collected, then
the Zenodo dataset in data/external/ for the strata they can't fill (see notam_gold/holdout.py).
Selection is reproducible, and refuses to change once silver labels exist.
"""

from collections import Counter

from notam_gold import corpus, db, holdout
from notam_gold import strata as s
from notam_gold.paths import CORPUS, HOLDOUT_DATABASE


def main():
    corpus_records = list(corpus.read_jsonl_gz(CORPUS))
    excluded = {s.template_key(r["icao_location"], r["notam_text"]) for r in corpus_records}
    api_records = {r["id"]: r for r in holdout.api_records()}
    zenodo_records = {
        r["id"]: r
        for r in holdout.zenodo_records(holdout.domestic_locations(corpus_records))
        if r["id"] not in api_records
    }
    records = api_records | zenodo_records
    selected = holdout.select(
        holdout.candidates(api_records.values(), excluded), holdout.candidates(zenodo_records.values(), excluded)
    )

    with db.connect(HOLDOUT_DATABASE) as connection:
        if connection.execute("SELECT COUNT(*) FROM silver_label").fetchone()[0]:
            raise SystemExit("Silver labels exist; refusing to change the candidate set under them.")
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
                    holdout.SEED,
                )
                for rank, (c, stratum) in enumerate(selected)
            ],
        )
    from_zenodo = Counter(stratum for c, stratum in selected if c.id in zenodo_records)
    total = Counter(stratum for _, stratum in selected)
    print(f"{'stratum':<22}{'selected':>9}{'zenodo':>8}")
    for stratum in s.ALL_STRATA:
        print(f"{stratum:<22}{total[stratum]:>9}{from_zenodo[stratum]:>8}")
    print(f"{'total':<22}{sum(total.values()):>9}{sum(from_zenodo.values()):>8}  → {HOLDOUT_DATABASE}")


if __name__ == "__main__":
    main()

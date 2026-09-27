#!/usr/bin/env python3
"""Tag the corpus with strata and select a seeded, stratified set of gold candidates.

Reads data/corpus.jsonl.gz and writes the candidates to the gold database.
Selection is reproducible: the same corpus and seed select the same NOTAMs.
"""

import argparse
from collections import Counter

from notam_gold import corpus, db
from notam_gold import strata as s
from notam_gold.paths import CORPUS
from notam_gold.selection import Candidate, SelectionConfig, select, stratum_counts


def print_table(title: str, counts: dict[str, int]):
    print(f"\n{title}")
    for stratum, count in counts.items():
        print(f"  {stratum:<22} {count:>7,}")
    print(f"  {'total':<22} {sum(counts.values()):>7,}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SelectionConfig.seed)
    parser.add_argument("--numeric-cap", type=int, default=SelectionConfig.numeric_cap)
    args = parser.parse_args()

    records = {r["id"]: r for r in corpus.read_jsonl_gz(CORPUS) if r["notam_text"].strip()}
    candidates = [
        Candidate(
            id=r["id"],
            icao_location=r["icao_location"],
            strata=tuple(s.strata(r["notam_text"], r["nms_type"])),
            template=s.template_key(r["icao_location"], r["notam_text"]),
        )
        for r in records.values()
    ]
    corpus_counts = Counter(stratum for c in candidates for stratum in c.strata)
    print_table(f"Corpus: {len(candidates):,} NOTAMs (a NOTAM can be in several strata)", dict(corpus_counts))

    config = SelectionConfig(seed=args.seed, numeric_cap=args.numeric_cap)
    selected = select(candidates, config)

    with db.connect() as connection:
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
                    config.seed,
                )
                for rank, (c, stratum) in enumerate(selected)
            ],
        )
    print_table(f"Gold candidates (seed {config.seed})", stratum_counts(selected))


if __name__ == "__main__":
    main()

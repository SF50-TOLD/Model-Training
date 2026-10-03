#!/usr/bin/env python3
"""Export reviewed gold labels to eval/ for Xcode's Evaluations framework.

Writes eval/notam_gold.jsonl (every accepted or edited NOTAM) and its stable
dev/test halves (eval/notam_dev.jsonl, eval/notam_test.jsonl), each with a
.meta.jsonl file whose lines match the samples line for line.

With --holdout, writes the held-out set instead: eval/notam_holdout.jsonl and its
.meta.jsonl file, with no halves.
"""

import argparse

from notam_gold import db
from notam_gold.export import export, export_holdout
from notam_gold.paths import EVAL_DIR, HOLDOUT_DATABASE
from notam_gold.reviews import stale_reviews
from notam_gold.strata import ALL_STRATA


def holdout():
    with db.connect(HOLDOUT_DATABASE) as connection:
        counts = export_holdout(connection, EVAL_DIR)
        stale = stale_reviews(connection)
    for stratum in ALL_STRATA:
        if counts[stratum]:
            print(f"{stratum:<22}{counts[stratum]:>7}")
    print(f"{'total':<22}{sum(counts.values()):>7}")
    print(f"Wrote {EVAL_DIR}/notam_holdout.jsonl and its .meta.jsonl file")
    report_stale(stale)


def report_stale(stale: dict):
    if stale:
        print(f"Left out {len(stale)} reviews the labelling rules have changed; re-review them to include them.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holdout", action="store_true", help="export the held-out set")
    if parser.parse_args().holdout:
        holdout()
        return
    with db.connect() as connection:
        counts = export(connection, EVAL_DIR)
        stale = stale_reviews(connection)
    print(f"{'stratum':<22}{'gold':>7}{'dev':>7}{'test':>7}")
    for stratum in ALL_STRATA:
        if counts["gold"][stratum]:
            print(f"{stratum:<22}" + "".join(f"{counts[name][stratum]:>7}" for name in ("gold", "dev", "test")))
    print(f"{'total':<22}" + "".join(f"{sum(counts[name].values()):>7}" for name in ("gold", "dev", "test")))
    print(f"Wrote {EVAL_DIR}/notam_{{gold,dev,test}}.jsonl and their .meta.jsonl files")
    report_stale(stale)


if __name__ == "__main__":
    main()

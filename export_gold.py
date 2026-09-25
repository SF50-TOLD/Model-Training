#!/usr/bin/env python3
"""Export reviewed gold labels to eval/ for Xcode's Evaluations framework.

Writes eval/notam_gold.jsonl (every accepted or edited NOTAM) and its stable
dev/test halves (eval/notam_dev.jsonl, eval/notam_test.jsonl), each with a
.meta.jsonl file whose lines match the samples line for line.
"""

from notam_gold import db
from notam_gold.export import export
from notam_gold.paths import EVAL_DIR
from notam_gold.reviews import stale_reviews
from notam_gold.strata import ALL_STRATA


def main():
    with db.connect() as connection:
        counts = export(connection, EVAL_DIR)
        stale = stale_reviews(connection)
    print(f"{'stratum':<22}{'gold':>7}{'dev':>7}{'test':>7}")
    for stratum in ALL_STRATA:
        if counts["gold"][stratum]:
            print(f"{stratum:<22}" + "".join(f"{counts[name][stratum]:>7}" for name in ("gold", "dev", "test")))
    print(f"{'total':<22}" + "".join(f"{sum(counts[name].values()):>7}" for name in ("gold", "dev", "test")))
    print(f"Wrote {EVAL_DIR}/notam_{{gold,dev,test}}.jsonl and their .meta.jsonl files")
    if stale:
        print(f"Left out {len(stale)} reviews the labelling rules have changed; re-review them to include them.")


if __name__ == "__main__":
    main()

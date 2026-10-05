#!/usr/bin/env python3
"""Migrate every current review to the current schema, appending one review row per NOTAM.

Reviews whose 2.0.0 meaning the 1.5.0 label can't settle (a closure the text limits to one
operation, an obstacle reference or direction read from the text) are appended under an
``Unreviewed:`` reviewer, so they return to the review queue. --dry-run reports without
writing; --holdout migrates the held-out set's database; --training only reports what the
training database's run-A silver labels would need a look at, since training reads them
through the converter and never rewrites them.
"""

import argparse
from collections import Counter
from pathlib import Path

from notam_gold import db
from notam_gold.migrate import is_current, migrate, migrate_reviews
from notam_gold.paths import DATABASE, HOLDOUT_DATABASE
from training.paths import TRAINING_DATABASE

SILVER_SQL = """
SELECT latest_silver.notam_key, latest_silver.extraction, notam.notam_text
FROM latest_silver JOIN notam ON notam.id = notam_key
WHERE run_name = 'A' AND extraction IS NOT NULL
"""


def report_silver(database: Path):
    counts, flagged = Counter(), 0
    with db.connect(database) as connection:
        for row in connection.execute(SILVER_SQL):
            extraction = db.loads(row["extraction"])
            if is_current(extraction):
                continue
            _, notes = migrate(extraction, row["notam_text"])
            counts.update(note.code for note in notes)
            flagged += any(note.needs_review for note in notes)
    print(f"{database.name}: {flagged} run-A labels would need a look; notes by kind: {dict(counts)}")


def migrate_database(database: Path, dry_run: bool, keys_out: Path | None):
    if not dry_run:
        db.back_up(database)
    with db.connect(database) as connection:
        report = migrate_reviews(connection, dry_run)
    verb = "would migrate" if dry_run else "migrated"
    print(f"{database.name}: {verb} {report.migrated} reviews; {len(report.needs_review)} need a look")
    for code, count in sorted(Counter(note.code for _, note in report.notes).items()):
        print(f"  {code:<24}{count:>6}")
    for key in report.needs_review:
        reasons = "; ".join(f"{n.path}: {n.message}" for k, n in report.notes if k == key and n.needs_review)
        print(f"  {key}: {reasons}")
    if keys_out is not None:
        keys_out.write_text("".join(f"{key}\n" for key in report.needs_review), encoding="utf-8")
        print(f"Wrote {len(report.needs_review)} keys to {keys_out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--holdout", action="store_true", help="migrate the held-out set's database")
    parser.add_argument("--training", action="store_true", help="only report on the training database's silver labels")
    parser.add_argument(
        "--keys-out", type=Path, help="write the NOTAM keys that need a look, for label_silver.py --keys"
    )
    args = parser.parse_args()
    if args.training:
        report_silver(TRAINING_DATABASE)
        return
    migrate_database(HOLDOUT_DATABASE if args.holdout else DATABASE, args.dry_run, args.keys_out)


if __name__ == "__main__":
    main()

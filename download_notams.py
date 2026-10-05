#!/usr/bin/env python3
"""Download every NOTAM from the NOTAM API and merge it with every earlier snapshot.

Writes the raw download to data/notams_<date>.jsonl.gz and the merged,
deduplicated corpus to data/corpus.jsonl.gz. The API only holds NOTAMs that
are still current, so the corpus merges every raw download (newest first)
and then the legacy data/all_notams.json; a NOTAM that has since expired stays
in the corpus. Raw downloads and the legacy snapshot are read, never written.

The published datasets in data/external/ (see notam_gold/external.py) are downloaded once and
merged last, so the API's text wins on a duplicate. The Polytechnique Montréal dataset has no
license; it is downloaded and merged only with --include-unlicensed.

With --holdout, it instead saves only NOTAMs that no raw download, the corpus or
an earlier holdout collection has, to data/holdout/notams_<date>T<time>.jsonl.gz.
These are the pool for a fresh held-out test set: data/holdout/ is never merged
into the corpus, so training never sees them. Run it at least every few weeks,
before the API drops NOTAMs 30 days after they expire.
"""

import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import date, datetime

from dotenv import load_dotenv
from tqdm import tqdm

from notam_gold import corpus, external, rewrite
from notam_gold import strata as s
from notam_gold.paths import CORPUS, DATA_DIR, HOLDOUT_DIR, LEGACY_SNAPSHOT
from notam_gold.selection import Candidate, collapse_reissues

# Every NOTAM effective before this was in the 2026-09-24 and 2026-09-25 downloads the corpus holds.
HOLDOUT_EARLIEST_START = "2026-09-24"
SCARCE_STRATA = (s.DISPLACED_THRESHOLD, s.PARTIAL_CLOSURE, s.DECLARED_DISTANCES)


def download(api: corpus.NOTAMAPI) -> dict[str, dict]:
    """Every NOTAM the API holds, keyed by identity."""
    total = api.total()
    rows: dict[str, dict] = {}
    with tqdm(total=total, desc="Downloading", unit="notam") as bar:
        for notam in api.sweep():
            if corpus.identity(notam) not in rows:
                rows[corpus.identity(notam)] = notam
                bar.update()
    print(f"Downloaded {len(rows):,} unique NOTAMs; the API reported {total:,}")
    return rows


def api_client() -> corpus.NOTAMAPI:
    token = os.getenv("NOTAM_API_TOKEN") or sys.exit("NOTAM_API_TOKEN is not set")
    return corpus.NOTAMAPI(os.getenv("NOTAM_API_BASE_URL", "https://notams.fly.dev"), token)


def holdout_records() -> list[dict]:
    return [record for path in sorted(HOLDOUT_DIR.glob("notams_*.jsonl.gz")) for record in corpus.read_jsonl_gz(path)]


def known_identities() -> set[str]:
    """Every NOTAM in the corpus, a raw download or the holdout."""
    downloads = (corpus.identity(n) for path in DATA_DIR.glob("notams_*.jsonl.gz") for n in corpus.read_jsonl_gz(path))
    return {r["id"] for r in corpus.read_jsonl_gz(CORPUS)} | set(downloads) | {r["id"] for r in holdout_records()}


def collect_holdout(api: corpus.NOTAMAPI) -> int:
    """Save the NOTAMs nothing local has yet; returns how many."""
    known = known_identities()
    new = {}
    for notam in api.sweep():
        if notam["effective_start"] < HOLDOUT_EARLIEST_START:
            break
        if (key := corpus.identity(notam)) not in known:
            new[key] = notam
    if new:
        now = datetime.now()
        path = HOLDOUT_DIR / f"notams_{now:%Y-%m-%dT%H%M}.jsonl.gz"
        HOLDOUT_DIR.mkdir(exist_ok=True)
        corpus.write_jsonl_gz(path, (corpus.corpus_record(n, f"{now:%Y-%m-%d}") for n in new.values()))
    return len(new)


def usable_holdout_strata(records: list[dict]) -> Counter:
    """Primary strata of holdout NOTAMs that aren't reissues of corpus text, one per reissued template."""
    corpus_templates = {s.template_key(r["icao_location"], r["notam_text"]) for r in corpus.read_jsonl_gz(CORPUS)}
    candidates = [
        Candidate(r["id"], r["icao_location"], tuple(s.strata(r["notam_text"], r["nms_type"])), template)
        for r in records
        if r["notam_text"].strip()
        and (template := s.template_key(r["icao_location"], r["notam_text"])) not in corpus_templates
    ]
    return Counter(c.primary for c in collapse_reissues(candidates, random.Random(0)))


def holdout(api: corpus.NOTAMAPI):
    saved = collect_holdout(api)
    records = holdout_records()
    counts = usable_holdout_strata(records)
    scarce = ", ".join(f"{stratum} {counts[stratum]}" for stratum in SCARCE_STRATA)
    print(f"Saved {saved:,} new NOTAMs; the holdout holds {len(records):,}. Usable scarce strata: {scarce}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--skip-download", action="store_true", help="re-merge an existing download")
    mode.add_argument("--holdout", action="store_true", help="save new NOTAMs to data/holdout/ instead")
    parser.add_argument(
        "--include-unlicensed", action="store_true", help="also merge the Polytechnique Montréal dataset (no license)"
    )
    args = parser.parse_args()

    load_dotenv()
    if args.holdout:
        holdout(api_client())
        return
    raw_path = DATA_DIR / f"notams_{date.today().isoformat()}.jsonl.gz"

    if not args.skip_download:
        fresh = download(api_client())
        corpus.write_jsonl_gz(raw_path, fresh.values())
        print(f"Wrote {len(fresh):,} NOTAMs to {raw_path}")
        external.fetch(args.include_unlicensed)

    downloads = sorted(DATA_DIR.glob("notams_*.jsonl.gz"), reverse=True)
    legacy = json.loads(LEGACY_SNAPSHOT.read_text(encoding="utf-8")) if LEGACY_SNAPSHOT.exists() else []
    api = corpus.merge(
        *(_snapshot_records(path) for path in downloads),
        (corpus.corpus_record(n, "2025-11") for n in legacy),
    )
    imported = external.imports(rewrite.domestic_locations(api), args.include_unlicensed)
    for source in imported:
        print(source.summary())
    merged = corpus.merge(api, *(source.records for source in imported))
    corpus.write_jsonl_gz(CORPUS, merged)
    print(
        f"Merged corpus: {len(merged):,} NOTAMs ({len(downloads)} downloads, {len(legacy):,} legacy, "
        f"{len(merged) - len(api):,} external) → {CORPUS}"
    )


def _snapshot_records(path):
    """A raw download's corpus records, sourced by the month in its ``notams_<date>`` name."""
    month = path.name.removeprefix("notams_")[:7]
    return (corpus.corpus_record(n, month) for n in corpus.read_jsonl_gz(path))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download every NOTAM from the NOTAM API and merge it with every earlier snapshot.

Writes the raw download to data/notams_<date>.jsonl.gz and the merged,
deduplicated corpus to data/corpus.jsonl.gz. The API only holds NOTAMs that
are still current, so the corpus merges every raw download (newest first)
and then the legacy data/all_notams.json; a NOTAM that has since expired stays
in the corpus. Raw downloads and the legacy snapshot are read, never written.
"""

import argparse
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
from tqdm import tqdm

from notam_gold import corpus
from notam_gold.paths import CORPUS, DATA_DIR, LEGACY_SNAPSHOT


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true", help="re-merge an existing download")
    args = parser.parse_args()

    load_dotenv()
    raw_path = DATA_DIR / f"notams_{date.today().isoformat()}.jsonl.gz"

    if not args.skip_download:
        token = os.getenv("NOTAM_API_TOKEN") or sys.exit("NOTAM_API_TOKEN is not set")
        api = corpus.NOTAMAPI(os.getenv("NOTAM_API_BASE_URL", "https://notams.fly.dev"), token)
        fresh = download(api)
        corpus.write_jsonl_gz(raw_path, fresh.values())
        print(f"Wrote {len(fresh):,} NOTAMs to {raw_path}")

    downloads = sorted(DATA_DIR.glob("notams_*.jsonl.gz"), reverse=True)
    legacy = json.loads(LEGACY_SNAPSHOT.read_text(encoding="utf-8")) if LEGACY_SNAPSHOT.exists() else []
    merged = corpus.merge(
        *(_snapshot_records(path) for path in downloads),
        (corpus.corpus_record(n, "2025-11") for n in legacy),
    )
    corpus.write_jsonl_gz(CORPUS, merged)
    print(f"Merged corpus: {len(merged):,} NOTAMs ({len(downloads)} downloads, {len(legacy):,} legacy) → {CORPUS}")


def _snapshot_records(path):
    """A raw download's corpus records, sourced by the month in its ``notams_<date>`` name."""
    month = path.name.removeprefix("notams_")[:7]
    return (corpus.corpus_record(n, month) for n in corpus.read_jsonl_gz(path))


if __name__ == "__main__":
    main()

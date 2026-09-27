"""Filesystem locations shared by the pipeline stages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVAL_DIR = ROOT / "eval"
SCHEMA_DIR = ROOT / "schema"
LABELER_DIR = ROOT / "labeler"

LEGACY_SNAPSHOT = DATA_DIR / "all_notams.json"
CORPUS = DATA_DIR / "corpus.jsonl.gz"
DATABASE = DATA_DIR / "notam_gold.sqlite"
SCHEMA_FILE = SCHEMA_DIR / "notam_extraction.schema.json"
SCHEMA_DOC = SCHEMA_DIR / "SCHEMA.md"

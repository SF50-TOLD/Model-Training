"""Export reviewed gold labels in the Evaluations framework's ModelSample shape.

Each sample line is ``{"input": {"prompt": ...}, "output": {"value": <NOTAMExtraction>}}``
with every key present. A parallel ``.meta.jsonl`` line (same line number) carries
provenance and strata, so results can be sliced without touching the sample.
"""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from notam_gold import db
from notam_gold.labeling import examples
from notam_gold.paths import SCHEMA_DOC
from notam_gold.prompt import build_prompt
from notam_gold.reviews import stale_reviews
from notam_gold.schema import canonicalize, schema_version, validate

DEV_FRACTION = 0.4
SPLIT_SALT = "notam-gold-split-v1"

GOLD_SQL = """
SELECT notam.*, review.reviewer, review.reviewed_at,
       review.extraction AS gold, review.edited, review.silver_label_id,
       label_run.model AS silver_model, label_run.prompt_version AS silver_prompt_version,
       disagreement.paths AS disagreement_paths
FROM current_review AS review
JOIN notam ON notam.id = review.notam_key
LEFT JOIN silver_label ON silver_label.id = review.silver_label_id
LEFT JOIN label_run ON label_run.id = silver_label.run_id
LEFT JOIN disagreement ON disagreement.notam_key = notam.id
WHERE review.status IN ('accepted', 'edited')
ORDER BY notam.id
"""


class InvalidGoldLabelError(Exception):
    """A reviewed label no longer validates, so the export stops rather than ship it."""


@dataclass(frozen=True)
class GoldRow:
    sample: dict
    meta: dict

    @property
    def split(self) -> str:
        return split_of(self.meta["notamKey"])


def worked_example_prompts() -> set[str]:
    """Prompts shown to models as worked examples (SCHEMA.md and the labeler's examples)."""
    schema_examples = re.findall(r"```text\n(.*?)\n```", SCHEMA_DOC.read_text(encoding="utf-8"), re.DOTALL)
    return set(schema_examples) | {example["prompt"] for example in examples(shuffle_seed=None)}


def split_of(notam_key: str) -> str:
    """``dev`` or ``test``, fixed by a salted hash of the NOTAM's identity so it never moves between exports."""
    digest = hashlib.sha256(f"{SPLIT_SALT}:{notam_key}".encode()).digest()
    return "dev" if int.from_bytes(digest[:8]) / 2**64 < DEV_FRACTION else "test"


def gold_rows(connection: sqlite3.Connection) -> list[GoldRow]:
    """Every accepted or edited review made under the current rules, validated and canonicalised."""
    rows = []
    stale = stale_reviews(connection)
    examples = worked_example_prompts()
    for row in connection.execute(GOLD_SQL):
        if row["id"] in stale:
            continue
        extraction = db.loads(row["gold"])
        if problems := validate(extraction):
            raise InvalidGoldLabelError(f"{row['id']}: {[p.to_dict() for p in problems]}")
        disagreements = db.loads(row["disagreement_paths"]) or []
        prompt = build_prompt(row["icao_location"], row["notam_text"])
        sample = {
            "input": {"prompt": prompt},
            "output": {"value": canonicalize(extraction)},
        }
        meta = {
            "notamId": row["notam_id"],
            "icaoLocation": row["icao_location"],
            "notamKey": row["id"],
            "strata": db.loads(row["strata"]),
            "selectedStratum": row["selected_stratum"],
            "reviewer": row["reviewer"],
            "reviewedAt": row["reviewed_at"],
            "edited": bool(row["edited"]),
            "schemaVersion": schema_version(),
            "silverLabelId": row["silver_label_id"],
            "silverModel": row["silver_model"],
            "silverPromptVersion": row["silver_prompt_version"],
            "silverDisagreement": bool(disagreements),
            "disagreementPaths": [d["path"] for d in disagreements],
            "metadataCanceled": row["nms_type"] == "C",
            "workedExample": prompt in examples,
            "effectiveStart": row["effective_start"],
            "effectiveEnd": row["effective_end"],
        }
        rows.append(GoldRow(sample, meta))
    return rows


def write(rows: list[GoldRow], samples: Path, meta: Path):
    """Write samples and their meta lines; meta ``line`` is the 1-based sample line number."""
    with samples.open("w", encoding="utf-8") as sample_file, meta.open("w", encoding="utf-8") as meta_file:
        for line, row in enumerate(rows, start=1):
            sample_file.write(json.dumps(row.sample, ensure_ascii=False) + "\n")
            meta_file.write(json.dumps({"line": line, **row.meta}, ensure_ascii=False) + "\n")


def export(connection: sqlite3.Connection, directory: Path) -> dict[str, Counter]:
    """Write the full set and its dev/test halves to ``directory``; returns stratum counts per file."""
    rows = gold_rows(connection)
    directory.mkdir(parents=True, exist_ok=True)
    # A worked example's answer is in front of the model, so it can't count toward the held-out gate.
    halves = {
        "dev": [r for r in rows if r.split == "dev"],
        "test": [r for r in rows if r.split == "test" and not r.meta["workedExample"]],
    }
    write(rows, directory / "notam_gold.jsonl", directory / "notam_gold.meta.jsonl")
    for name, half in halves.items():
        write(half, directory / f"notam_{name}.jsonl", directory / f"notam_{name}.meta.jsonl")
    counts = {"gold": Counter(r.meta["selectedStratum"] for r in rows)}
    counts |= {name: Counter(r.meta["selectedStratum"] for r in half) for name, half in halves.items()}
    return counts

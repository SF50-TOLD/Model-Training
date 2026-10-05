"""Build the training and validation sets from silver labels.

A NOTAM's label is kept when:

- its stratum was labelled by both runs (see select_training.py) and the two agree field for field; or
- its stratum was labelled by run A alone.

Labels come from the training database and from the gold candidates that aren't gold (both runs agree
on all of them, and none shares a reissue template or text with a gold NOTAM). Every label must
validate against the schema. The completion is the canonical extraction as compact JSON with keys in
schema order.

Labels then follow the conventions both runs get wrong alike (label_rules.py). Validation is carved
from training by reissue template, never from the gold set:
**nothing from notam_dev or notam_test is ever written here.**

    python -m training.build_dataset
"""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter

from notam_gold import db
from notam_gold import strata as s
from notam_gold.disagreement import diff
from notam_gold.migrate import current
from notam_gold.paths import DATABASE, EVAL_DIR
from notam_gold.prompt import build_prompt
from notam_gold.schema import canonicalize, validate
from training.label_rules import corrected
from training.paths import DATASET_DIR, TRAINING_DATABASE
from training.select_training import DUAL_RUN_STRATA, normalized_text

VALIDATION_SHARE = 0.05
SPLIT_SALT = "notam-train-split-v1"

EFFECT_KEYS = ("runway", "closure", "partialClosure", "thresholdDisplacement", "declaredDistances", "surfaceCondition")
MEASURE_KEYS = ("value", "unit")
HEIGHT_KEYS = ("value", "unit", "datum")
DECLARED_KEYS = ("TORA", "LDA")
CONTAMINANT_KEYS = ("type", "coveragePercent", "depth")
OBSTACLE_KEYS = ("height", "distance", "reference", "direction")
REFERENCE_KEYS = ("kind", "runway")


def ordered(extraction: dict) -> dict:
    """The extraction with every object's keys in schema order."""
    return {
        "isCanceled": extraction["isCanceled"],
        "effects": [_ordered_effect(e) for e in extraction["effects"]],
        "obstacles": [_ordered_obstacle(o) for o in extraction["obstacles"]],
    }


def _keyed(value: dict | None, keys: tuple[str, ...]) -> dict | None:
    return None if value is None else {k: value[k] for k in keys}


def _ordered_effect(effect: dict) -> dict:
    ordered = {k: effect[k] for k in EFFECT_KEYS}
    if (portion := effect["partialClosure"]) is not None:
        ordered["partialClosure"] = {"length": _keyed(portion["length"], MEASURE_KEYS), "end": portion["end"]}
    ordered["thresholdDisplacement"] = _keyed(effect["thresholdDisplacement"], MEASURE_KEYS)
    if (declared := effect["declaredDistances"]) is not None:
        ordered["declaredDistances"] = {k: _keyed(declared[k], MEASURE_KEYS) for k in DECLARED_KEYS}
    if (condition := effect["surfaceCondition"]) is not None:
        ordered["surfaceCondition"] = {
            "rwyCC": condition["rwyCC"],
            "contaminants": [_ordered_contaminant(c) for c in condition["contaminants"]],
        }
    return ordered


def _ordered_contaminant(contaminant: dict) -> dict:
    return {**_keyed(contaminant, CONTAMINANT_KEYS), "depth": _keyed(contaminant["depth"], MEASURE_KEYS)}


def _ordered_obstacle(obstacle: dict) -> dict:
    return {
        "height": _keyed(obstacle["height"], HEIGHT_KEYS),
        "distance": _keyed(obstacle["distance"], MEASURE_KEYS),
        "reference": _keyed(obstacle["reference"], REFERENCE_KEYS),
        "direction": obstacle["direction"],
    }


def completion(extraction: dict) -> str:
    return json.dumps(ordered(canonicalize(extraction)), separators=(",", ":"), ensure_ascii=False)


LATEST_SQL = """
SELECT silver.notam_key, silver.run_name, silver.extraction, notam.notam_text
FROM latest_silver AS silver JOIN notam ON notam.id = silver.notam_key
WHERE silver.extraction IS NOT NULL
"""


def latest(connection: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """Each run's latest label per NOTAM, in the current schema."""
    rows = connection.execute(LATEST_SQL)
    return {(r["notam_key"], r["run_name"]): current(json.loads(r["extraction"]), r["notam_text"]) for r in rows}


def kept_label(key: str, stratum: str, labels: dict) -> dict | None:
    """The label training uses for one NOTAM, or ``None`` when its runs disagree or it has none."""
    a, b = labels.get((key, "A")), labels.get((key, "B"))
    if a is None:
        return None
    if stratum in DUAL_RUN_STRATA:
        return a if b is not None and not diff(a, b) else None
    return a


def training_labels(connection: sqlite3.Connection, exclude: set[str]) -> list[tuple[sqlite3.Row, dict]]:
    labels = latest(connection)
    kept = []
    for notam in connection.execute("SELECT * FROM notam ORDER BY selection_rank"):
        if notam["id"] in exclude:
            continue
        if (label := kept_label(notam["id"], notam["selected_stratum"], labels)) is not None:
            kept.append((notam, label))
    return kept


def gold_keys() -> set[str]:
    with (EVAL_DIR / "notam_gold.meta.jsonl").open(encoding="utf-8") as lines:
        return {json.loads(line)["notamKey"] for line in lines}


def non_gold_candidates(gold: set[str]) -> list[tuple[sqlite3.Row, dict]]:
    """Gold candidates that aren't gold, with labels both runs agree on, sharing nothing with gold."""
    with db.connect(DATABASE) as connection:
        rows = connection.execute("SELECT * FROM notam").fetchall()
        gold_rows = [r for r in rows if r["id"] in gold]
        templates = {s.template_key(r["icao_location"], r["notam_text"]) for r in gold_rows}
        texts = {normalized_text(r["notam_text"]) for r in gold_rows}
        labels = latest(connection)
    kept = []
    for row in rows:
        if row["id"] in gold or s.template_key(row["icao_location"], row["notam_text"]) in templates:
            continue
        if normalized_text(row["notam_text"]) in texts:
            continue
        a, b = labels.get((row["id"], "A")), labels.get((row["id"], "B"))
        if a is not None and b is not None and not diff(a, b):
            kept.append((row, a))
    return kept


def is_validation(notam: sqlite3.Row) -> bool:
    template = "|".join(s.template_key(notam["icao_location"], notam["notam_text"]))
    digest = hashlib.sha256(f"{SPLIT_SALT}:{template}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < VALIDATION_SHARE


def main():
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    gold = gold_keys()
    with db.connect(TRAINING_DATABASE) as connection:
        examples = training_labels(connection, exclude=gold) + non_gold_candidates(gold)

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    counts, skipped = Counter(), Counter()
    with (
        (DATASET_DIR / "train.jsonl").open("w", encoding="utf-8") as train,
        (DATASET_DIR / "val.jsonl").open("w", encoding="utf-8") as val,
    ):
        for notam, label in examples:
            if notam["id"] in gold:
                raise SystemExit(f"{notam['id']} is gold; refusing to write it to a training set")
            label = corrected(label, notam["notam_text"])
            if validate(label):
                skipped["invalid"] += 1
                continue
            split = "val" if is_validation(notam) else "train"
            row = {
                "notamKey": notam["id"],
                "stratum": notam["selected_stratum"],
                "prompt": build_prompt(notam["icao_location"], notam["notam_text"]),
                "completion": completion(label),
            }
            (val if split == "val" else train).write(json.dumps(row, ensure_ascii=False) + "\n")
            counts[(split, notam["selected_stratum"])] += 1
    for split in ("train", "val"):
        by_stratum = {k[1]: v for k, v in counts.items() if k[0] == split}
        print(f"{split}: {sum(by_stratum.values()):,}  {by_stratum}")
    if skipped:
        print(f"skipped: {dict(skipped)}")


if __name__ == "__main__":
    main()

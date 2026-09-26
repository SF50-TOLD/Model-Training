"""Build the model's training and validation sets from silver labels.

A NOTAM's label is kept when:

- its stratum was labelled by both runs (see select_training.py) and the two agree field for field; or
- its stratum was labelled by run A alone.

Labels come from the training database and from the gold candidates that aren't gold (both runs agree
on all of them, and none shares a reissue template or text with a gold NOTAM). Every label must
validate against the schema. The completion is the canonical extraction as compact JSON with keys in
schema order — exactly the text the on-device decoder emits.

Labels then follow the conventions both runs get wrong alike (label_rules.py). Validation is carved
from training by reissue template, never from the gold set:
**nothing from notam_dev or notam_test is ever written here.** Training NOTAMs in the scarce numeric
strata also get label-preserving variants (augment.py), and training gets synthetic NOTAMs for a
pattern the corpus has no usable examples of (synthetic.py); validation gets neither.

    python -m training.build_dataset
"""

import argparse
import hashlib
import json
import random
import sqlite3
from collections import Counter

from notam_gold import db
from notam_gold import strata as s
from notam_gold.disagreement import diff
from notam_gold.paths import DATABASE, EVAL_DIR
from notam_gold.prompt import build_prompt
from notam_gold.schema import canonicalize, validate
from training import synthetic
from training.augment import variants
from training.label_rules import corrected
from training.paths import DATASET_DIR, TRAINING_DATABASE
from training.select_training import DUAL_RUN_STRATA, normalized_text

VALIDATION_SHARE = 0.05
SPLIT_SALT = "notam-train-split-v1"
AUGMENT_SEED = 2027
# The strata whose numeric fields the corpus has fewest examples of.
AUGMENTED_STRATA = {s.DISPLACED_THRESHOLD, s.PARTIAL_CLOSURE, s.DECLARED_DISTANCES}

EFFECT_KEYS = (
    "runway",
    "closure",
    "closedLength",
    "closedEnd",
    "thresholdDisplacement",
    "declaredDistances",
    "surfaceCondition",
    "obstacle",
)
MEASURE_KEYS = ("value", "unit")
DECLARED_KEYS = ("TORA", "TODA", "ASDA", "LDA")
CONTAMINANT_KEYS = ("type", "runwayThird", "coveragePercent", "depth")
OBSTACLE_KEYS = (
    "heightAGL",
    "heightMSL",
    "distance",
    "distanceReference",
    "bearingDegrees",
    "latitude",
    "longitude",
)


def ordered(extraction: dict) -> dict:
    """The extraction with every object's keys in schema order."""

    def measure(value):
        return None if value is None else {k: value[k] for k in MEASURE_KEYS}

    def effect(e):
        condition = e["surfaceCondition"]
        obstacle = e["obstacle"]
        declared = e["declaredDistances"]
        return {
            "runway": e["runway"],
            "closure": e["closure"],
            "closedLength": measure(e["closedLength"]),
            "closedEnd": e["closedEnd"],
            "thresholdDisplacement": measure(e["thresholdDisplacement"]),
            "declaredDistances": None if declared is None else {k: measure(declared[k]) for k in DECLARED_KEYS},
            "surfaceCondition": None
            if condition is None
            else {
                "rwyCC": condition["rwyCC"],
                "contaminants": [
                    {**{k: c[k] for k in CONTAMINANT_KEYS}, "depth": measure(c["depth"])}
                    for c in condition["contaminants"]
                ],
            },
            "obstacle": None
            if obstacle is None
            else {
                k: measure(obstacle[k]) if k in ("heightAGL", "heightMSL", "distance") else obstacle[k]
                for k in OBSTACLE_KEYS
            },
        }

    return {"isCanceled": extraction["isCanceled"], "effects": [effect(e) for e in extraction["effects"]]}


def completion(extraction: dict) -> str:
    return json.dumps(ordered(canonicalize(extraction)), separators=(",", ":"), ensure_ascii=False)


def latest(connection: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    rows = connection.execute("SELECT notam_key, run_name, extraction FROM latest_silver WHERE extraction IS NOT NULL")
    return {(r["notam_key"], r["run_name"]): json.loads(r["extraction"]) for r in rows}


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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variants", type=int, default=5, help="augmented variants per scarce training NOTAM")
    parser.add_argument("--synthetic", type=int, default=80, help="synthetic NOTAMs added to training")
    args = parser.parse_args()
    rng = random.Random(AUGMENT_SEED)
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
            prompt = build_prompt(notam["icao_location"], notam["notam_text"])
            rows = [(prompt, label)]
            if split == "train" and notam["selected_stratum"] in AUGMENTED_STRATA:
                rows += variants(prompt, label, args.variants, rng)
            for text, extraction in rows:
                row = {
                    "notamKey": notam["id"],
                    "stratum": notam["selected_stratum"],
                    "prompt": text,
                    "completion": completion(extraction),
                }
                (val if split == "val" else train).write(json.dumps(row, ensure_ascii=False) + "\n")
                counts[(split, notam["selected_stratum"])] += 1
        for index, (prompt, label) in enumerate(synthetic.examples(args.synthetic, rng)):
            if problems := validate(label):
                raise SystemExit(f"synthetic example {index} is invalid: {problems}")
            row = {
                "notamKey": f"synthetic {index}",
                "stratum": synthetic.STRATUM,
                "prompt": prompt,
                "completion": completion(label),
            }
            train.write(json.dumps(row, ensure_ascii=False) + "\n")
            counts[("train", synthetic.STRATUM)] += 1
    for split in ("train", "val"):
        by_stratum = {k[1]: v for k, v in counts.items() if k[0] == split}
        print(f"{split}: {sum(by_stratum.values()):,}  {by_stratum}")
    if skipped:
        print(f"skipped: {dict(skipped)}")


if __name__ == "__main__":
    main()

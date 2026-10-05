"""A tiny classifier for whether a NOTAM affects runway performance, for sorting the app's NOTAM list.

A NOTAM is relevant when its label states a runway effect or an obstacle and it isn't a cancellation.
The classifier is a logistic regression over hashed word, word-pair, word-triple and character
4-gram features of the NOTAM text, with every number replaced by ``#``, so it learns phrasing
rather than values. It trains in seconds on the silver-labelled training set and is scored on the
reviewed gold and held-out sets; a missed NOTAM still appears in the app's list, only lower, so the
gate is on recall.

The app reproduces ``features`` exactly: tokens are runs of ``A-Z`` and ``#`` or any other single
non-space character of the upper-cased, whitespace-collapsed text; each feature's name is hashed
with 64-bit FNV-1a over its UTF-8 bytes, modulo the dimension; a feature's value is ``1 + ln(count)``,
values that hash alike add up, and the vector is scaled to unit length. ``export`` writes the
weights as little-endian float32 with a JSON manifest, and a parity file of texts with the scores
these weights give them, for the app's tests.

    python -m training.relevance --out data/models/relevance
"""

import argparse
import json
import math
import random
import re
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from training.paths import DATASET_DIR

DIMENSION = 1 << 18
THRESHOLD = 0.2
RECALL_GATE = 0.97
EPOCHS = 12
LEARNING_RATE = 0.1
L2 = 1e-6
SEED = 7
VERSION = 1
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN = re.compile(r"[A-Z#]+|[^\sA-Z#]")
_FNV_OFFSET, _FNV_PRIME, _MASK = 0xCBF29CE484222325, 0x100000001B3, (1 << 64) - 1
EVAL_SPLITS = ("dev", "test", "holdout")


def fnv1a64(text: str) -> int:
    """64-bit FNV-1a of ``text``'s UTF-8 bytes."""
    value = _FNV_OFFSET
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * _FNV_PRIME) & _MASK
    return value


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(_NUMBER.sub("#", " ".join(text.upper().split())))


def feature_names(text: str) -> Counter:
    words = tokens(text)
    names = Counter()
    for i, word in enumerate(words):
        names["w:" + word] += 1
        if i + 1 < len(words):
            names[f"b:{word}_{words[i + 1]}"] += 1
        if i + 2 < len(words):
            names[f"t:{word}_{words[i + 1]}_{words[i + 2]}"] += 1
        if len(word) > 4:
            names.update("c:" + word[j : j + 4] for j in range(len(word) - 3))
    return names


def features(text: str, dimension: int = DIMENSION) -> dict[int, float]:
    """The unit-length hashed feature vector of ``text``, as index → value."""
    vector: dict[int, float] = {}
    for name, count in feature_names(text).items():
        index = fnv1a64(name) % dimension
        vector[index] = vector.get(index, 0.0) + 1 + math.log(count)
    norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
    return {index: value / norm for index, value in vector.items()}


def is_relevant(extraction: dict) -> bool:
    return not extraction["isCanceled"] and bool(extraction["effects"] or extraction["obstacles"])


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(min(z, 30.0), -30.0)))


@dataclass
class Model:
    weights: list[float]
    bias: float
    threshold: float = THRESHOLD

    def probability(self, text: str) -> float:
        dimension = len(self.weights)
        return _sigmoid(self.bias + sum(self.weights[i] * v for i, v in features(text, dimension).items()))

    def as_float32(self) -> Model:
        """This model with weights rounded to the float32 values the app loads."""
        rounded = struct.unpack(f"<{len(self.weights)}f", struct.pack(f"<{len(self.weights)}f", *self.weights))
        return Model(list(rounded), struct.unpack("<f", struct.pack("<f", self.bias))[0], self.threshold)


def train(texts: list[str], labels: list[int], epochs: int = EPOCHS, dimension: int = DIMENSION) -> Model:
    """Logistic regression by shuffled stochastic gradient descent, seeded so it is reproducible."""
    rng = random.Random(SEED)
    vectors = [features(text, dimension) for text in texts]
    weights, bias = [0.0] * dimension, 0.0
    order = list(range(len(vectors)))
    for epoch in range(epochs):
        rng.shuffle(order)
        rate = LEARNING_RATE / (1 + epoch * 0.5)
        for i in order:
            vector = vectors[i]
            error = _sigmoid(bias + sum(weights[k] * v for k, v in vector.items())) - labels[i]
            for k, v in vector.items():
                weights[k] -= rate * (error * v + L2 * weights[k])
            bias -= rate * error
    return Model(weights, bias)


def _notam_text(prompt: str) -> str:
    return prompt.split("\n\n", 1)[1]


def training_examples(directory: Path = DATASET_DIR) -> tuple[list[str], list[int]]:
    """Each distinct training NOTAM's text and relevance; augmented and synthetic copies are left out."""
    texts, labels, seen = [], [], set()
    for name in ("train.jsonl", "val.jsonl"):
        for row in map(json.loads, (directory / name).read_text(encoding="utf-8").splitlines()):
            if row["notamKey"] in seen or row["notamKey"].startswith("synthetic"):
                continue
            seen.add(row["notamKey"])
            texts.append(_notam_text(row["prompt"]))
            labels.append(int(is_relevant(json.loads(row["completion"]))))
    return texts, labels


def scores(model: Model, samples: Path) -> dict:
    """Recall and precision at the model's threshold, and the relevant NOTAMs it misses."""
    rows = [json.loads(line) for line in samples.read_text(encoding="utf-8").splitlines()]
    found = missed = false_alarms = 0
    misses = []
    for row in rows:
        text, relevant = _notam_text(row["input"]["prompt"]), is_relevant(row["output"]["value"])
        flagged = model.probability(text) >= model.threshold
        found += relevant and flagged
        false_alarms += flagged and not relevant
        if relevant and not flagged:
            missed += 1
            misses.append(" ".join(text.split())[:120])
    relevant_count = found + missed
    return {
        "count": len(rows),
        "relevant": relevant_count,
        "recall": found / relevant_count if relevant_count else None,
        "precision": found / (found + false_alarms) if found + false_alarms else None,
        "misses": misses,
    }


def export(model: Model, out: Path, parity_texts: list[str]):
    """Write the weights, their manifest and a parity file of texts with the scores these weights give."""
    out.mkdir(parents=True, exist_ok=True)
    shipped = model.as_float32()
    (out / "notam-relevance.weights").write_bytes(struct.pack(f"<{len(shipped.weights)}f", *shipped.weights))
    manifest = {
        "version": VERSION,
        "dimension": len(shipped.weights),
        "bias": shipped.bias,
        "threshold": shipped.threshold,
        "weights": "notam-relevance.weights",
        "hash": "fnv1a64",
    }
    (out / "notam-relevance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (out / "parity.jsonl").open("w", encoding="utf-8") as parity:
        for text in parity_texts:
            parity.write(json.dumps({"text": text, "probability": shipped.probability(text)}) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--eval-dir", type=Path, default=Path("eval"))
    args = parser.parse_args()
    texts, labels = training_examples()
    print(f"Training on {len(texts):,} NOTAMs, {sum(labels):,} relevant")
    model = train(texts, labels).as_float32()
    passed = True
    for split in EVAL_SPLITS:
        result = scores(model, args.eval_dir / f"notam_{split}.jsonl")
        passed &= result["recall"] >= RECALL_GATE
        print(
            f"{split:<8} {result['count']:>4} NOTAMs, {result['relevant']:>4} relevant: "
            f"recall {result['recall']:.3f}, precision {result['precision']:.3f}"
        )
        for miss in result["misses"]:
            print(f"    missed: {miss}")
    if not passed:
        raise SystemExit(f"Recall is below {RECALL_GATE} on a reviewed set; not exporting.")
    parity = [_notam_text(json.loads(line)["input"]["prompt"]) for line in (args.eval_dir / "notam_dev.jsonl").open()]
    export(model, args.out, parity[:60] + ["", "rwy 09 clsd", "RWY  09\r\n27 CLSD ÄÖ"])
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

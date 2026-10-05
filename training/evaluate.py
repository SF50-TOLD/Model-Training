"""Score a trained reader against a gold set, field by field, without the app's harness.

Each gold NOTAM is put to the model as the app would put it; the reading is decoded and compared with
the gold extraction. A field the gold states is correct, missed or wrong; a field only the reading
states is invented. The summary gives each field's recall (correct over stated) and safety (one minus
wrong and invented over everything either side states), and whole-NOTAM rates: exact readings,
readable readings, silence where gold is silent, and hazardous readings, meaning a wrong length,
distance or displacement, or an operation the gold closes that the reading leaves open. The app's
harness decodes under a grammar; this one does not, so a malformed reading counts as unreadable here
and as nothing there.

    python -m training.evaluate --model data/models/<name> --samples eval/notam_dev.jsonl
"""

import argparse
import json
from collections import Counter, defaultdict
from enum import Enum
from pathlib import Path

from notam_gold.schema import canonicalize, validate
from training import reading_format
from training.template import END_OF_READING, prompt_text

HAZARD_FIELDS = ("TORA", "LDA", "partialClosure.length", "thresholdDisplacement")
MAX_READING_TOKENS = 160


class Outcome(Enum):
    CORRECT = "correct"
    MISSED = "missed"
    WRONG = "wrong"
    INVENTED = "invented"


def _stated(extraction: dict) -> dict[tuple[str, str], str]:
    """Every fact the extraction states, keyed by runway and field, as comparable text."""
    stated = {}
    for effect in extraction["effects"]:
        runway = effect["runway"] or "*"
        if effect["closure"] != "none":
            stated[(runway, "closure")] = effect["closure"]
        if (portion := effect["partialClosure"]) is not None:
            stated[(runway, "partialClosure")] = "stated"
            for key in ("length", "end"):
                if portion[key] is not None:
                    stated[(runway, f"partialClosure.{key}")] = json.dumps(portion[key], sort_keys=True)
        if effect["thresholdDisplacement"] is not None:
            stated[(runway, "thresholdDisplacement")] = json.dumps(effect["thresholdDisplacement"], sort_keys=True)
        for key in ("TORA", "LDA"):
            if (effect["declaredDistances"] or {}).get(key) is not None:
                stated[(runway, key)] = json.dumps(effect["declaredDistances"][key], sort_keys=True)
        if (condition := effect["surfaceCondition"]) is not None:
            if condition["rwyCC"] is not None:
                stated[(runway, "rwyCC")] = json.dumps(condition["rwyCC"])
            stated[(runway, "contaminants")] = json.dumps(condition["contaminants"], sort_keys=True)
    for key in ("height", "distance", "reference", "direction"):
        values = sorted(json.dumps(o[key], sort_keys=True) for o in extraction["obstacles"] if o[key] is not None)
        if values:
            stated[("obstacles", key)] = json.dumps(values)
    return stated


def outcomes(gold: dict, read: dict | None) -> dict[tuple[str, str], Outcome]:
    """How the reading fares on every field either it or the gold states; an unreadable reading misses all."""
    expected = _stated(canonicalize(gold))
    actual = _stated(canonicalize(read)) if read is not None else {}
    scored = {}
    for key in expected.keys() | actual.keys():
        if key not in actual:
            scored[key] = Outcome.MISSED
        elif key not in expected:
            scored[key] = Outcome.INVENTED
        else:
            scored[key] = Outcome.CORRECT if expected[key] == actual[key] else Outcome.WRONG
    return scored


def _is_silent(extraction: dict) -> bool:
    return not extraction["isCanceled"] and not extraction["effects"] and not extraction["obstacles"]


_CLOSED_OPERATIONS = {"none": set(), "takeoff": {"takeoff"}, "landing": {"landing"}, "both": {"takeoff", "landing"}}


def _closures(extraction: dict | None) -> dict[str | None, set[str]]:
    effects = extraction["effects"] if extraction else []
    return {e["runway"]: _CLOSED_OPERATIONS[e["closure"]] for e in effects}


def _opens_a_closed_operation(gold: dict, read: dict | None) -> bool:
    """Whether the reading leaves open an operation the gold closes; closing more is only cautious."""
    read_closures = _closures(read)
    return any(not closed <= read_closures.get(runway, set()) for runway, closed in _closures(gold).items())


def _is_hazardous(gold: dict, read: dict | None, scored: dict[tuple[str, str], Outcome]) -> bool:
    wrong_length = any(f in HAZARD_FIELDS and o == Outcome.WRONG for (_, f), o in scored.items())
    return wrong_length or _opens_a_closed_operation(gold, read)


def summarize(pairs: list[tuple[dict, dict | None]]) -> dict:
    """Per-field recall and safety, and whole-NOTAM rates, over ``(gold, reading)`` pairs."""
    counts = defaultdict(Counter)
    notams = Counter()
    silent = 0
    for gold, read in pairs:
        scored = outcomes(gold, read)
        for (_, field), outcome in scored.items():
            counts[field][outcome] += 1
        notams["readable"] += read is not None
        notams["exact"] += read is not None and canonicalize(gold) == canonicalize(read)
        notams["hazardous"] += _is_hazardous(gold, read, scored)
        if _is_silent(gold):
            silent += 1
            notams["staysSilent"] += read is not None and _is_silent(read)
    fields = {}
    for field, count in sorted(counts.items()):
        stated = count[Outcome.CORRECT] + count[Outcome.MISSED] + count[Outcome.WRONG]
        either = stated + count[Outcome.INVENTED]
        fields[field] = {
            "recall": count[Outcome.CORRECT] / stated if stated else None,
            "safety": 1 - (count[Outcome.WRONG] + count[Outcome.INVENTED]) / either if either else None,
            "stated": stated,
        }
    total = len(pairs)
    return {
        "fields": fields,
        "notams": {
            "count": total,
            "readable": notams["readable"] / total,
            "exact": notams["exact"] / total,
            "hazardous": notams["hazardous"] / total,
            "staysSilent": notams["staysSilent"] / silent if silent else None,
        },
    }


def decode(reading: str) -> dict | None:
    """The extraction a reading states, or ``None`` when it is outside the format or invalid."""
    try:
        extraction = reading_format.decode(reading)
    except ValueError:
        return None
    return None if validate(extraction) else extraction


def read_all(model_path: Path, prompts: list[str]) -> list[str]:
    """Greedy readings of every prompt from the model at ``model_path``."""
    from mlx_lm import generate, load  # noqa: PLC0415 — the scorer runs without MLX

    model, tokenizer = load(str(model_path))
    stop = tokenizer.encode(END_OF_READING, add_special_tokens=False)[0]
    readings = []
    for prompt in prompts:
        text = generate(model, tokenizer, prompt=prompt_text(prompt), max_tokens=MAX_READING_TOKENS, verbose=False)
        readings.append(text.split(tokenizer.decode([stop]))[0].strip())
    return readings


def _report(summary: dict) -> str:
    lines = [f"{'field':<24}{'recall':>8}{'safety':>8}{'stated':>8}"]
    for field, scores in summary["fields"].items():
        recall = "-" if scores["recall"] is None else f"{scores['recall']:.3f}"
        safety = "-" if scores["safety"] is None else f"{scores['safety']:.3f}"
        lines.append(f"{field:<24}{recall:>8}{safety:>8}{scores['stated']:>8}")
    notams = summary["notams"]
    silent = "-" if notams["staysSilent"] is None else f"{notams['staysSilent']:.3f}"
    lines.append(
        f"NOTAMs {notams['count']}: readable {notams['readable']:.3f}, exact {notams['exact']:.3f},"
        f" hazardous {notams['hazardous']:.3f}, stays silent {silent}"
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, required=True, help="a trained model folder")
    parser.add_argument("--samples", type=Path, required=True, help="a ModelSample .jsonl file from eval/")
    parser.add_argument("--out", type=Path, help="where to write each NOTAM's reading and outcomes")
    args = parser.parse_args()
    samples = [json.loads(line) for line in args.samples.read_text(encoding="utf-8").splitlines()]
    readings = read_all(args.model, [s["input"]["prompt"] for s in samples])
    pairs = [(s["output"]["value"], decode(r)) for s, r in zip(samples, readings, strict=True)]
    print(_report(summarize(pairs)))
    if args.out:
        with args.out.open("w", encoding="utf-8") as out:
            for sample, reading, (gold, read) in zip(samples, readings, pairs, strict=True):
                scored = {f"{r}.{f}": o.value for (r, f), o in outcomes(gold, read).items()}
                out.write(
                    json.dumps({"prompt": sample["input"]["prompt"], "reading": reading, "outcomes": scored}) + "\n"
                )


if __name__ == "__main__":
    main()

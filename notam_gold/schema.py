"""The NOTAMExtraction schema: loading, validation, and canonical ordering."""

import json
from dataclasses import dataclass
from functools import cache

from jsonschema import Draft202012Validator

from notam_gold.paths import SCHEMA_FILE

CLOSURE_ORDER = {"none": 0, "full": 1, "partial": 2}


@dataclass(frozen=True)
class Problem:
    """A validation failure at a JSON path such as ``effects[0].closedLength``."""

    path: str
    message: str

    def to_dict(self) -> dict:
        return {"path": self.path, "message": self.message}


@cache
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def schema_version() -> str:
    return schema()["schemaVersion"]


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(schema())


def _json_path(parts) -> str:
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else part)
    return path


def _problem(error) -> Problem:
    """Report a failed nullable ``anyOf`` at the non-null branch's deepest error, in plain words."""
    while error.validator == "anyOf" and error.context:
        error = max(error.context, key=lambda e: len(e.absolute_path))
    message = "Enter a value" if error.validator == "type" and error.instance is None else error.message
    return Problem(_json_path(error.absolute_path), message)


def validate(extraction: dict) -> list[Problem]:
    """All schema and semantic problems with ``extraction``; empty when it is valid."""
    problems = [_problem(error) for error in _validator().iter_errors(extraction)]
    if problems:
        return problems
    return list(_semantic_problems(extraction))


def _semantic_problems(extraction: dict):
    effects = extraction["effects"]
    if extraction["isCanceled"] and effects:
        yield Problem("effects", "A cancelled NOTAM has no effects")
    seen = set()
    for index, effect in enumerate(effects):
        yield from _effect_problems(f"effects[{index}]", effect)
        key = json.dumps(effect, sort_keys=True)
        if key in seen:
            yield Problem(f"effects[{index}]", "Duplicate effect")
        seen.add(key)


def _is_single_direction(runway: str | None) -> bool:
    return runway is not None and "/" not in runway


def _effect_problems(path: str, effect: dict):
    if effect["closure"] != "partial":
        for field in ("closedLength", "closedEnd"):
            if effect[field] is not None:
                yield Problem(f"{path}.{field}", f'{field} requires closure "partial"')
    for field in ("declaredDistances", "thresholdDisplacement"):
        if effect[field] is not None and not _is_single_direction(effect["runway"]):
            yield Problem(f"{path}.runway", f"{field} requires a single-direction runway")
    if effect["closure"] == "none" and all(effect[f] is None for f in _FACT_FIELDS):
        yield Problem(path, "Effect states nothing; remove it")
    for field in ("closedLength", "thresholdDisplacement"):
        yield from _positive(f"{path}.{field}", effect[field])
    if (distances := effect["declaredDistances"]) is not None:
        if all(value is None for value in distances.values()):
            yield Problem(f"{path}.declaredDistances", "No declared distance stated; use null")
        for name, length in distances.items():
            yield from _positive(f"{path}.declaredDistances.{name}", length)
    if (condition := effect["surfaceCondition"]) is not None:
        yield from _surface_problems(f"{path}.surfaceCondition", condition)
    if (obstacle := effect["obstacle"]) is not None:
        yield from _obstacle_problems(f"{path}.obstacle", obstacle)


_FACT_FIELDS = (
    "closedLength",
    "closedEnd",
    "thresholdDisplacement",
    "declaredDistances",
    "surfaceCondition",
    "obstacle",
)


def _positive(path: str, measure: dict | None):
    if measure is not None and measure["value"] <= 0:
        yield Problem(path, "Must be greater than zero")


def _surface_problems(path: str, condition: dict):
    codes = condition["rwyCC"]
    if codes is not None and len(codes) not in (1, 3):
        yield Problem(f"{path}.rwyCC", "Report one code or one per third")
    thirds = [c["runwayThird"] for c in condition["contaminants"]]
    if any(t is None for t in thirds) and any(t is not None for t in thirds):
        yield Problem(f"{path}.contaminants", "Give every contaminant a runwayThird, or none of them")
    for index, contaminant in enumerate(condition["contaminants"]):
        yield from _positive(f"{path}.contaminants[{index}].depth", contaminant["depth"])


def _obstacle_problems(path: str, obstacle: dict):
    if all(value is None for value in obstacle.values()):
        yield Problem(path, "Obstacle states nothing; use null")
    if (obstacle["latitude"] is None) != (obstacle["longitude"] is None):
        yield Problem(f"{path}.latitude", "Latitude and longitude come as a pair")
    for field in ("heightAGL", "heightMSL", "distance"):
        yield from _positive(f"{path}.{field}", obstacle[field])


def _effect_sort_key(effect: dict):
    runway = effect["runway"]
    return (
        runway is not None,
        runway or "",
        CLOSURE_ORDER[effect["closure"]],
        effect["thresholdDisplacement"] is not None,
        effect["declaredDistances"] is not None,
        effect["surfaceCondition"] is not None,
        effect["obstacle"] is not None,
    )


def _contaminant_sort_key(contaminant: dict):
    third = contaminant["runwayThird"]
    return third is not None, third or 0, contaminant["type"]


def canonicalize(extraction: dict) -> dict:
    """A copy with effects and contaminants in the canonical order defined in SCHEMA.md."""
    effects = []
    for effect in sorted(extraction["effects"], key=_effect_sort_key):
        if (condition := effect["surfaceCondition"]) is not None:
            contaminants = sorted(condition["contaminants"], key=_contaminant_sort_key)
            effect = {**effect, "surfaceCondition": {**condition, "contaminants": contaminants}}
        effects.append(effect)
    return {**extraction, "effects": effects}

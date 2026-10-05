"""The NOTAMExtraction schema: loading, validation, and canonical ordering."""

import json
from dataclasses import dataclass
from functools import cache

from jsonschema import Draft202012Validator

from notam_gold.paths import SCHEMA_FILE

RELATIVE_ENDS = ("thresholdEnd", "departureEnd")
SHORTENING_FIELDS = ("partialClosure", "thresholdDisplacement", "declaredDistances")
RUNWAY_END_REFERENCES = ("departureEnd", "threshold")
_FACT_FIELDS = (*SHORTENING_FIELDS, "surfaceCondition")


@dataclass(frozen=True)
class Problem:
    """A validation failure at a JSON path such as ``effects[0].partialClosure.length``."""

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
    effects, obstacles = extraction["effects"], extraction["obstacles"]
    if extraction["isCanceled"]:
        if effects:
            yield Problem("effects", "A cancelled NOTAM has no effects")
        if obstacles:
            yield Problem("obstacles", "A cancelled NOTAM has no obstacles")
    seen = set()
    for index, effect in enumerate(effects):
        path = f"effects[{index}]"
        if effect["runway"] in seen:
            yield Problem(path, f"Combine this with the other effect for runway {effect['runway'] or 'the aerodrome'}")
        seen.add(effect["runway"])
        yield from _effect_problems(path, effect)
    for index, obstacle in enumerate(obstacles):
        yield from _obstacle_problems(f"obstacles[{index}]", obstacle)


def _effect_problems(path: str, effect: dict):
    if effect["closure"] == "none" and all(effect[f] is None for f in _FACT_FIELDS):
        yield Problem(path, "Effect states nothing; remove it")
    yield from _closure_problems(path, effect)
    if effect["runway"] is None:
        for field in SHORTENING_FIELDS:
            if effect[field] is not None:
                yield Problem(f"{path}.runway", f"{field} requires a runway")
    if (portion := effect["partialClosure"]) is not None:
        yield from _positive(f"{path}.partialClosure.length", portion["length"])
    yield from _positive(f"{path}.thresholdDisplacement", effect["thresholdDisplacement"])
    if (distances := effect["declaredDistances"]) is not None:
        yield from _declared_problems(f"{path}.declaredDistances", distances)
    if (condition := effect["surfaceCondition"]) is not None:
        yield from _surface_problems(f"{path}.surfaceCondition", condition)


def _closure_problems(path: str, effect: dict):
    closure = effect["closure"]
    if closure == "both":
        for field in SHORTENING_FIELDS:
            if effect[field] is not None:
                yield Problem(f"{path}.{field}", "A runway closed for takeoff and landing takes no shortening")
        return
    distances = effect["declaredDistances"] or {}
    for operation, distance in (("takeoff", "TORA"), ("landing", "LDA")):
        if closure == operation and distances.get(distance) is not None:
            yield Problem(
                f"{path}.declaredDistances.{distance}", f"A runway closed for {operation} has no {distance}; use null"
            )


def _declared_problems(path: str, distances: dict):
    if all(value is None for value in distances.values()):
        yield Problem(path, "No declared distance stated; use null")
    for name, distance in distances.items():
        yield from _positive(f"{path}.{name}", distance)


def _positive(path: str, measure: dict | None):
    if measure is not None and measure["value"] <= 0:
        yield Problem(path, "Must be greater than zero")


def _surface_problems(path: str, condition: dict):
    codes = condition["rwyCC"]
    if codes is not None and len(codes) not in (1, 3):
        yield Problem(f"{path}.rwyCC", "Report one code or one per third")
    for index, contaminant in enumerate(condition["contaminants"]):
        yield from _positive(f"{path}.contaminants[{index}].depth", contaminant["depth"])


def _obstacle_problems(path: str, obstacle: dict):
    if obstacle["height"] is None and obstacle["distance"] is None:
        yield Problem(path, "Obstacle states nothing; remove it")
    for field in ("height", "distance"):
        yield from _positive(f"{path}.{field}", obstacle[field])
    reference = obstacle["reference"]
    if (obstacle["distance"] is None) != (reference is None):
        yield Problem(f"{path}.reference", "A distance and its reference come as a pair")
    if reference is not None and (reference["kind"] in RUNWAY_END_REFERENCES) != (reference["runway"] is not None):
        yield Problem(f"{path}.reference.runway", "A runway end names its runway; ARP and other references name none")


def _effect_sort_key(effect: dict):
    runway = effect["runway"]
    return runway is not None, runway or ""


def _obstacle_sort_key(obstacle: dict):
    reference = obstacle["reference"] or {}
    return (
        reference.get("runway") or "",
        reference.get("kind") or "",
        (obstacle["height"] or {}).get("value", 0),
        (obstacle["distance"] or {}).get("value", 0),
        str(obstacle["direction"]),
    )


def _contaminant_sort_key(contaminant: dict):
    depth = contaminant["depth"] or {}
    coverage = contaminant["coveragePercent"]
    return contaminant["type"], -1 if coverage is None else coverage, depth.get("value", -1), depth.get("unit", "")


def _distinct(contaminants: list[dict]) -> list[dict]:
    seen, kept = set(), []
    for contaminant in contaminants:
        key = json.dumps(contaminant, sort_keys=True)
        if key not in seen:
            seen.add(key)
            kept.append(contaminant)
    return kept


def canonicalize(extraction: dict) -> dict:
    """A copy with effects, obstacles and contaminants in the canonical order defined in SCHEMA.md."""
    effects = []
    for effect in sorted(extraction["effects"], key=_effect_sort_key):
        if (condition := effect["surfaceCondition"]) is not None:
            contaminants = sorted(_distinct(condition["contaminants"]), key=_contaminant_sort_key)
            effect = {**effect, "surfaceCondition": {**condition, "contaminants": contaminants}}
        effects.append(effect)
    obstacles = sorted(extraction["obstacles"], key=_obstacle_sort_key)
    return {**extraction, "effects": effects, "obstacles": obstacles}

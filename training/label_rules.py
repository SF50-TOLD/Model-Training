"""Corrections for silver-label conventions both labelling runs get wrong alike.

The agreement filter can't catch an error both runs make, so these rules bring training labels in
line with SCHEMA.md and the reviewed gold set. They only ever remove what a label states, never add
to it, and they never touch gold.

- A runway closed only for landing or only for takeoff (`RWY 20 CLSD LDG`, `LDG RWY 16R NOT AVBL`)
  is not a closure (SCHEMA.md scope rule), unless the text also closes that runway outright.
- An obstacle published in an en-route obstacle list (AIP ENR 5.4, low-flying-zone and vertical
  obstacle lists) isn't in an aerodrome environment, so it isn't recorded.
"""

import copy
import re

_OPERATION = r"(?:LDG|LANDING|LANDINGS|TKOF|TAKE-?OFF|TAKE-?OFFS|ARR|DEP)"
_DESIGNATOR = r"(\d{1,2}[LCR]?(?:\s*/\s*\d{1,2}[LCR]?)?)"
_CLOSED = r"(?:CLSD|CLOSED|NOT AVBL|NOT AVAILABLE)"
_ONE_DIRECTION = [
    re.compile(rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}\s+(?:FOR\s+|TO\s+)?{_OPERATION}\b"),
    re.compile(rf"\b{_OPERATION}\s+(?:ON\s+|FM\s+|FROM\s+)?RWY\s*{_DESIGNATOR}\s+{_CLOSED}"),
]
_OUTRIGHT = re.compile(rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}(?!\s+(?:FOR\s+|TO\s+)?{_OPERATION}\b)")
_STATED_FIELDS = (
    "closedLength",
    "closedEnd",
    "thresholdDisplacement",
    "declaredDistances",
    "surfaceCondition",
    "obstacle",
)
_EN_ROUTE_LIST = re.compile(r"\bENR\s*5\.4|\bLOW FLYING ZONE\b|\bVERTICAL OBSTACLES\b")


def corrected(label: dict, notam_text: str) -> dict:
    """``label`` with the conventions above applied to it."""
    text = " ".join(notam_text.upper().split())
    fixed = copy.deepcopy(label)
    one_direction = _designators(_ONE_DIRECTION, text) - _outright_closures(text)
    en_route = bool(_EN_ROUTE_LIST.search(text))
    for effect in fixed["effects"]:
        if effect["closure"] == "full" and effect["runway"] in one_direction:
            effect["closure"] = "none"
        if en_route:
            effect["obstacle"] = None
    fixed["effects"] = [e for e in fixed["effects"] if _states_something(e)]
    return fixed


def _designators(patterns: list[re.Pattern], text: str) -> set[str]:
    found = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            found |= _normalized(match.group(1))
    return found


def _outright_closures(text: str) -> set[str]:
    """Runways the text closes without naming an operation (`LDG RWY 16R NOT AVBL` isn't one)."""
    qualified = [m.span() for m in _ONE_DIRECTION[1].finditer(text)]
    found = set()
    for match in _OUTRIGHT.finditer(text):
        if not any(start <= match.start() < end for start, end in qualified):
            found |= _normalized(match.group(1))
    return found


def _normalized(written: str) -> set[str]:
    """The written designator and, for a pair, each direction and the pair, zero-padded."""
    directions = [part.strip() for part in written.split("/")]
    padded = [f"{int(re.match(r'\d+', d).group()):02d}{d.lstrip('0123456789')}" for d in directions]
    return {*padded, "/".join(padded)}


def _states_something(effect: dict) -> bool:
    return effect["closure"] != "none" or any(effect[key] is not None for key in _STATED_FIELDS)

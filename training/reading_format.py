"""The compact text the on-device model writes: one line per runway direction and per obstacle.

Every token the model emits costs a decode step, so the model writes this instead of the schema's
JSON, and the app reads it back into a `NOTAMExtraction` (the Swift twin of `decode`). The mapping is
exact both ways for every schema value, and `encode` writes the canonical form: effects, obstacles and
contaminants in canonical order, fields in a fixed order, numbers in their shortest form.

    CNL                         the NOTAM is a cancellation
    NIL                         nothing affects runway performance
    RWY <rwy|*> [CLSD [TKOF|LDG]] [PART [<len>] [END <end>]] [DTHR <len>] [TORA <len>] [LDA <len>]
        [SFC [CC <n>[/<n>/<n>]] <contaminant>[,<contaminant>...]|-]
    OBST [AGL <len>|MSL <len>] [DIST <len> DER <rwy>|THR <rwy>|ARP|OTHER] [DIR <compass>|<degrees>]

`CLSD` alone closes the direction to both operations. A length is a number and its unit (`1713ft`,
`0.125in`, `2.2nm`); a contaminant is its type with its coverage and depth when stated
(`drySnow%30~0.125in`); `*` is the aerodrome. A distance is always followed by what it is measured
from, and a direction is a 16-point compass word or a bare number of degrees.
"""

import re

from notam_gold.schema import canonicalize

CANCELED, NOTHING, AERODROME, ABSENT = "CNL", "NIL", "*", "-"
DECLARED = ("TORA", "LDA")
_CLOSURES = {"both": [], "takeoff": ["TKOF"], "landing": ["LDG"]}
_CLOSURE_TAGS = {tag: closure for closure, tags in _CLOSURES.items() for tag in tags}
_REFERENCES = {"departureEnd": "DER", "threshold": "THR", "ARP": "ARP", "other": "OTHER"}
_REFERENCE_TAGS = {tag: kind for kind, tag in _REFERENCES.items()}
_RUNWAY_END_REFERENCES = ("departureEnd", "threshold")
_MEASURE = re.compile(r"^(\d+(?:\.\d+)?)(ft|m|nm|in|mm)$")
_CONTAMINANT = re.compile(r"^([A-Za-z]+)(?:%(\d{1,3}))?(?:~(\S+))?$")
_DEGREES = re.compile(r"^\d+(?:\.\d+)?$")


def number(value: float) -> str:
    """The shortest exact decimal for ``value``, never in exponent form."""
    if float(value).is_integer():
        return str(int(value))
    return format(value, "f").rstrip("0") if "e" in repr(value) else repr(float(value))


def measure(value: dict) -> str:
    return f"{number(value['value'])}{value['unit']}"


def encode(extraction: dict) -> str:
    """The reading of ``extraction``."""
    if extraction["isCanceled"]:
        return CANCELED
    canonical = canonicalize(extraction)
    lines = [_effect(e) for e in canonical["effects"]] + [_obstacle(o) for o in canonical["obstacles"]]
    return "\n".join(lines) if lines else NOTHING


def _effect(effect: dict) -> str:
    parts = ["RWY", effect["runway"] or AERODROME]
    if effect["closure"] != "none":
        parts += ["CLSD", *_CLOSURES[effect["closure"]]]
    if (portion := effect["partialClosure"]) is not None:
        parts += ["PART"] + ([measure(portion["length"])] if portion["length"] else [])
        parts += ["END", portion["end"]] if portion["end"] else []
    if effect["thresholdDisplacement"]:
        parts += ["DTHR", measure(effect["thresholdDisplacement"])]
    if declared := effect["declaredDistances"]:
        parts += [part for k in DECLARED if declared[k] for part in (k, measure(declared[k]))]
    if condition := effect["surfaceCondition"]:
        parts += ["SFC"]
        if condition["rwyCC"] is not None:
            parts += ["CC", "/".join(str(code) for code in condition["rwyCC"])]
        parts += [",".join(map(_contaminant, condition["contaminants"])) or ABSENT]
    return " ".join(parts)


def _contaminant(contaminant: dict) -> str:
    text = contaminant["type"]
    if contaminant["coveragePercent"] is not None:
        text += f"%{contaminant['coveragePercent']}"
    if contaminant["depth"]:
        text += f"~{measure(contaminant['depth'])}"
    return text


def _obstacle(obstacle: dict) -> str:
    parts = ["OBST"]
    if obstacle["height"]:
        parts += [obstacle["height"]["datum"], measure(obstacle["height"])]
    if obstacle["distance"]:
        reference = obstacle["reference"]
        parts += ["DIST", measure(obstacle["distance"]), _REFERENCES[reference["kind"]]]
        parts += [reference["runway"]] if reference["runway"] else []
    if obstacle["direction"] is not None:
        direction = obstacle["direction"]
        parts += ["DIR", direction if isinstance(direction, str) else number(direction)]
    return " ".join(parts)


def decode(text: str) -> dict:
    """The extraction ``text`` states; raises ``ValueError`` for text outside the format."""
    extraction = {"isCanceled": text == CANCELED, "effects": [], "obstacles": []}
    if text in (CANCELED, NOTHING):
        return extraction
    for line in text.split("\n"):
        tokens = line.split(" ")
        if _take(tokens, "OBST"):
            extraction["obstacles"].append(_decode_obstacle(tokens))
        else:
            extraction["effects"].append(_decode_effect(tokens))
        if tokens:
            raise ValueError(f"unexpected {tokens[0]!r} in {line!r}")
    return extraction


def _decode_effect(tokens: list[str]) -> dict:
    effect = {
        "runway": None,
        "closure": "none",
        "partialClosure": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
    }
    _expect(tokens, "RWY")
    runway = _pop(tokens)
    effect["runway"] = None if runway == AERODROME else runway
    if _take(tokens, "CLSD"):
        effect["closure"] = _CLOSURE_TAGS[_pop(tokens)] if tokens and tokens[0] in _CLOSURE_TAGS else "both"
    if _take(tokens, "PART"):
        effect["partialClosure"] = _decode_partial_closure(tokens)
    if _take(tokens, "DTHR"):
        effect["thresholdDisplacement"] = _measure(_pop(tokens))
    declared = {k: _measure(_pop(tokens)) if _take(tokens, k) else None for k in DECLARED}
    if any(declared.values()):
        effect["declaredDistances"] = declared
    if _take(tokens, "SFC"):
        codes = [int(c) for c in _pop(tokens).split("/")] if _take(tokens, "CC") else None
        listed = _pop(tokens)
        contaminants = [] if listed == ABSENT else [_decode_contaminant(c) for c in listed.split(",")]
        effect["surfaceCondition"] = {"rwyCC": codes, "contaminants": contaminants}
    return effect


def _decode_partial_closure(tokens: list[str]) -> dict:
    portion = {"length": None, "end": None}
    if tokens and _MEASURE.match(tokens[0]):
        portion["length"] = _measure(_pop(tokens))
    if _take(tokens, "END"):
        portion["end"] = _pop(tokens)
    return portion


def _decode_obstacle(tokens: list[str]) -> dict:
    obstacle = {"height": None, "distance": None, "reference": None, "direction": None}
    if tokens and tokens[0] in ("AGL", "MSL"):
        datum = _pop(tokens)
        obstacle["height"] = {**_measure(_pop(tokens)), "datum": datum}
    if _take(tokens, "DIST"):
        obstacle["distance"] = _measure(_pop(tokens))
        obstacle["reference"] = _decode_reference(tokens)
    if _take(tokens, "DIR"):
        direction = _pop(tokens)
        obstacle["direction"] = _number(direction) if _DEGREES.match(direction) else direction
    return obstacle


def _decode_reference(tokens: list[str]) -> dict:
    if not tokens or tokens[0] not in _REFERENCE_TAGS:
        raise ValueError("a distance needs its reference")
    kind = _REFERENCE_TAGS[_pop(tokens)]
    if kind not in _RUNWAY_END_REFERENCES:
        return {"kind": kind, "runway": None}
    if not tokens:
        raise ValueError("a runway end names its runway")
    return {"kind": kind, "runway": _pop(tokens)}


def _decode_contaminant(text: str) -> dict:
    match = _CONTAMINANT.match(text)
    if not match:
        raise ValueError(f"not a contaminant: {text!r}")
    kind, coverage, depth = match.groups()
    return {
        "type": kind,
        "coveragePercent": int(coverage) if coverage else None,
        "depth": _measure(depth) if depth else None,
    }


def _pop(tokens: list[str]) -> str:
    if not tokens:
        raise ValueError("the reading ends where a value was expected")
    return tokens.pop(0)


def _take(tokens: list[str], tag: str) -> bool:
    if tokens and tokens[0] == tag:
        tokens.pop(0)
        return True
    return False


def _expect(tokens: list[str], tag: str):
    if not _take(tokens, tag):
        raise ValueError(f"expected {tag}")


def _number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def _measure(text: str) -> dict:
    match = _MEASURE.match(text)
    if not match:
        raise ValueError(f"not a measurement: {text!r}")
    return {"value": _number(match.group(1)), "unit": match.group(2)}

"""The compact text the on-device model writes: one line per runway effect, only what is stated.

Every token the model emits costs a decode step, so the model writes this instead of the schema's
JSON, and the app reads it back into a `NOTAMExtraction` (the Swift twin of `decode`). The mapping is
exact both ways for every schema value, and `encode` writes the canonical form: effects and
contaminants in canonical order, fields in a fixed order, numbers in their shortest form.

    CNL                         the NOTAM is a cancellation
    NIL                         nothing affects runway performance
    RWY <rwy|*> [CLSD [PART]] [LEN <len>] [END <end>] [DTHR <len>]
        [DD [TORA <len>] [TODA <len>] [ASDA <len>] [LDA <len>]]
        [SFC [CC <n>[/<n>...]] <contaminant>[,<contaminant>...]|-]
        [OBST [AGL <len>] [MSL <len>] [DIST <len>] [REF "<text>"] [BRG <n>] [POS <lat> <lon>]]

A length is a number and its unit (`1713ft`, `0.125in`, `2.2nm`); a contaminant is its type with its
third, coverage and depth when stated (`drySnowOverCompactedSnow@2%30~0.125in`); `*` is the aerodrome.
A position is copied as the NOTAM writes it in degrees, minutes and seconds (`POS 453036N 0732322W`),
so the model never does the conversion; decimal degrees are written only when the text has no DMS
position that converts exactly to the label's.
"""

import re

from notam_gold.schema import canonicalize

CANCELED, NOTHING, AERODROME, ABSENT = "CNL", "NIL", "*", "-"
DECLARED = ("TORA", "TODA", "ASDA", "LDA")
_MEASURE = re.compile(r"^(\d+(?:\.\d+)?)(ft|m|nm|in|mm)$")
_DMS_PAIR = re.compile(
    r"(?<!\d)(\d{4}\d{2}(?:\.\d{1,3})?)\s?([NS])\s*[/,]?\s*(\d{5}\d{2}(?:\.\d{1,3})?)\s?([EW])(?![A-Z])"
)
_DMS = re.compile(r"^(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)([NSEW])$")
_CONTAMINANT = re.compile(r"^([A-Za-z]+)(?:@([1-3]))?(?:%(\d{1,3}))?(?:~(\S+))?$")


def number(value: float) -> str:
    """The shortest exact decimal for ``value``, never in exponent form."""
    if float(value).is_integer():
        return str(int(value))
    return format(value, "f").rstrip("0") if "e" in repr(value) else repr(float(value))


def reference(text: str) -> str:
    """A distance reference on one line, without double quotes; the reference is never scored."""
    return " ".join(text.replace('"', "'").split())


def measure(value: dict) -> str:
    return f"{number(value['value'])}{value['unit']}"


def encode(extraction: dict, text: str = "") -> str:
    """The reading of ``extraction``; ``text``, the NOTAM, supplies positions as written."""
    if extraction["isCanceled"]:
        return CANCELED
    effects = canonicalize(extraction)["effects"]
    positions = _written_positions(text)
    return "\n".join(_effect(e, positions) for e in effects) if effects else NOTHING


def decimal_degrees(written: str) -> float | None:
    """Decimal degrees for a DMS coordinate (`453036N`), north and east positive, to 6 places."""
    match = _DMS.match(written)
    if not match:
        return None
    degrees, minutes, seconds, hemisphere = int(match[1]), int(match[2]), float(match[3]), match[4]
    if minutes >= 60 or seconds >= 60:
        return None
    value = round(degrees + (minutes + seconds / 60) / 60, 6)
    return -value if hemisphere in "SW" else value


def _written_positions(text: str) -> list[tuple[str, str]]:
    return [(a + b, c + d) for a, b, c, d in _DMS_PAIR.findall(" ".join(text.split()))]


def _position(obstacle: dict, positions: list[tuple[str, str]]) -> list[str]:
    for latitude, longitude in positions:
        if decimal_degrees(latitude) == obstacle["latitude"] and decimal_degrees(longitude) == obstacle["longitude"]:
            return [latitude, longitude]
    return [number(obstacle["latitude"]), number(obstacle["longitude"])]


def _effect(effect: dict, positions: list[tuple[str, str]]) -> str:
    parts = ["RWY", effect["runway"] or AERODROME]
    if effect["closure"] != "none":
        parts += ["CLSD"] + (["PART"] if effect["closure"] == "partial" else [])
    if effect["closedLength"]:
        parts += ["LEN", measure(effect["closedLength"])]
    if effect["closedEnd"]:
        parts += ["END", effect["closedEnd"]]
    if effect["thresholdDisplacement"]:
        parts += ["DTHR", measure(effect["thresholdDisplacement"])]
    if declared := effect["declaredDistances"]:
        parts += ["DD"] + [part for k in DECLARED if declared[k] for part in (k, measure(declared[k]))]
    if condition := effect["surfaceCondition"]:
        parts += ["SFC"]
        if condition["rwyCC"] is not None:
            parts += ["CC", "/".join(str(code) for code in condition["rwyCC"])]
        parts += [",".join(map(_contaminant, condition["contaminants"])) or ABSENT]
    if obstacle := effect["obstacle"]:
        parts += ["OBST"] + _obstacle(obstacle, positions)
    return " ".join(parts)


def _contaminant(contaminant: dict) -> str:
    text = contaminant["type"]
    if contaminant["runwayThird"] is not None:
        text += f"@{contaminant['runwayThird']}"
    if contaminant["coveragePercent"] is not None:
        text += f"%{contaminant['coveragePercent']}"
    if contaminant["depth"]:
        text += f"~{measure(contaminant['depth'])}"
    return text


def _obstacle(obstacle: dict, positions: list[tuple[str, str]]) -> list[str]:
    parts = []
    for key, tag in (("heightAGL", "AGL"), ("heightMSL", "MSL"), ("distance", "DIST")):
        if obstacle[key]:
            parts += [tag, measure(obstacle[key])]
    if obstacle["distanceReference"] is not None:
        parts += ["REF", f'"{reference(obstacle["distanceReference"])}"']
    if obstacle["bearingDegrees"] is not None:
        parts += ["BRG", number(obstacle["bearingDegrees"])]
    if obstacle["latitude"] is not None:
        parts += ["POS"] + _position(obstacle, positions)
    return parts


def decode(text: str) -> dict:
    """The extraction ``text`` states; raises ``ValueError`` for text outside the format."""
    if text == CANCELED:
        return {"isCanceled": True, "effects": []}
    if text == NOTHING:
        return {"isCanceled": False, "effects": []}
    return {"isCanceled": False, "effects": [_decode_effect(line) for line in text.split("\n")]}


def _decode_effect(line: str) -> dict:
    tokens = _tokens(line)
    effect = {
        "runway": None,
        "closure": "none",
        "closedLength": None,
        "closedEnd": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
        "obstacle": None,
    }
    _expect(tokens, "RWY")
    runway = tokens.pop(0)
    effect["runway"] = None if runway == AERODROME else runway
    if _take(tokens, "CLSD"):
        effect["closure"] = "partial" if _take(tokens, "PART") else "full"
    if _take(tokens, "LEN"):
        effect["closedLength"] = _measure(tokens.pop(0))
    if _take(tokens, "END"):
        effect["closedEnd"] = tokens.pop(0)
    if _take(tokens, "DTHR"):
        effect["thresholdDisplacement"] = _measure(tokens.pop(0))
    if _take(tokens, "DD"):
        effect["declaredDistances"] = {k: _measure(tokens.pop(0)) if _take(tokens, k) else None for k in DECLARED}
    if _take(tokens, "SFC"):
        codes = [int(c) for c in tokens.pop(0).split("/")] if _take(tokens, "CC") else None
        listed = tokens.pop(0)
        contaminants = [] if listed == ABSENT else [_decode_contaminant(c) for c in listed.split(",")]
        effect["surfaceCondition"] = {"rwyCC": codes, "contaminants": contaminants}
    if _take(tokens, "OBST"):
        effect["obstacle"] = _decode_obstacle(tokens)
    if tokens:
        raise ValueError(f"unexpected {tokens[0]!r} in {line!r}")
    return effect


def _decode_obstacle(tokens: list[str]) -> dict:
    obstacle = dict.fromkeys(
        ("heightAGL", "heightMSL", "distance", "distanceReference", "bearingDegrees", "latitude", "longitude")
    )
    for key, tag in (("heightAGL", "AGL"), ("heightMSL", "MSL"), ("distance", "DIST")):
        if _take(tokens, tag):
            obstacle[key] = _measure(tokens.pop(0))
    if _take(tokens, "REF"):
        obstacle["distanceReference"] = tokens.pop(0)[1:-1]
    if _take(tokens, "BRG"):
        obstacle["bearingDegrees"] = _number(tokens.pop(0))
    if _take(tokens, "POS"):
        obstacle["latitude"], obstacle["longitude"] = (_coordinate(tokens.pop(0)) for _ in range(2))
    return obstacle


def _decode_contaminant(text: str) -> dict:
    match = _CONTAMINANT.match(text)
    if not match:
        raise ValueError(f"not a contaminant: {text!r}")
    kind, third, coverage, depth = match.groups()
    return {
        "type": kind,
        "runwayThird": int(third) if third else None,
        "coveragePercent": int(coverage) if coverage else None,
        "depth": _measure(depth) if depth else None,
    }


def _tokens(line: str) -> list[str]:
    """Space-separated tokens, keeping a quoted reference whole."""
    return re.findall(r'"[^"]*"|\S+', line)


def _take(tokens: list[str], tag: str) -> bool:
    if tokens and tokens[0] == tag:
        tokens.pop(0)
        return True
    return False


def _expect(tokens: list[str], tag: str):
    if not _take(tokens, tag):
        raise ValueError(f"expected {tag}")


def _coordinate(text: str) -> int | float:
    converted = decimal_degrees(text)
    return _number(text) if converted is None else converted


def _number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def _measure(text: str) -> dict:
    match = _MEASURE.match(text)
    if not match:
        raise ValueError(f"not a measurement: {text!r}")
    return {"value": _number(match.group(1)), "unit": match.group(2)}

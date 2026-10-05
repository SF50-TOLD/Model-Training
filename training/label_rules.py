"""Corrections for silver-label conventions both labelling runs get wrong alike.

The agreement filter can't catch an error both runs make, so these rules bring training labels in
line with SCHEMA.md and the reviewed gold set. They only ever remove what a label states, never add
to it, and they never touch gold.

- An obstacle published in an en-route obstacle list (AIP ENR 5.4, low-flying-zone and vertical
  obstacle lists) isn't in an aerodrome environment, so it isn't recorded.
- A runway closed only at stated times (`RWY 13/31 CLSD DLY 0401-0900`, `RWY 16/34 CLSD AFTER LAST SKED
  INTL ARR`) isn't recorded as closed.
- A runway closed with exceptions that include the SF50 (`RWY 27 CLSD EXC ACFT WINGSPAN LESS THAN
  119FT`) is in effect closed only to larger aircraft, so it isn't recorded as closed.
- A list of published obstacles in an ODP's takeoff minimum notes (`TAKE OFF MINIMUM NOTES: OBSTACLES
  TREE …`) isn't recorded; a temporary obstacle the procedure adds still is.
- A threshold "further displaced" by some distance states only the increment, not the displacement,
  so no displacement is recorded unless the text also states the total (`TOTAL DISPLACEMENT 1970FT`).
"""

import copy
import re

from notam_gold.schema import SHORTENING_FIELDS

_DESIGNATOR = r"(\d{1,2}[LCR]?(?:\s*/\s*\d{1,2}[LCR]?)?)"
_CLOSED = r"(?:CLSD|CLOSED|NOT AVBL|NOT AVAILABLE)"
_STATED_FIELDS = (*SHORTENING_FIELDS, "surfaceCondition")
_EN_ROUTE_LIST = re.compile(r"\bENR\s*5\.4|\bLOW FLYING ZONE\b|\bVERTICAL OBSTACLES\b")
_AT_STATED_TIMES = re.compile(
    rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}\b[^.]{{0,40}}?"
    r"(?:\b(?:DLY|DAILY|MON|TUE|WED|THU|FRI|SAT|SUN)\b|\b\d{4}\s*-\s*\d{4}\b|\bBTN\s+\d{4}\s+AND\s+\d{4}\b"
    r"|\b(?:AFT|AFTER)\s+(?:THE\s+)?LAST\s+(?:SKED|SCHEDULED|PLANNED)\b)"
)
_EXCEPTED_SIZE = re.compile(
    rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}\s+EXC\b[^.]{{0,60}}?\b(?:WINGSPAN|SPAN|MTOW|WEIGHT|WT)\b[^.]{{0,20}}?"
    r"\b(?:LESS THAN|BELOW|UNDER|UP TO|LT)\s+(\d[\d,]*(?:\.\d+)?)\s*(FT|M|KG|LBS?|T)\b"
)
# The SF50's wingspan and maximum takeoff weight, in each unit a size exception may use.
_SF50_SIZE = {"FT": 38.7, "M": 11.8, "KG": 2727, "LB": 6000, "LBS": 6000, "T": 2.727}
_ODP_OBSTACLE_NOTES = re.compile(r"\b(?:TAKE[\s-]?OFF|TKOF)\s+(?:MINIMUMS?|OBSTACLE)\s+NOTES?\b")
_FURTHER_DISPLACED = re.compile(r"\bFURTHER\s+(?:DISPLACED|DSPLCD)\b")
_TOTAL_DISPLACEMENT = re.compile(r"\bTOTAL\s+(?:DISPLACEMENT|DTHR)\b")


def corrected(label: dict, notam_text: str) -> dict:
    """``label`` with the conventions above applied to it."""
    text = " ".join(notam_text.upper().split())
    fixed = copy.deepcopy(label)
    conditional = _directions(_AT_STATED_TIMES, text) | _sf50_excepted_directions(text)
    increment_only = bool(_FURTHER_DISPLACED.search(text)) and not _TOTAL_DISPLACEMENT.search(text)
    for effect in fixed["effects"]:
        if effect["runway"] in conditional:
            effect.update(closure="none", partialClosure=None)
        if increment_only:
            effect["thresholdDisplacement"] = None
    if _EN_ROUTE_LIST.search(text) or _is_published_obstacle_list(text):
        fixed["obstacles"] = []
    fixed["effects"] = [e for e in fixed["effects"] if _states_something(e)]
    return fixed


def _directions(pattern: re.Pattern, text: str) -> set[str]:
    """Each runway direction ``pattern`` names, zero-padded; a pair names both of its directions."""
    return {_padded(part) for match in pattern.finditer(text) for part in match.group(1).split("/")}


def _sf50_excepted_directions(text: str) -> set[str]:
    """Directions closed with a size exception the SF50 falls within."""
    return {
        _padded(part)
        for match in _EXCEPTED_SIZE.finditer(text)
        if float(match.group(2).replace(",", "")) > _SF50_SIZE[match.group(3)]
        for part in match.group(1).split("/")
    }


def _is_published_obstacle_list(text: str) -> bool:
    return bool(_ODP_OBSTACLE_NOTES.search(text)) and "TEMPORARY" not in text


def _padded(written: str) -> str:
    digits = re.match(r"\s*(\d+)", written).group(1)
    return f"{int(digits):02d}{written.strip()[len(digits) :]}"


def _states_something(effect: dict) -> bool:
    return effect["closure"] != "none" or any(effect[key] is not None for key in _STATED_FIELDS)

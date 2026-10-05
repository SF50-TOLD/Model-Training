"""Corrections for silver-label conventions both labelling runs get wrong alike.

The agreement filter can't catch an error both runs make, so these rules bring training labels in
line with SCHEMA.md and the reviewed gold set. They only ever remove what a label states, never add
to it, and they never touch gold.

- An obstacle published in an en-route obstacle list (AIP ENR 5.4, low-flying-zone and vertical
  obstacle lists) isn't in an aerodrome environment, so it isn't recorded.
- A runway closed only after the last scheduled flight (`RWY 16/34 CLSD AFTER LAST SKED INTL ARR`) is
  closed conditionally, and a conditional closure isn't recorded.
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
_AFTER_LAST_FLIGHT = re.compile(
    rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}\s+(?:AFT|AFTER)\s+(?:THE\s+)?LAST\s+(?:SKED|SCHEDULED)\b"
)
_FURTHER_DISPLACED = re.compile(r"\bFURTHER\s+(?:DISPLACED|DSPLCD)\b")
_TOTAL_DISPLACEMENT = re.compile(r"\bTOTAL\s+(?:DISPLACEMENT|DTHR)\b")


def corrected(label: dict, notam_text: str) -> dict:
    """``label`` with the conventions above applied to it."""
    text = " ".join(notam_text.upper().split())
    fixed = copy.deepcopy(label)
    conditional = _directions(_AFTER_LAST_FLIGHT, text)
    increment_only = bool(_FURTHER_DISPLACED.search(text)) and not _TOTAL_DISPLACEMENT.search(text)
    for effect in fixed["effects"]:
        if effect["runway"] in conditional:
            effect.update(closure="none", partialClosure=None)
        if increment_only:
            effect["thresholdDisplacement"] = None
    if _EN_ROUTE_LIST.search(text):
        fixed["obstacles"] = []
    fixed["effects"] = [e for e in fixed["effects"] if _states_something(e)]
    return fixed


def _directions(pattern: re.Pattern, text: str) -> set[str]:
    """Each runway direction ``pattern`` names, zero-padded; a pair names both of its directions."""
    return {_padded(part) for match in pattern.finditer(text) for part in match.group(1).split("/")}


def _padded(written: str) -> str:
    digits = re.match(r"\s*(\d+)", written).group(1)
    return f"{int(digits):02d}{written.strip()[len(digits) :]}"


def _states_something(effect: dict) -> bool:
    return effect["closure"] != "none" or any(effect[key] is not None for key in _STATED_FIELDS)

"""Deterministic stratum tags for NOTAMs, from their text alone.

Tags are a cheap pre-filter for sampling gold candidates. They are not labels:
a NOTAM tagged ``partial_closure`` may turn out, on review, to state nothing.
"""

import re

DECLARED_DISTANCES = "declared_distances"
DISPLACED_THRESHOLD = "displaced_threshold"
PARTIAL_CLOSURE = "partial_closure"
FULL_CLOSURE = "full_closure"
FICON_RWYCC = "ficon_rwycc"
FICON_NO_RWYCC = "ficon_no_rwycc"
OBSTACLE = "obstacle"
CANCELLED = "cancelled"
PLAUSIBLE_NEGATIVE = "plausible_negative"
OTHER_NEGATIVE = "other_negative"

POSITIVE_STRATA = (
    DECLARED_DISTANCES,
    DISPLACED_THRESHOLD,
    PARTIAL_CLOSURE,
    FULL_CLOSURE,
    FICON_RWYCC,
    FICON_NO_RWYCC,
    OBSTACLE,
)
NEGATIVE_STRATA = (PLAUSIBLE_NEGATIVE, OTHER_NEGATIVE)
ALL_STRATA = (*POSITIVE_STRATA, CANCELLED, *NEGATIVE_STRATA)

RUNWAY = r"\b(?:RWY|RUNWAY)\b"
DESIGNATOR = r"\d{1,2}[LCR]?(?:\s*[/-]\s*\d{1,2}[LCR]?)?"
LENGTH = r"\d[\d,]*(?:\.\d+)?\s*(?:FT|M)\b"

_DECLARED = re.compile(r"\b(?:TORA|TODA|ASDA|LDA)\b|DECLARED\s+DIST")
_DISPLACED = re.compile(
    rf"\b(?:DSPLCD|DISPLACED)\b[^.]{{0,20}}?{LENGTH}|{LENGTH}[^.]{{0,20}}?\b(?:DSPLCD|DISPLACED)\b|\bDTHR\s+(?:BY\s+)?{LENGTH}"
)
_CLOSED = r"\b(?:CLSD|CLOSED)\b"
_PARTIAL = re.compile(
    rf"{RUNWAY}\s*{DESIGNATOR}.{{0,80}}?(?:{LENGTH}.{{0,40}}{_CLOSED}|{_CLOSED}.{{0,40}}(?:{LENGTH}|\b(?:FIRST|LAST)\b)"
    rf"|\b[NSEW]{{1,2}}\s+(?:OF\s+TWY|END)\b.{{0,40}}{_CLOSED}|{_CLOSED}\s+(?:BTN|BETWEEN|[NSEW]{{1,2}}\s+OF)\b)",
    re.DOTALL,
)
_FULL = re.compile(rf"{RUNWAY}\s*{DESIGNATOR}\s+{_CLOSED}")
_CLASS_RESTRICTION = re.compile(rf"{_CLOSED}\s+TO\s+(?:ACFT|AIRCRAFT)")
_RUNWAY_FICON = re.compile(
    rf"{RUNWAY}\s*{DESIGNATOR}\s+FICON|\bRSC\s+\d{{2}}|\bSNOWTAM\b|\bRWYCC\b|RWY\s+CONDITION\s+CODE"
)
_MOVEMENT_AREA_FICON = re.compile(r"(?:^|\bE\)\s*)(?:[A-Z]{3,4}\s+)?(?:TWY|APRON|RAMP|TXL)\b[^.]*?\bFICON\b")
_RWYCC = re.compile(
    r"(?:\bFICON|\bRSC\s+\d{2}[LCR]?|\b\d{8}\s+\d{2}[LCR]?)\s+[0-6]/[0-6]/[0-6]\b|\bRWYCC\b|RWY\s+CONDITION\s+CODE"
)
_OBSTACLE = re.compile(r"\b(?:OBST|CRANE|TOWER|RIG|MAST|WIND\s*TURBINE)S?\b")
_OBSTACLE_HEIGHT = re.compile(
    r"\d+\s*(?:FT|M)\s*(?:\(?\s*\d+\s*(?:FT|M)\s*)?(?:AGL|AMSL|MSL)|\bHGT\b|\bELEV\b|\(\d+FT AGL\)"
)
_LIGHT_OUTAGE = re.compile(r"\bLGTS?\b.{0,120}?\b(?:U/S|OTS|INOP|UNSERVICEABLE|OUT OF SERVICE)\b")
_CANCELLED = re.compile(r"\bNOTAMC\b|\bCANCEL+ED\b|\bCNL\b")
_TEMPTING = re.compile(
    rf"{RUNWAY}|\bTHR\b|\bFICON\b|\bOBST\b|\bILS\b|\bPAPI\b|\bVASI\b|\bALS\b|\bREIL\b|\bTWY\b.{{0,40}}\bCLSD\b|\bAPRON\b.{{0,40}}\bFICON\b"
)


def _normalized(text: str) -> str:
    return " ".join(text.upper().split())


def strata(text: str, nms_type: str | None = None) -> list[str]:
    """Every stratum ``text`` belongs to; a NOTAM with no positive or cancelled stratum is one negative stratum."""
    text = _normalized(text)
    tags = []
    if _DECLARED.search(text):
        tags.append(DECLARED_DISTANCES)
    if _DISPLACED.search(text) and "NO LONGER DISPLACED" not in text:
        tags.append(DISPLACED_THRESHOLD)
    if not _CLASS_RESTRICTION.search(text):
        if _PARTIAL.search(text):
            tags.append(PARTIAL_CLOSURE)
        elif _FULL.search(text):
            tags.append(FULL_CLOSURE)
    if _RUNWAY_FICON.search(text) and not _MOVEMENT_AREA_FICON.search(text):
        tags.append(FICON_RWYCC if _RWYCC.search(text) else FICON_NO_RWYCC)
    if _is_obstacle(text):
        tags.append(OBSTACLE)
    if nms_type == "C" or _CANCELLED.search(text):
        tags.append(CANCELLED)
    if not tags:
        tags.append(PLAUSIBLE_NEGATIVE if _TEMPTING.search(text) else OTHER_NEGATIVE)
    return tags


def _is_obstacle(text: str) -> bool:
    return bool(_OBSTACLE.search(text) and _OBSTACLE_HEIGHT.search(text) and not _LIGHT_OUTAGE.search(text))


_TIMES = re.compile(r"\b\d{10}\b|\b\d{4,}(?:[-/]\d+)*\b")
_NOTAM_NUMBERS = re.compile(r"\b[A-Z]?\d+/\d{2,4}\b")


def template_key(icao_location: str, text: str) -> tuple[str, str]:
    """Group reissues of the same NOTAM (FICONs are re-issued every few hours) by masking numbers."""
    masked = _NOTAM_NUMBERS.sub("#", _normalized(text))
    masked = _TIMES.sub("#", masked)
    masked = re.sub(r"\bOBS AT #.*$", "", masked)
    return icao_location, masked.strip()

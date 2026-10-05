"""Rewrite NOTAMs from published datasets into corpus records carrying the text the NOTAM API serves.

The API serves an ICAO NOTAM's E) item (a cancellation keeps its whole message), and an FAA domestic
NOTAM without its accountability header and validity times.
"""

import re
from collections import Counter
from collections.abc import Iterable

from notam_gold import corpus

ICAO_HEADER = re.compile(r"^([A-Z])(\d{4})(\d{2})\s+NOTAM([NRC])\b")
ICAO_ITEM = {item: re.compile(rf"\b{item}\)\s*(\w+)") for item in "ABC"}
ICAO_TEXT = re.compile(r"\bE\)\s*(.*?)(?:\s+[FG]\).*)?\s*$", re.DOTALL)
DOMESTIC = re.compile(r"^!(\w+) (\d+) (\w+) (.*?)\s*(\d{10})-(\d{10}|PERM)(?:EST)?\s*$", re.DOTALL)


def timestamp(value: str | None) -> str | None:
    """An ICAO ``yymmddhhmm`` time as ISO 8601 UTC; None for PERM or a missing time."""
    if not value or not value[:10].isdigit():
        return None
    return f"20{value[:2]}-{value[2:4]}-{value[4:6]}T{value[6:8]}:{value[8:10]}:00Z"


def item(raw: str, letter: str) -> str | None:
    """The first word of an ICAO NOTAM's A), B) or C) item."""
    return match.group(1) if (match := ICAO_ITEM[letter].search(raw)) else None


def e_item(raw: str) -> str | None:
    """An ICAO NOTAM's E) item, without the F) and G) items that may follow it."""
    return body.group(1) if (body := ICAO_TEXT.search(raw)) else None


def record(
    location: str, notam_id: str, text: str, kind: str | None, start: str | None, end: str | None, source: str
) -> dict:
    """A corpus record, in the shape ``corpus.corpus_record`` gives an API NOTAM."""
    return {
        "id": corpus.identity({"icao_location": location, "notam_id": notam_id}),
        "notam_id": notam_id,
        "icao_location": location,
        "effective_start": start,
        "effective_end": end,
        "notam_text": text,
        "nms_type": kind,
        "source": source,
    }


def message_record(location: str, raw: str, domestic_locations: dict[str, str], source: str) -> dict | None:
    """A whole ICAO or FAA domestic NOTAM message as a corpus record.

    None when the message has neither format, or its text or ICAO location can't be recovered.
    ``location`` is the fallback for an ICAO message without an A) item.
    """
    raw = raw.strip()
    if header := ICAO_HEADER.match(raw):
        series, number, year, kind = header.groups()
        location = item(raw, "A") or location.strip()
        text = raw if kind == "C" else (e_item(raw) or "")
        notam_id, start, end = f"{series}{number}/{year}", item(raw, "B"), item(raw, "C")
    elif domestic := DOMESTIC.match(raw):
        accountability, number, designator, body, start, end = domestic.groups()
        location = domestic_locations.get(designator)
        text, notam_id, kind = f"{designator} {body}", f"{accountability} {number}", "N"
    else:
        return None
    if not text or not location:
        return None
    return record(location, notam_id, text, kind, timestamp(start), timestamp(end), source)


def domestic_locations(records: Iterable[dict]) -> dict[str, str]:
    """FAA designators (``SFO``) mapped to ICAO locations (``KSFO``) wherever the corpus pairs them consistently."""
    pairs = Counter()
    for record in records:
        words = record["notam_text"].split(maxsplit=1)
        if words and 3 <= len(words[0]) <= 4 and words[0].isalnum():
            pairs[words[0], record["icao_location"]] += 1
    totals = Counter()
    for (designator, _), count in pairs.items():
        totals[designator] += count
    return {
        designator: location
        for (designator, location), count in pairs.items()
        if count >= 3 and count / totals[designator] >= 0.9
    }

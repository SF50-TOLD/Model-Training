"""Download the NOTAM corpus from the NOTAM API and merge it with older snapshots."""

import gzip
import json
import re
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

import requests

PAGE_SIZE = 500
PAGE_PAUSE_SECONDS = 0.5
MAX_ATTEMPTS = 5

CANCELLATION_TEXT = re.compile(r"\bNOTAMC\b")
NMS_TYPE_XML = re.compile(r"<(?:\w+:)?type>([NRC])</(?:\w+:)?type>")


class NOTAMAPI:
    """Minimal client for the notams.fly.dev list endpoint.

    The endpoint orders by ``effective_start`` descending and pages by offset,
    but deep offsets exceed the server's statement timeout. So pages are walked
    by keyset instead: each request asks for NOTAMs starting at or before the
    oldest ``effective_start`` seen so far (the ``end`` filter).
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def page(self, limit: int = PAGE_SIZE, offset: int = 0, end: str | None = None) -> dict:
        """Fetch one page, retrying transient failures with exponential backoff."""
        params = {"limit": limit, "offset": offset} | ({"end": end} if end else {})
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.session.get(f"{self.base_url}/api/notams", params=params, timeout=90)
                if response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                    return response.json()
            except requests.ConnectionError, requests.Timeout:
                pass
            time.sleep(2**attempt)
        raise RuntimeError(f"Giving up on {params} after {MAX_ATTEMPTS} attempts")

    def total(self) -> int:
        return self.page(limit=1)["pagination"]["total"]

    def sweep(self) -> Iterator[dict]:
        """Yield every NOTAM (with repeats at page boundaries) from newest to oldest effective_start."""
        cursor, offset = None, 0
        while True:
            rows = self.page(offset=offset, end=cursor)["data"]
            yield from rows
            if len(rows) < PAGE_SIZE:
                return
            oldest = min(row["effective_start"] for row in rows)
            # A full page sharing one effective_start can't advance the cursor; step past it by offset.
            offset = offset + len(rows) if oldest == cursor else 0
            cursor = oldest
            time.sleep(PAGE_PAUSE_SECONDS)


def nms_type(notam: dict) -> str | None:
    """The NMS message type (N, R or C), from the raw message or the text's NOTAMC marker."""
    raw = notam.get("raw_message") or ""
    if raw.startswith("{"):
        try:
            found = json.loads(raw)["properties"]["coreNOTAMData"]["notam"].get("type")
        except json.JSONDecodeError, KeyError, TypeError:
            found = None
    else:
        match = NMS_TYPE_XML.search(raw)
        found = match.group(1) if match else None
    if found is None and CANCELLATION_TEXT.search(notam.get("notam_text") or ""):
        return "C"
    return found


def content_key(notam: dict) -> tuple[str, str, str]:
    """Identity that survives the two ingestion paths' different notam_id formats."""
    text = " ".join((notam.get("notam_text") or "").split())
    return notam.get("icao_location") or "", text, notam.get("effective_start") or ""


def identity(notam: dict) -> str:
    """A NOTAM's identity. ``notam_id`` alone is not unique: series numbers repeat between countries."""
    return f"{notam['icao_location']} {notam['notam_id']}"


def merge(*sources: Iterable[dict]) -> list[dict]:
    """Merge snapshots, earlier sources winning, deduplicating on identity and then on content."""
    merged, ids, keys = [], set(), set()
    for source in sources:
        for notam in source:
            key = content_key(notam)
            if notam["id"] in ids or key in keys:
                continue
            ids.add(notam["id"])
            keys.add(key)
            merged.append(notam)
    return merged


def corpus_record(notam: dict, source: str) -> dict:
    """The fields the pipeline keeps, plus the derived NMS type and snapshot source."""
    return {
        "id": identity(notam),
        "notam_id": notam["notam_id"],
        "icao_location": notam["icao_location"],
        "effective_start": notam.get("effective_start"),
        "effective_end": notam.get("effective_end"),
        "notam_text": notam.get("notam_text") or "",
        "nms_type": nms_type(notam),
        "source": source,
    }


def write_jsonl_gz(path: Path, rows: Iterable[dict]) -> int:
    count = 0
    with gzip.open(path, "wt", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        yield from (json.loads(line) for line in file)

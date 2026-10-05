"""Training-corpus NOTAMs from published datasets, downloaded to data/external/<source>/.

- NOTAM-Evolve (https://github.com/Estrellajer/NOTAM-Evolve, Apache 2.0): runway, taxiway, lighting
  and area NOTAMs sampled from 2024 traffic, as ``A) <location> E) <text>`` with neither ID nor times.
- DEEL-AI/NOTAM (https://huggingface.co/datasets/DEEL-AI/NOTAM, MIT): E) items alone. Only those
  whose text names their location unambiguously are kept.
- Polytechnique Montréal's NOTAM_data.xlsx (https://github.com/krooonal/NOTAM_explainable_prediction_data),
  ICAO NOTAMs mostly from 2020. It has no license, so it is opt-in.

Every text is rewritten into the form the NOTAM API serves (see ``notam_gold.rewrite``), with its ends
trimmed and LF line breaks. A record whose ICAO location can't be recovered is skipped: the model's
prompt starts with the location.
"""

import csv
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import requests

from notam_gold import corpus, rewrite
from notam_gold.paths import EXTERNAL_DIR

EVOLVE = "notam-evolve-2024"
DEEL = "deel-ai-notam"
POLYMTL = "polymtl-2020"

EVOLVE_URL = "https://raw.githubusercontent.com/Estrellajer/NOTAM-Evolve/main/Dataset/{}"
EVOLVE_KINDS = ("runway", "taxiway", "light", "area")
EVOLVE_FILES = tuple(f"{kind}_{half}.json" for kind in EVOLVE_KINDS for half in ("train", "test"))
DEEL_URL = "https://huggingface.co/datasets/DEEL-AI/NOTAM/resolve/main/{}"
DEEL_FILES = ("train_data.csv", "test_data.csv")
POLYMTL_URL = "https://raw.githubusercontent.com/krooonal/NOTAM_explainable_prediction_data/main/{}"
POLYMTL_FILES = ("NOTAM_data.xlsx",)

EVOLVE_TRAILER = re.compile(r"(?:\n\)\s*)?\nNNNN\b.*", re.DOTALL)
# Most of the sheet's times put the day where the hour belongs and the hour and minute after it.
POLYMTL_GARBLED_TIME = re.compile(r"(\d{4}-\d{2}-(\d{2}))T\2:(\d{2}):(\d{2})00\.000Z")
POLYMTL_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


@dataclass
class Import:
    """One source's corpus records, and how many of its NOTAMs were skipped for each reason."""

    source: str
    records: list[dict] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)

    @property
    def read(self) -> int:
        return len(self.records) + self.skipped.total()

    def summary(self) -> str:
        reasons = ", ".join(f"{count:,} {reason}" for reason, count in self.skipped.most_common())
        return f"{self.source}: read {self.read:,}, kept {len(self.records):,}, skipped {reasons or 'none'}"


def api_text(text: str) -> str:
    """``text`` trimmed, with LF line breaks."""
    return "\n".join(text.strip().splitlines())


def content_id(text: str) -> str:
    """A stable ID for a NOTAM its source published without one."""
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def a_item_record(message: str, source: str) -> dict | None:
    """An ``A) <location> E) <text>`` message as a corpus record, or None without both items."""
    location, body = rewrite.item(message, "A"), rewrite.e_item(message)
    if not location or not body or not (text := api_text(body)):
        return None
    return rewrite.record(location, content_id(text), text, corpus.nms_type({"notam_text": text}), None, None, source)


def evolve_record(raw: str) -> dict | None:
    """A NOTAM-Evolve input as a corpus record, or None when it has no A) item."""
    return a_item_record(EVOLVE_TRAILER.sub("", raw), EVOLVE)


def deel_record(raw: str, domestic_locations: dict[str, str]) -> dict | None:
    """A DEEL NOTAM as a corpus record, or None unless its text names its location unambiguously.

    The location comes from a whole ICAO message's header and A) item, an ``A) <location> E) <text>``
    message, or an FAA domestic text's leading designator whose ICAO location ends with it.
    """
    text = api_text(raw)
    if found := rewrite.message_record("", text, domestic_locations, DEEL):
        return found | {"notam_text": api_text(found["notam_text"])}
    if text.startswith("A)"):
        return a_item_record(text, DEEL)
    if location := _designated_location(text, domestic_locations):
        return rewrite.record(location, content_id(text), text, corpus.nms_type({"notam_text": text}), None, None, DEEL)
    return None


def _designated_location(text: str, domestic_locations: dict[str, str]) -> str | None:
    designator = text.split(maxsplit=1)[0] if text else ""
    location = domestic_locations.get(designator)
    return location if location and location.endswith(designator) else None


def polymtl_record(row: dict) -> dict | None:
    """A NOTAM_data.xlsx row, keyed by column name, as a corpus record; None without a message or location."""
    text, location = api_text(row.get("message") or ""), (row.get("location") or "").strip()
    if not text or not location:
        return None
    notam_id = (row.get("id") or "").strip() or content_id(text)
    kind = corpus.nms_type({"notam_text": text})
    return rewrite.record(
        location, notam_id, text, kind, _polymtl_time(row.get("startdate")), _polymtl_time(row.get("enddate")), POLYMTL
    )


def _polymtl_time(value: str | None) -> str | None:
    if not value:
        return None
    if garbled := POLYMTL_GARBLED_TIME.fullmatch(value):
        date, _, hour, minute = garbled.groups()
        return f"{date}T{hour}:{minute}:00.000Z"
    return value if POLYMTL_TIME.fullmatch(value) else None


def _directory(source: str) -> Path:
    return EXTERNAL_DIR / source


def _present(source: str, names: Iterable[str]) -> Iterator[Path]:
    return (path for name in names if (path := _directory(source) / name).exists())


def evolve_inputs() -> Iterator[str]:
    for path in _present(EVOLVE, EVOLVE_FILES):
        yield from (example["input"] for example in json.loads(path.read_text(encoding="utf-8")))


def deel_texts() -> Iterator[str]:
    for path in _present(DEEL, DEEL_FILES):
        with path.open(newline="", encoding="utf-8") as file:
            yield from (row["text"] for row in csv.DictReader(file, delimiter=";"))


def polymtl_rows() -> Iterator[dict]:
    for path in _present(POLYMTL, POLYMTL_FILES):
        rows = openpyxl.load_workbook(path, read_only=True).active.iter_rows(values_only=True)
        header = next(rows)
        yield from (dict(zip(header, row, strict=False)) for row in rows if any(row))


def convert(source: str, items: Iterable, to_record: Callable[..., dict | None], text: Callable = str) -> Import:
    """Each of ``items`` converted to a record, skips counted as having no text or no recoverable location."""
    result = Import(source)
    for item in items:
        if record := to_record(item):
            result.records.append(record)
        else:
            result.skipped["no text" if not (text(item) or "").strip() else "no location"] += 1
    return result


def imports(domestic_locations: dict[str, str], include_unlicensed: bool = False) -> list[Import]:
    """Every downloaded source's records; Polytechnique Montréal's only when ``include_unlicensed``."""
    found = [
        convert(EVOLVE, evolve_inputs(), evolve_record, lambda raw: EVOLVE_TRAILER.sub("", raw)),
        convert(DEEL, deel_texts(), lambda text: deel_record(text, domestic_locations)),
    ]
    if include_unlicensed:
        found.append(convert(POLYMTL, polymtl_rows(), polymtl_record, lambda row: row.get("message")))
    return found


def fetch(include_unlicensed: bool = False):
    """Download each source's files that aren't already in data/external/."""
    sources = [(EVOLVE, EVOLVE_URL, EVOLVE_FILES), (DEEL, DEEL_URL, DEEL_FILES)]
    if include_unlicensed:
        sources.append((POLYMTL, POLYMTL_URL, POLYMTL_FILES))
    for source, url, names in sources:
        for name in names:
            _download(url.format(name), _directory(source) / name)


def _download(url: str, path: Path):
    if path.exists():
        return
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(response.content)
    partial.rename(path)

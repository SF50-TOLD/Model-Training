"""Migration of schema 1.5.0 extractions to the current schema.

Every reader of a stored label calls ``current`` so a 1.5.0 silver label is compared, shown and
trained on in the current shape. ``migrate`` converts one label and says what it could not settle
from the label alone: a note that ``needs_review`` names a NOTAM a person should look at again.
"""

import copy
import re
import sqlite3
from dataclasses import dataclass, field

from notam_gold import db
from notam_gold.db import UNREVIEWED_REVIEWER_PREFIX
from notam_gold.schema import SHORTENING_FIELDS, canonicalize, validate

MIGRATION_REVIEWER = "Claude (migrating to schema 2.0.0 by rules approved by Tim Morgan)"
FLAGGED_REVIEWER = f"{UNREVIEWED_REVIEWER_PREFIX} migrated to schema 2.0.0 by rule; needs a look at"

_COMPASS = "N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW"
_DESIGNATOR = r"(\d{1,2}[LCR]?(?:\s*/\s*\d{1,2}[LCR]?)?)"
_CLOSED = r"(?:CLSD|CLOSED|NOT\s+AVBL|NOT\s+AVAILABLE|NOT\s+AUTH)"
_LANDING = r"LDG|LANDINGS?|ARR|ARRIVALS?"
_TAKEOFF = r"TKOF|TAKE-?OFFS?|DEP|DEPARTURES?"
_OPERATION = rf"(?:{_LANDING}|{_TAKEOFF})"
_JOINER = r"(?:\s+(?:AND|&)\s+|\s*/\s*)"
_OPERATIONS = rf"({_OPERATION}(?:{_JOINER}{_OPERATION})?)"
_OPERATION_CLOSURES = [
    re.compile(rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}\s+(?:FOR\s+|TO\s+)?{_OPERATIONS}\b"),
    re.compile(rf"(?<!IFR\s)(?<!VFR\s)\b{_OPERATIONS}\s+(?:ON\s+|FM\s+|FROM\s+)?RWY\s*{_DESIGNATOR}\s+{_CLOSED}"),
]
_ONLY_CLOSURES = [
    re.compile(
        rf"\bRWY\s*{_DESIGNATOR}\s+(?:IS\s+)?(?:AVBL|AVAILABLE|LIMITED TO)\s+(?:FOR\s+)?{_OPERATIONS}"
        r"\s+ONLY\b(?!\s+ON\s+RWY)"
    ),
    re.compile(rf"\bLIMITED TO\s+{_OPERATIONS}\s+ONLY\s+ON\s+RWY\s*{_DESIGNATOR}\b"),
]
_OUTRIGHT = re.compile(rf"\bRWY\s*{_DESIGNATOR}\s+{_CLOSED}(?!\s+(?:FOR\s+|TO\s+)?{_OPERATION}\b)")
_ARP = re.compile(r"\bARP\b")
_IDENTIFIER = re.compile(r"^[A-Z0-9]{3,4}$")
_DEPARTURE_END = re.compile(r"\b(?:DER|DEP[\s-]*END|DEPARTURE\s+END|BEYOND\s+(?:TORA|TODA|END)|TORA|TODA)\b")
_THRESHOLD = re.compile(r"\b(?:THR|THRESHOLD|APCH\s+END|APP\s+END|APPROACH\s+END|BFR\s+THR)\b")
_REFERENCE_DESIGNATOR = re.compile(r"(?:RWY\s*)?\b(\d{2}[LCR]?)\b")


@dataclass(frozen=True)
class Note:
    """What the migration did at ``path``, and whether a person should check it."""

    code: str
    path: str
    message: str
    needs_review: bool = False


def is_current(extraction: dict) -> bool:
    return "obstacles" in extraction


def current(extraction: dict, text: str = "") -> dict:
    """``extraction`` in the current schema: as it is, or migrated from 1.5.0."""
    return extraction if is_current(extraction) else migrate(extraction, text)[0]


def migrate(extraction: dict, text: str = "") -> tuple[dict, list[Note]]:
    """The 1.5.0 ``extraction`` in the current schema, with notes on everything that was not mechanical."""
    notes = []
    effects = _merged_effects(extraction["effects"], text, notes)
    obstacles = _obstacles(extraction["effects"], text, notes)
    migrated = {"isCanceled": extraction["isCanceled"], "effects": effects, "obstacles": obstacles}
    return canonicalize(migrated), notes


def _merged_effects(old_effects: list[dict], text: str, notes: list[Note]) -> list[dict]:
    closures = operation_closures(text)
    outright = _designators(_OUTRIGHT, text)
    by_runway: dict[str | None, dict] = {}
    for old in sorted(old_effects, key=_is_pair):
        for runway in _directions(old["runway"]):
            new = _effect(old, runway, closures, outright, notes)
            if (existing := by_runway.get(runway)) is None:
                by_runway[runway] = new
            else:
                _merge(existing, new, notes)
    effects = [e for e in by_runway.values() if _states_something(e)]
    for runway, operations in closures.items():
        closure = by_runway.get(runway, {}).get("closure", "none")
        if not operations <= _OPERATIONS_OF[closure]:
            notes.append(_unrecorded_closure(runway, operations))
    return effects


_OPERATIONS_OF = {"none": set(), "takeoff": {"takeoff"}, "landing": {"landing"}, "both": {"takeoff", "landing"}}
_CLOSURE_OF = {frozenset(ops): closure for closure, ops in _OPERATIONS_OF.items()}


def _unrecorded_closure(runway: str, operations: set[str]) -> Note:
    named = " and ".join(sorted(operations))
    return Note("closure_not_recorded", "effects", f"the text closes runway {runway} for {named}; not recorded", True)


def _effect(old: dict, runway: str | None, closures: dict, outright: set[str], notes: list[Note]) -> dict:
    """The effect for one direction of ``old``, holding copies so expanded directions share nothing."""
    old = copy.deepcopy(old)
    index = f"effects[{runway}]"
    effect = {
        "runway": runway,
        "closure": _closure(old, runway, closures, outright, notes),
        "partialClosure": None,
        "thresholdDisplacement": old["thresholdDisplacement"],
        "declaredDistances": None,
        "surfaceCondition": None,
    }
    if old["closure"] == "partial":
        effect["partialClosure"] = {"length": old["closedLength"], "end": old["closedEnd"]}
    if (declared := old["declaredDistances"]) is not None:
        if declared["TORA"] is None and declared["LDA"] is None:
            notes.append(Note("distances_dropped", index, "only TODA or ASDA were stated; the schema keeps neither"))
        else:
            effect["declaredDistances"] = {"TORA": declared["TORA"], "LDA": declared["LDA"]}
    if (condition := old["surfaceCondition"]) is not None:
        contaminants = [{k: c[k] for k in ("type", "coveragePercent", "depth")} for c in condition["contaminants"]]
        effect["surfaceCondition"] = {"rwyCC": condition["rwyCC"], "contaminants": contaminants}
    return effect


def _closure(old: dict, runway: str | None, closures: dict, outright: set[str], notes: list[Note]) -> str:
    if old["closure"] != "full":
        return "none"
    operations = closures.get(runway)
    if not operations or operations == {"takeoff", "landing"} or runway in outright:
        return "both"
    narrowed = _CLOSURE_OF[frozenset(operations)]
    notes.append(Note("closure_narrowed", "effects[0].closure", f"runway {runway} is closed for {narrowed} only", True))
    return narrowed


def _merge(existing: dict, new: dict, notes: list[Note]):
    """Fold ``new`` into ``existing`` for the same direction; the earlier (single-direction) value wins a conflict."""
    if new["closure"] != "none" and existing["closure"] == "none":
        existing["closure"] = new["closure"]
    for key in (*SHORTENING_FIELDS, "surfaceCondition"):
        if new[key] is None:
            continue
        if existing[key] is not None and existing[key] != new[key]:
            path = f"effects[0].{key}"
            notes.append(Note("merge_conflict", path, f"runway {existing['runway']} has two different values", True))
            continue
        existing[key] = new[key]


def _is_pair(effect: dict) -> bool:
    return bool(effect["runway"]) and "/" in effect["runway"]


def _states_something(effect: dict) -> bool:
    return effect["closure"] != "none" or any(effect[k] is not None for k in (*SHORTENING_FIELDS, "surfaceCondition"))


def _obstacles(old_effects: list[dict], text: str, notes: list[Note]) -> list[dict]:
    obstacles = []
    for old in old_effects:
        if (obstacle := old["obstacle"]) is None:
            continue
        index = f"obstacles[{len(obstacles)}]"
        height = _height(obstacle)
        if height is None and obstacle["distance"] is None:
            notes.append(Note("obstacle_dropped", index, "the obstacle states neither a height nor a distance"))
            continue
        if obstacle["latitude"] is not None:
            notes.append(Note("position_dropped", index, "the schema keeps no position"))
        obstacles.append(
            {
                "height": height,
                "distance": obstacle["distance"],
                "reference": _reference(obstacle, old["runway"], text, index, notes),
                "direction": _direction(obstacle, text, index, notes),
            }
        )
    return obstacles


def _height(obstacle: dict) -> dict | None:
    for key, datum in (("heightMSL", "MSL"), ("heightAGL", "AGL")):
        if obstacle[key] is not None:
            return {**obstacle[key], "datum": datum}
    return None


def _reference(obstacle: dict, runway: str | None, text: str, index: str, notes: list[Note]) -> dict | None:
    if obstacle["distance"] is None:
        return None
    written = " ".join((obstacle["distanceReference"] or "").upper().split())
    kind = _reference_kind(written, text)
    if kind in ("ARP", "other"):
        if kind == "other":
            notes.append(
                Note("reference_unrecognised", f"{index}.reference", f"{written!r} names no known point", True)
            )
        return {"kind": kind, "runway": None}
    designators = _directions(runway) if runway else []
    end = _REFERENCE_DESIGNATOR.search(written)
    if end is not None:
        return {"kind": kind, "runway": _padded(end.group(1))}
    if len(designators) == 1 and designators[0] is not None:
        return {"kind": kind, "runway": designators[0]}
    notes.append(Note("reference_runway_unknown", f"{index}.reference", f"{written!r} names no runway end", True))
    return {"kind": "other", "runway": None}


def _reference_kind(written: str, text: str) -> str:
    if _DEPARTURE_END.search(written):
        return "departureEnd"
    if _THRESHOLD.search(written):
        return "threshold"
    if _ARP.search(written) or _IDENTIFIER.match(written) and not _REFERENCE_DESIGNATOR.fullmatch(written):
        return "ARP"
    return "other"


def _direction(obstacle: dict, text: str, index: str, notes: list[Note]):
    if (bearing := obstacle["bearingDegrees"]) is not None:
        return bearing % 360
    if obstacle["distance"] is None:
        return None
    value = obstacle["distance"]["value"]
    pattern = rf"(?<![\d.])({re.escape(_shortest(value))})\s*(?:NM|M|FT|KM)\s+({_COMPASS})\b"
    match = re.search(pattern, " ".join(text.upper().split()))
    if match is None:
        return None
    notes.append(Note("direction_from_text", f"{index}.direction", f"read {match.group(2)} from the text", True))
    return match.group(2)


def _shortest(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def operation_closures(text: str) -> dict[str, set[str]]:
    """The operations each runway direction is stated closed to, where the text names an operation."""
    normalized = " ".join(text.upper().split())
    found: dict[str, set[str]] = {}
    for pattern in _OPERATION_CLOSURES:
        for match in pattern.finditer(normalized):
            operations, designator = _operations_and_designator(match)
            for runway in _directions(designator):
                found.setdefault(runway, set()).update(operations)
    for pattern in _ONLY_CLOSURES:
        for match in pattern.finditer(normalized):
            operations, designator = _operations_and_designator(match)
            for runway in _directions(designator):
                found.setdefault(runway, set()).update({"takeoff", "landing"} - operations)
    return {runway: operations for runway, operations in found.items() if operations}


def _operations_and_designator(match: re.Match) -> tuple[set[str], str]:
    first, second = match.group(1), match.group(2)
    operations_text, designator = (second, first) if re.match(r"\d", first) else (first, second)
    return {_operation(word) for word in re.split(_JOINER, operations_text)}, _padded_pair(designator)


def _operation(word: str) -> str:
    return "landing" if re.fullmatch(_LANDING, word) else "takeoff"


def _designators(pattern: re.Pattern, text: str) -> set[str]:
    normalized = " ".join(text.upper().split())
    return {runway for match in pattern.finditer(normalized) for runway in _directions(_padded_pair(match.group(1)))}


def _padded_pair(written: str) -> str:
    return "/".join(_padded(part.strip()) for part in written.split("/"))


def _padded(written: str) -> str:
    digits = re.match(r"\d+", written).group()
    return f"{int(digits):02d}{written[len(digits) :]}"


def _directions(runway: str | None) -> list[str | None]:
    return runway.split("/") if runway else [None]


@dataclass
class MigrationReport:
    """What migrating a database's current reviews did, or would do."""

    migrated: int = 0
    needs_review: list[str] = field(default_factory=list)
    notes: list[tuple[str, Note]] = field(default_factory=list)


REVIEWS_SQL = """
SELECT review.*, notam.notam_text FROM current_review AS review JOIN notam ON notam.id = review.notam_key
ORDER BY review.notam_key
"""


def migrate_reviews(connection: sqlite3.Connection, dry_run: bool) -> MigrationReport:
    """Append a current-schema review for every current review; flagged ones re-enter the review queue."""
    report = MigrationReport()
    rows = connection.execute(REVIEWS_SQL).fetchall()
    for row in rows:
        extraction = db.loads(row["extraction"])
        if extraction is None or is_current(extraction):
            continue
        migrated, notes = migrate(extraction, row["notam_text"])
        if problems := validate(migrated):
            raise ValueError(f"{row['notam_key']}: migrated label is invalid: {[p.to_dict() for p in problems]}")
        flagged = [note for note in notes if note.needs_review]
        report.migrated += 1
        report.notes += [(row["notam_key"], note) for note in notes]
        if flagged:
            report.needs_review.append(row["notam_key"])
        if not dry_run:
            _append_review(connection, row, migrated, notes, flagged)
    if not dry_run:
        connection.commit()
    return report


def _append_review(
    connection: sqlite3.Connection, row: sqlite3.Row, migrated: dict, notes: list[Note], flagged: list[Note]
):
    if flagged:
        reviewer = f"{FLAGGED_REVIEWER} {', '.join(note.path for note in flagged)}"
    elif row["reviewer"].startswith(UNREVIEWED_REVIEWER_PREFIX):
        reviewer = f"{UNREVIEWED_REVIEWER_PREFIX} migrated to schema 2.0.0 by rule"
    else:
        reviewer = MIGRATION_REVIEWER
    migration_note = "Schema 2.0.0 migration: " + "; ".join(f"{note.path}: {note.message}" for note in notes)
    note = "\n".join(filter(None, [row["note"], migration_note if notes else None]))
    connection.execute(
        "INSERT INTO review (notam_key, silver_label_id, reviewer, reviewed_at, status, extraction, note, edited)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["notam_key"],
            row["silver_label_id"],
            reviewer,
            db.now(),
            row["status"],
            db.dumps(migrated),
            note or None,
            row["edited"],
        ),
    )

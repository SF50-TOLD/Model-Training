"""Local web app for reviewing silver labels into gold labels, one NOTAM per screen."""

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from notam_gold import db
from notam_gold.coords import parse_position
from notam_gold.labeling import evidence_problems
from notam_gold.prompt import build_prompt
from notam_gold.reviews import stale_reviews
from notam_gold.schema import canonicalize, schema, validate
from notam_gold.strata import ALL_STRATA

STATIC = Path(__file__).parent / "static"
EMPTY_EXTRACTION = {"isCanceled": False, "effects": []}


class ValidateRequest(BaseModel):
    extraction: dict


class ReviewRequest(BaseModel):
    key: str
    status: Literal["accepted", "edited", "ambiguous", "skipped"]
    extraction: dict | None = None
    note: str | None = None


def _current_problems(extraction: dict | None, evidence: list[dict], text: str, stored: list[dict]) -> list[dict]:
    """Problems under today's validation and evidence matching; the stored ones reflect ingest time."""
    if extraction is None:
        return stored
    return [p.to_dict() for p in validate(extraction)] + evidence_problems(evidence, text)


def _silver(connection: sqlite3.Connection, key: str, run_name: str) -> dict | None:
    row = connection.execute(
        "SELECT silver_label.*, label_run.model, label_run.prompt_version, notam.notam_text FROM silver_label"
        " JOIN label_run ON label_run.id = run_id JOIN notam ON notam.id = notam_key"
        " WHERE notam_key = ? AND label_run.name = ?"
        " ORDER BY silver_label.id DESC LIMIT 1",
        (key, run_name),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "model": row["model"],
        "promptVersion": row["prompt_version"],
        "extraction": db.loads(row["extraction"]),
        "evidence": db.loads(row["evidence"]),
        "note": row["note"],
        "problems": _current_problems(
            db.loads(row["extraction"]), db.loads(row["evidence"]), row["notam_text"], db.loads(row["problems"])
        ),
    }


def _current_review(connection: sqlite3.Connection, key: str) -> dict | None:
    row = connection.execute("SELECT * FROM current_review WHERE notam_key = ?", (key,)).fetchone()
    if row is None:
        return None
    return {
        "status": row["status"],
        "extraction": db.loads(row["extraction"]),
        "note": row["note"],
        "reviewer": row["reviewer"],
        "reviewedAt": row["reviewed_at"],
        "edited": bool(row["edited"]),
    }


QUEUE_SQL = """
SELECT notam.id AS key, notam.notam_id, notam.icao_location, notam.selected_stratum, notam.strata,
       COALESCE(disagreement.score, 0) AS score, current_review.status AS status
FROM notam
LEFT JOIN disagreement ON disagreement.notam_key = notam.id
LEFT JOIN current_review ON current_review.notam_key = notam.id
ORDER BY notam.selection_rank
"""
OPEN_STATUSES = ("unreviewed", "stale")


def _queue_status(row: sqlite3.Row, stale: dict) -> str:
    return "stale" if row["key"] in stale else row["status"] or "unreviewed"


def create_app(database: Path, reviewer: str) -> FastAPI:
    """The review app over ``database``, attributing reviews to ``reviewer``.

    Every handler is ``async`` so all database work runs on the event loop's thread:
    this SQLite build is not serialized (``sqlite3.threadsafety == 1``), and sharing
    one connection across FastAPI's worker threads crashes the process.
    """
    connection = db.connect(database)
    app = FastAPI(title="NOTAM gold review")

    @app.middleware("http")
    async def revalidate(request, call_next):
        """Make browsers revalidate every load, so an edited page never runs a stale cached script."""
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/enums")
    async def enums():
        definitions = schema()["$defs"]
        return {
            "closure": definitions["RunwayEffect"]["properties"]["closure"]["enum"],
            "contaminant": definitions["Contaminant"]["properties"]["type"]["enum"],
        }

    @app.get("/api/queue")
    async def queue(stratum: str | None = None, disagreement: bool = False, status: str = "all"):
        items = []
        stale = stale_reviews(connection)
        for row in connection.execute(QUEUE_SQL):
            reviewed_status = _queue_status(row, stale)
            if stratum and row["selected_stratum"] != stratum:
                continue
            if disagreement and not row["score"]:
                continue
            if status == "reviewed" and reviewed_status not in ("accepted", "edited"):
                continue
            if status not in ("all", "reviewed") and reviewed_status != status:
                continue
            items.append(
                {
                    "key": row["key"],
                    "notamId": row["notam_id"],
                    "location": row["icao_location"],
                    "stratum": row["selected_stratum"],
                    "score": row["score"],
                    "status": reviewed_status,
                }
            )
        items.sort(key=lambda item: (item["status"] not in OPEN_STATUSES, -item["score"]))
        return {"items": items, "reviewer": reviewer}

    @app.get("/api/progress")
    async def progress():
        stale = stale_reviews(connection)
        totals, reviewed = Counter(), Counter()
        for row in connection.execute(QUEUE_SQL):
            totals[row["selected_stratum"]] += 1
            reviewed[row["selected_stratum"]] += _queue_status(row, stale) not in (*OPEN_STATUSES, "skipped")
        return [{"stratum": s, "total": totals[s], "reviewed": reviewed[s]} for s in ALL_STRATA if totals[s]]

    @app.get("/api/notam")
    async def notam(key: str):
        row = connection.execute("SELECT * FROM notam WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise HTTPException(404, f"No NOTAM {key}")
        disagreement = connection.execute("SELECT paths FROM disagreement WHERE notam_key = ?", (key,)).fetchone()
        return {
            "key": key,
            "notamId": row["notam_id"],
            "location": row["icao_location"],
            "prompt": build_prompt(row["icao_location"], row["notam_text"]),
            "strata": db.loads(row["strata"]),
            "stratum": row["selected_stratum"],
            "nmsType": row["nms_type"],
            "effectiveStart": row["effective_start"],
            "effectiveEnd": row["effective_end"],
            "silverA": _silver(connection, key, "A"),
            "silverB": _silver(connection, key, "B"),
            "disagreements": db.loads(disagreement["paths"]) if disagreement else [],
            "review": _current_review(connection, key),
            "staleDifferences": [d.to_dict() for d in stale_reviews(connection).get(key, [])],
        }

    @app.post("/api/validate")
    async def check(request: ValidateRequest):
        return {"problems": [p.to_dict() for p in validate(request.extraction)]}

    @app.get("/api/dms")
    async def dms(text: str):
        try:
            latitude, longitude = parse_position(text)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return {"latitude": latitude, "longitude": longitude}

    @app.post("/api/review")
    async def review(request: ReviewRequest):
        silver = _silver(connection, request.key, "A")
        extraction = request.extraction
        if request.status in ("accepted", "edited"):
            if extraction is None:
                raise HTTPException(422, "A reviewed label needs an extraction")
            if problems := validate(extraction):
                raise HTTPException(422, {"problems": [p.to_dict() for p in problems]})
        edited = _is_edited(extraction, silver)
        status = request.status
        if status in ("accepted", "edited"):
            status = "edited" if edited else "accepted"
        with connection:
            connection.execute(
                "INSERT INTO review"
                " (notam_key, silver_label_id, reviewer, reviewed_at, status, extraction, note, edited)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.key,
                    silver["id"] if silver else None,
                    reviewer,
                    db.now(),
                    status,
                    db.dumps(extraction),
                    request.note or None,
                    int(edited),
                ),
            )
        return {"status": status, "edited": edited}

    return app


def _is_edited(extraction: dict | None, silver: dict | None) -> bool:
    if extraction is None:
        return False
    original = silver["extraction"] if silver and silver["extraction"] else EMPTY_EXTRACTION
    try:
        return canonicalize(extraction) != canonicalize(original)
    except KeyError, TypeError:
        return True

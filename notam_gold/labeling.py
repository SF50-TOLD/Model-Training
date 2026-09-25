"""Silver labelling with the Claude Message Batches API, with provenance.

Each labelling run is one batch and one ``label_run`` row recording the
model, prompt version and schema version. Results are stored in
``silver_label`` rows, which are never modified.
"""

import hashlib
import itertools
import json
import random
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from notam_gold import db
from notam_gold.paths import LABELER_DIR, SCHEMA_DOC
from notam_gold.prompt import build_prompt
from notam_gold.schema import schema, schema_version, validate

MAX_TOKENS = 16000
EFFORT = "high"
WIRE_UNSUPPORTED = ("minimum", "maximum")


@dataclass(frozen=True)
class RunSpec:
    """How a named labelling run calls the model."""

    name: str
    model: str
    shuffle_seed: int | None  # None keeps the examples in file order

    @property
    def system_prompt(self) -> str:
        return system_prompt(self.shuffle_seed)

    @property
    def prompt_version(self) -> str:
        return hashlib.sha256(self.system_prompt.encode()).hexdigest()[:12]


RUNS = {
    "A": RunSpec("A", "claude-opus-5-5", None),
    "B": RunSpec("B", "claude-opus-5", 7),
}

# USD per million tokens at batch rates (half the standard rate). Cache writes use the 1-hour TTL (2x input).
BATCH_PRICES = {
    "claude-opus-5-5": {"input": 2.00, "output": 10.00, "cache_write": 4.00, "cache_read": 0.10},
    "claude-opus-5": {"input": 2.50, "output": 12.50, "cache_write": 5.00, "cache_read": 0.25},
}


def _strip_unsupported(value):
    if isinstance(value, dict):
        return {k: _strip_unsupported(v) for k, v in value.items() if k not in WIRE_UNSUPPORTED}
    if isinstance(value, list):
        return [_strip_unsupported(v) for v in value]
    return value


@cache
def output_schema() -> dict:
    """The labeler's structured-output schema: the extraction plus evidence and a note.

    Structured outputs reject numeric bounds, so they are stripped here and enforced by ``validate``.
    """
    extraction = {k: v for k, v in schema().items() if k not in ("$schema", "$id", "schemaVersion", "$defs")}
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "quote"],
        "properties": {"path": {"type": "string"}, "quote": {"type": "string"}},
    }
    return _strip_unsupported(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["extraction", "evidence", "note"],
            "properties": {
                "extraction": {"$ref": "#/$defs/NOTAMExtraction"},
                "evidence": {"type": "array", "items": evidence},
                "note": {"type": ["string", "null"]},
            },
            "$defs": schema()["$defs"] | {"NOTAMExtraction": extraction},
        }
    )


def examples(shuffle_seed: int | None) -> list[dict]:
    lines = (LABELER_DIR / "examples.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(rows)
    return rows


def system_prompt(shuffle_seed: int | None) -> str:
    """Instructions, then SCHEMA.md, then complete example outputs."""
    rendered = "\n\n".join(
        f"### Example {n}\n\nInput:\n\n```text\n{row['prompt']}\n```\n\n"
        f"Output:\n\n```json\n{json.dumps(row['output'], indent=2, ensure_ascii=False)}\n```"
        for n, row in enumerate(examples(shuffle_seed), start=1)
    )
    return "\n\n".join(
        [
            (LABELER_DIR / "system_prompt.md").read_text(encoding="utf-8").strip(),
            "# Schema document\n\n" + SCHEMA_DOC.read_text(encoding="utf-8").strip(),
            "# Complete output examples\n\n" + rendered,
        ]
    )


def request_params(spec: RunSpec, prompt: str) -> dict:
    return {
        "model": spec.model,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": output_schema()}},
        "system": [{"type": "text", "text": spec.system_prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "messages": [{"role": "user", "content": prompt}],
    }


def custom_id(notam_key: str) -> str:
    """Batch custom IDs allow only [a-zA-Z0-9_-]; NOTAM identities contain spaces and slashes."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", notam_key)


def estimate(client: anthropic.Anthropic, spec: RunSpec, prompts: list[str], output_tokens: int) -> dict:
    """Projected batch cost: best case every request after the first reads the cache, worst case none do."""
    system_tokens = client.messages.count_tokens(
        model=spec.model, system=spec.system_prompt, messages=[{"role": "user", "content": "x"}]
    ).input_tokens
    sample = prompts[:: max(1, len(prompts) // 25)]
    message_tokens = sum(
        client.messages.count_tokens(model=spec.model, messages=[{"role": "user", "content": p}]).input_tokens
        for p in sample
    ) / len(sample)
    prices = {k: v / 1e6 for k, v in BATCH_PRICES[spec.model].items()}
    n = len(prompts)
    variable = n * (message_tokens * prices["input"] + output_tokens * prices["output"])
    best = variable + system_tokens * (prices["cache_write"] + (n - 1) * prices["cache_read"])
    worst = variable + n * system_tokens * prices["cache_write"]
    return {
        "requests": n,
        "system_tokens": system_tokens,
        "mean_message_tokens": round(message_tokens),
        "assumed_output_tokens": output_tokens,
        "best_usd": round(best, 2),
        "worst_usd": round(worst, 2),
    }


def prewarm(client: anthropic.Anthropic, spec: RunSpec) -> dict:
    """Write the system-prompt cache with one synchronous request so the batch's requests read it.

    Batch requests run concurrently, so without this most of them miss the cache and each pays
    for a write. ``max_tokens: 0`` pre-warming is rejected alongside structured outputs, so this
    sends a real (short) labelling request and discards the result.
    """
    message = client.messages.create(**request_params(spec, build_prompt("ZZZZ", "RWY 09/27 CLSD")))
    return message.usage.to_dict()


def submit(
    client: anthropic.Anthropic, connection: sqlite3.Connection, spec: RunSpec, notams: list[sqlite3.Row]
) -> int:
    """Submit one batch for ``notams`` and record the run; returns the label_run id."""
    requests = [
        Request(
            custom_id=custom_id(n["id"]),
            params=MessageCreateParamsNonStreaming(
                **request_params(spec, build_prompt(n["icao_location"], n["notam_text"]))
            ),
        )
        for n in notams
    ]
    batch = client.messages.batches.create(requests=requests)
    with connection:
        return _record_run(connection, spec, notams, batch.id)


def _record_run(connection: sqlite3.Connection, spec: RunSpec, notams: list[sqlite3.Row], batch_id: str | None) -> int:
    keys = db.dumps([n["id"] for n in notams])
    return connection.execute(
        "INSERT INTO label_run (name, model, prompt_version, schema_version, batch_id, notam_keys, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (spec.name, spec.model, spec.prompt_version, schema_version(), batch_id, keys, db.now()),
    ).lastrowid


def label_now(
    client: anthropic.Anthropic,
    connection: sqlite3.Connection,
    spec: RunSpec,
    notams: list[sqlite3.Row],
    workers: int = 4,
) -> dict[str, int]:
    """Label ``notams`` through the Messages API, at standard prices, and record the run.

    Worth it for small sets: after the first request writes the prompt cache, the rest read it
    reliably, whereas concurrent batch requests can each miss and pay for a cache write.
    """
    with connection:
        run_id = _record_run(connection, spec, notams, batch_id=None)

    def label(notam):
        try:
            prompt = build_prompt(notam["icao_location"], notam["notam_text"])
            return client.messages.create(**request_params(spec, prompt))
        except anthropic.APIError as error:
            return error

    counts = {"succeeded": 0, "errored": 0}
    try:
        with ThreadPoolExecutor(workers) as pool:
            results = itertools.chain([label(notams[0])], pool.map(label, notams[1:])) if notams else []
            for notam, result in zip(notams, results, strict=True):
                if isinstance(result, anthropic.APIError):
                    counts["errored"] += 1
                    continue
                with connection:
                    _store(connection, run_id, notam, result)
                counts["succeeded"] += 1
    finally:
        with connection:
            connection.execute("UPDATE label_run SET ended_at = ? WHERE id = ?", (db.now(), run_id))
    return counts


def _store(connection: sqlite3.Connection, run_id: int, notam: sqlite3.Row, message) -> None:
    fields = parse_result(message, notam["notam_text"])
    connection.execute(
        "INSERT OR IGNORE INTO silver_label"
        " (run_id, notam_key, extraction, evidence, note, problems, response, usage, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            notam["id"],
            db.dumps(fields["extraction"]),
            db.dumps(fields["evidence"]),
            fields["note"],
            db.dumps(fields["problems"]),
            message.to_json(),
            message.usage.to_json(),
            db.now(),
        ),
    )


def _squashed(text: str) -> str:
    return " ".join(text.split())


def evidence_problems(evidence: list[dict], text: str) -> list[dict]:
    """Quotes absent from the text, ignoring whitespace differences such as CRLF versus LF line breaks."""
    return [
        {"path": e["path"], "message": f"Evidence quote not found in text: {e['quote']!r}"}
        for e in evidence
        if _squashed(e["quote"]) not in _squashed(text)
    ]


def parse_result(message, notam_text: str) -> dict:
    """Silver fields from one successful message, with every problem recorded rather than raised."""
    if message.stop_reason != "end_turn":
        return {
            "extraction": None,
            "evidence": [],
            "note": None,
            "problems": [{"path": "", "message": message.stop_reason}],
        }
    text = next(block.text for block in message.content if block.type == "text")
    output = json.loads(text)
    extraction = output["extraction"]
    problems = [p.to_dict() for p in validate(extraction)] + evidence_problems(output["evidence"], notam_text)
    return {"extraction": extraction, "evidence": output["evidence"], "note": output["note"], "problems": problems}


def ingest(client: anthropic.Anthropic, connection: sqlite3.Connection, run_id: int) -> dict[str, int]:
    """Store a finished batch's results as silver labels; returns counts by result type."""
    run = connection.execute("SELECT * FROM label_run WHERE id = ?", (run_id,)).fetchone()
    notams = {
        custom_id(row["id"]): row
        for row in connection.execute(
            "SELECT * FROM notam WHERE id IN (SELECT value FROM json_each(?))", (run["notam_keys"],)
        )
    }
    counts: dict[str, int] = {}
    with connection:
        for result in client.messages.batches.results(run["batch_id"]):
            kind = result.result.type
            counts[kind] = counts.get(kind, 0) + 1
            if kind != "succeeded":
                continue
            _store(connection, run_id, notams[result.custom_id], result.result.message)
        connection.execute("UPDATE label_run SET ended_at = ? WHERE id = ?", (db.now(), run_id))
    return counts


def actual_cost(connection: sqlite3.Connection) -> dict[str, float]:
    """Spend so far per run, from recorded usage; requests outside a batch cost twice the batch rate."""
    costs: dict[str, float] = {}
    rows = connection.execute(
        "SELECT label_run.id, label_run.name, label_run.model, silver_label.usage"
        " FROM silver_label JOIN label_run ON label_run.id = silver_label.run_id"
    )
    for row in rows:
        usage = json.loads(row["usage"])
        rate = 1 if usage.get("service_tier") == "batch" else 2
        prices = {kind: price * rate for kind, price in BATCH_PRICES[row["model"]].items()}
        cost = (
            usage.get("input_tokens", 0) * prices["input"]
            + usage.get("output_tokens", 0) * prices["output"]
            + (usage.get("cache_creation_input_tokens") or 0) * prices["cache_write"]
            + (usage.get("cache_read_input_tokens") or 0) * prices["cache_read"]
        ) / 1e6
        key = f"{row['id']} ({row['name']}, {row['model']})"
        costs[key] = costs.get(key, 0) + cost
    return costs

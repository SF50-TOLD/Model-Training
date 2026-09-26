"""Label the training set in chunks that can never take total spend past a budget.

Labelling runs in chunks, one at a time, through the Messages API: its first request writes the
prompt cache and the rest read it, which concurrent Batches API requests mostly fail to do (on the
2026-09-25 pilot, 85 of 100 batch requests missed and cost $0.11 each). Before each chunk the spend
so far is read from the usage recorded in the training database, and the chunk is sized so that even
its worst case — every request missing the cache, at standard prices, with twice the output tokens
observed so far — fits in what is left. When not even one request fits, labelling stops.

Run B labels only the strata where training keeps labels both runs agree on (select_training.py).

    python -m training.label_budgeted A --budget 180
"""

import argparse

import anthropic
from dotenv import load_dotenv

from label_silver import observed_output_tokens, unlabelled
from notam_gold import db, labeling
from notam_gold.paths import ROOT
from notam_gold.prompt import build_prompt
from training.paths import TRAINING_DATABASE
from training.select_training import DUAL_RUN_STRATA

DEFAULT_CHUNK_SIZE = 50
OUTPUT_TOKEN_MARGIN = 2
# Messages API requests cost twice the batch rates labeling.estimate prices at.
STANDARD_RATE = 2
PREWARM_TABLE = (
    "CREATE TABLE IF NOT EXISTS prewarm (model TEXT NOT NULL, usage TEXT NOT NULL, created_at TEXT NOT NULL)"
)


def usage_cost(model: str, usage: dict) -> float:
    """USD for one request's recorded usage; requests outside a batch cost twice the batch rate."""
    rate = 1 if usage.get("service_tier") == "batch" else 2
    prices = labeling.BATCH_PRICES[model]
    return (
        rate
        * (
            usage.get("input_tokens", 0) * prices["input"]
            + usage.get("output_tokens", 0) * prices["output"]
            + (usage.get("cache_creation_input_tokens") or 0) * prices["cache_write"]
            + (usage.get("cache_read_input_tokens") or 0) * prices["cache_read"]
        )
        / 1e6
    )


def spent(connection) -> float:
    """Labels and batch prewarms so far, from recorded usage."""
    prewarms = connection.execute("SELECT model, usage FROM prewarm").fetchall()
    return sum(labeling.actual_cost(connection).values()) + sum(
        usage_cost(row["model"], db.loads(row["usage"])) for row in prewarms
    )


def pending(connection, spec: labeling.RunSpec, dual_only: bool) -> list:
    """Unlabelled NOTAMs for this run; run B labels only the strata where both runs must agree."""
    notams = unlabelled(connection, spec)
    if dual_only or spec.name == "B":
        notams = [n for n in notams if n["selected_stratum"] in DUAL_RUN_STRATA]
    return notams


def worst_case(client, connection, spec, notams) -> float:
    prompts = [build_prompt(n["icao_location"], n["notam_text"]) for n in notams]
    output_tokens = OUTPUT_TOKEN_MARGIN * observed_output_tokens(connection, spec.model)
    return STANDARD_RATE * labeling.estimate(client, spec, prompts, output_tokens)["worst_usd"]


def affordable_chunk(client, connection, spec, notams, size: int, remaining: float) -> tuple[list, float]:
    """The largest prefix of ``notams``, at most ``size``, whose worst case fits ``remaining``."""
    chunk = notams[:size]
    while chunk:
        cost = worst_case(client, connection, spec, chunk)
        if cost <= remaining:
            return chunk, cost
        chunk = chunk[: len(chunk) // 2]
    return [], 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", choices=labeling.RUNS)
    parser.add_argument("--budget", type=float, required=True, help="total USD across every training run")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--limit", type=int, help="label at most this many NOTAMs (a pilot)")
    parser.add_argument("--dual-only", action="store_true", help="only the strata both runs label")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = anthropic.Anthropic()
    spec = labeling.RUNS[args.run]
    with db.connect(TRAINING_DATABASE) as connection:
        connection.execute(PREWARM_TABLE)
        if connection.execute("SELECT COUNT(*) FROM label_run WHERE ended_at IS NULL").fetchone()[0]:
            raise SystemExit("A training run is unfinished; ingest or end it before starting another.")
        notams = pending(connection, spec, args.dual_only)[: args.limit]
        while notams:
            remaining = args.budget - spent(connection)
            chunk, cost = affordable_chunk(client, connection, spec, notams, args.chunk_size, remaining)
            if not chunk:
                print(f"Stopping: ${remaining:.2f} left can't cover even one request's worst case.")
                break
            before = spent(connection)
            counts = labeling.label_now(client, connection, spec, chunk)
            actual = spent(connection) - before
            print(
                f"Run {spec.name}: {counts} of {len(chunk)}, ${actual:.2f} (worst case ${cost:.2f});"
                f" ${spent(connection):.2f} spent",
                flush=True,
            )
            notams = notams[len(chunk) :]
        print(f"Spent ${spent(connection):.2f} of ${args.budget:.2f} on training labels.")


if __name__ == "__main__":
    main()

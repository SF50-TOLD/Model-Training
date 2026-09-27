#!/usr/bin/env python3
"""Label gold candidates with Claude, through the Message Batches API or synchronously.

    label_silver.py estimate A            # projected cost of labelling every candidate in run A
    label_silver.py submit A --pilot 20   # small pilot batch
    label_silver.py submit A              # every candidate without a run-A label
    label_silver.py run A --keys FILE     # label the listed NOTAMs now, outside a batch
    label_silver.py status                # runs and their batch status
    label_silver.py ingest 3              # store a finished batch's results
    label_silver.py disagreements         # compare the latest run-A and run-B labels
    label_silver.py cost                  # spend so far, from recorded usage

`submit` suits the full candidate set at batch prices. `run` suits a few dozen NOTAMs: it pays
standard prices, but its requests read the prompt cache reliably. Either needs --confirm-cost
when its estimate exceeds the cost limit.
"""

import argparse
import sqlite3
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from notam_gold import db, labeling
from notam_gold.disagreement import diff, score
from notam_gold.prompt import build_prompt

COST_LIMIT_USD = 25
DEFAULT_OUTPUT_TOKENS = 2500


def unlabelled(connection: sqlite3.Connection, spec: labeling.RunSpec) -> list[sqlite3.Row]:
    """Candidates without a label, or a pending batch request, from this run's current model and prompt version."""
    return connection.execute(
        "SELECT * FROM notam WHERE id NOT IN ("
        " SELECT notam_key FROM silver_label JOIN label_run ON label_run.id = run_id"
        " WHERE label_run.model = :model AND label_run.prompt_version = :prompt"
        " UNION SELECT value FROM label_run, json_each(label_run.notam_keys)"
        " WHERE label_run.ended_at IS NULL AND label_run.model = :model AND label_run.prompt_version = :prompt)"
        " ORDER BY selection_rank",
        {"model": spec.model, "prompt": spec.prompt_version},
    ).fetchall()


def observed_output_tokens(connection: sqlite3.Connection, model: str) -> int:
    """Mean output tokens seen so far for ``model``, or a conservative default before any results."""
    row = connection.execute(
        "SELECT AVG(json_extract(usage, '$.output_tokens')) FROM silver_label"
        " JOIN label_run ON label_run.id = run_id WHERE label_run.model = ?",
        (model,),
    ).fetchone()
    return round(row[0]) if row[0] else DEFAULT_OUTPUT_TOKENS


def cost_estimate(client, connection, spec, notams) -> dict:
    prompts = [build_prompt(n["icao_location"], n["notam_text"]) for n in notams]
    return labeling.estimate(client, spec, prompts, observed_output_tokens(connection, spec.model))


def print_estimate(spec: labeling.RunSpec, estimate: dict):
    print(
        f"Run {spec.name} ({spec.model}, prompt {spec.prompt_version}): {estimate['requests']} requests, "
        f"system prompt {estimate['system_tokens']:,} tokens, mean NOTAM {estimate['mean_message_tokens']} tokens, "
        f"assumed output {estimate['assumed_output_tokens']:,} tokens"
    )
    print(f"Estimated batch cost: ${estimate['best_usd']:.2f} (cache hits) to ${estimate['worst_usd']:.2f} (no hits)")


def chosen(connection: sqlite3.Connection, spec: labeling.RunSpec, args) -> list[sqlite3.Row]:
    """The unlabelled candidates, narrowed to --keys and --pilot when given."""
    notams = unlabelled(connection, spec)
    if args.keys:
        wanted = set(args.keys.read_text(encoding="utf-8").split("\n")) - {""}
        notams = [n for n in notams if n["id"] in wanted]
    return notams[: args.pilot] if args.pilot else notams


def command_estimate(client, connection, args):
    spec = labeling.RUNS[args.run]
    print_estimate(spec, cost_estimate(client, connection, spec, chosen(connection, spec, args)))


def command_run(client, connection, args):
    spec = labeling.RUNS[args.run]
    notams = chosen(connection, spec, args)
    if not notams:
        raise SystemExit(f"Every chosen candidate already has a run-{spec.name} label.")
    estimate = cost_estimate(client, connection, spec, notams)
    expected = 2 * estimate["best_usd"]
    print(f"Run {spec.name}: {len(notams)} requests at standard prices, about ${expected:.2f} with the cache warm")
    if expected > COST_LIMIT_USD and not args.confirm_cost:
        raise SystemExit(f"Estimate exceeds ${COST_LIMIT_USD}; re-run with --confirm-cost once approved.")
    print(labeling.label_now(client, connection, spec, notams))


def command_submit(client, connection, args):
    spec = labeling.RUNS[args.run]
    notams = chosen(connection, spec, args)
    if not notams:
        raise SystemExit(f"Every candidate already has a run-{spec.name} label.")
    estimate = cost_estimate(client, connection, spec, notams)
    print_estimate(spec, estimate)
    if estimate["worst_usd"] > COST_LIMIT_USD and not args.confirm_cost:
        raise SystemExit(f"Estimate exceeds ${COST_LIMIT_USD}; re-run with --confirm-cost once approved.")
    print(f"Pre-warmed the prompt cache: {labeling.prewarm(client, spec)}")
    run_id = labeling.submit(client, connection, spec, notams)
    print(f"Submitted run {run_id} with {len(notams)} requests.")


def command_status(client, connection, _args):
    for run in connection.execute("SELECT * FROM label_run ORDER BY id"):
        stored = connection.execute("SELECT COUNT(*) FROM silver_label WHERE run_id = ?", (run["id"],)).fetchone()[0]
        if run["batch_id"] is None:
            state = "ended" if run["ended_at"] else "running"
            label = f"run {run['id']} {run['name']} {run['model']} prompt {run['prompt_version']}"
            print(f"{label}: synchronous, {state}; stored {stored}")
            continue
        batch = client.messages.batches.retrieve(run["batch_id"])
        counts = batch.request_counts
        print(
            f"run {run['id']} {run['name']} {run['model']} prompt {run['prompt_version']}: {batch.processing_status};"
            f" succeeded {counts.succeeded}, errored {counts.errored}, expired {counts.expired}; stored {stored}"
        )


def command_ingest(client, connection, args):
    print(labeling.ingest(client, connection, args.run_id))
    problems = connection.execute(
        "SELECT COUNT(*) FROM silver_label WHERE run_id = ? AND problems != '[]'", (args.run_id,)
    ).fetchone()[0]
    print(f"{problems} labels have validation or evidence problems (kept, and shown in review).")


def latest_labels(connection: sqlite3.Connection, run_name: str) -> dict[str, sqlite3.Row]:
    rows = connection.execute("SELECT * FROM latest_silver WHERE run_name = ? AND extraction IS NOT NULL", (run_name,))
    return {row["notam_key"]: row for row in rows}


def command_disagreements(_client, connection, _args):
    a, b = latest_labels(connection, "A"), latest_labels(connection, "B")
    with connection:
        connection.execute("DELETE FROM disagreement")
        for key in a.keys() & b.keys():
            differences = diff(db.loads(a[key]["extraction"]), db.loads(b[key]["extraction"]))
            connection.execute(
                "INSERT INTO disagreement VALUES (?, ?, ?, ?, ?)",
                (key, a[key]["id"], b[key]["id"], db.dumps([d.to_dict() for d in differences]), score(differences)),
            )
    disagreeing = connection.execute("SELECT COUNT(*) FROM disagreement WHERE score > 0").fetchone()[0]
    print(f"Compared {len(a.keys() & b.keys())} NOTAMs labelled by both runs; {disagreeing} disagree.")


def command_cost(_client, connection, _args):
    costs = labeling.actual_cost(connection)
    for run, cost in costs.items():
        print(f"run {run}: ${cost:.2f}")
    print(f"total: ${sum(costs.values()):.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("estimate", command_estimate), ("submit", command_submit), ("run", command_run)):
        command = commands.add_parser(name)
        command.set_defaults(handler=handler)
        command.add_argument("run", choices=labeling.RUNS)
        command.add_argument("--pilot", type=int, help="only the first N unlabelled candidates")
        command.add_argument("--keys", type=Path, help="only the NOTAM keys listed one per line in this file")
        command.add_argument("--confirm-cost", action="store_true")
    commands.add_parser("status").set_defaults(handler=command_status)
    ingest = commands.add_parser("ingest")
    ingest.set_defaults(handler=command_ingest)
    ingest.add_argument("run_id", type=int)
    commands.add_parser("disagreements").set_defaults(handler=command_disagreements)
    commands.add_parser("cost").set_defaults(handler=command_cost)
    args = parser.parse_args()

    load_dotenv()
    with db.connect() as connection:
        args.handler(anthropic.Anthropic(), connection, args)


if __name__ == "__main__":
    main()

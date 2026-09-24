# NOTAM Gold Evaluation Set

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](setup.sh)

This repo builds a human-reviewed gold set of NOTAM extractions. The set measures how accurately the SF50 TOLD app's on-device model reads runway-performance data from raw NOTAM text.

On iOS 27, the app uses Apple's stock Foundation Models model. The model *proposes* runway effects from a NOTAM, and the pilot confirms them. Before that ships, the app's Evaluations harness scores the model against the labels in [`eval/`](eval/). Every label there has been reviewed by a person.

```text
[NOTAM API] → corpus → strata → gold candidates → silver labels (2 runs) → human review → eval/
```

## The contract

[`schema/notam_extraction.schema.json`](schema/notam_extraction.schema.json) is the extraction schema, and [`schema/SCHEMA.md`](schema/SCHEMA.md) gives the rule for every field, with worked examples. The app mirrors the schema as a `@Generable` Swift struct. Any change to it is a cross-repo change.

The core rule: **a label records only what the NOTAM text states**. An absent fact is `null`, and the evaluation scores that `null`. Units and designators are recorded as written. The app does all derivation (shortening, per-direction effects, contamination categories) itself.

## Setup

```bash
./setup.sh                # pyenv virtualenv "notam-gold" + dependencies
cp .env.example .env      # then fill in ANTHROPIC_API_KEY and NOTAM_API_TOKEN
```

## Pipeline

### 1. Corpus

```bash
./download_notams.py
```

Downloads every NOTAM from the NOTAM API into `data/notams_<date>.jsonl.gz`. It pages by keyset on `effective_start`, because deep offsets time out on the server. It then merges the download with the legacy snapshot `data/all_notams.json` into `data/corpus.jsonl.gz`.

`notam_id` alone isn't unique, because series numbers repeat between countries. NOTAMs are therefore identified by location plus `notam_id`, and deduplicated on that and then on their content. To re-merge without downloading again, pass `--skip-download`.

### 2. Strata and gold candidates

```bash
./select_gold.py [--seed 2026]
```

A regex pass tags each NOTAM with strata:

- declared distances
- displaced threshold
- partial closure
- full closure
- condition report with or without RwyCC
- obstacle
- cancelled
- plausible negative
- other negative

A seeded, reproducible selection then writes about 550 candidates to `data/notam_gold.sqlite`:

- every displaced-threshold and declared-distance NOTAM, up to 150;
- stratified samples of the rest;
- at least 25% negatives, mostly plausible ones.

Reissued NOTAMs are collapsed to one each, and each stratum is spread across airports.

### 3. Silver labels

```bash
./label_silver.py estimate A          # projected cost
./label_silver.py submit A --pilot 20
./label_silver.py submit A --confirm-cost
./label_silver.py status
./label_silver.py ingest <run id>
./label_silver.py disagreements       # after both runs
./label_silver.py cost
```

Two independent runs label every candidate through the Message Batches API, with structured outputs constrained to the schema:

- run A uses Claude Opus 5.5;
- run B uses Claude Opus 5, with the prompt's examples shuffled.

The cached system prompt is [`labeler/system_prompt.md`](labeler/system_prompt.md), then `SCHEMA.md`, then [`labeler/examples.jsonl`](labeler/examples.jsonl). Each label comes with the exact text it relied on (its evidence) and a note on anything ambiguous.

Every label records its model, prompt version, schema version and timestamp. Silver labels are never modified: database triggers reject updates and deletes. The disagreements between the two runs set the review order.

### 4. Review

```bash
./review.py              # http://127.0.0.1:8765
```

The review app shows one NOTAM per screen:

- **Left:** the NOTAM text, with each label's evidence highlighted. Focusing a field lights up its span.
- **Right:** the full schema as a form, prefilled from run A.
- **Disagreements:** fields where run B disagreed are shown in amber, with run B's value alongside.

| Key | Action |
|---|---|
| `A` | Accept |
| `S` / ⌘↵ | Save edits |
| `M` | Mark ambiguous (kept, but excluded from the gold set) |
| `K` | Skip |
| `N` | Note |
| `J` / `P` | Next / previous |
| `?` | Help |

The queue opens on unreviewed NOTAMs, most disagreement first. You can filter it by stratum, by disagreement, and by status.

Reviews are stored separately from silver labels and are append-only. Each review records:

- the reviewer, from `git config user.name` or `--reviewer`;
- the time;
- the silver label it started from;
- whether it was edited.

`review.py` backs up the database on start.

### 5. Export

```bash
./export_gold.py
```

Writes the accepted and edited reviews to [`eval/`](eval/) in the Evaluations framework's `ModelSample` shape. The export includes a stable dev/test split; see [`eval/README.md`](eval/README.md).

## Tests

```bash
ruff check . && ruff format --check . && pytest
```

## License

MIT License - see [LICENSE](LICENSE)

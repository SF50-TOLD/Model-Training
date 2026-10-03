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

`./download_notams.py --holdout` collects NOTAMs for a fresh held-out test set. It saves only NOTAMs that nothing local has yet, to `data/holdout/`, and prints how many usable displaced-threshold, partial-closure and declared-distance NOTAMs the holdout has. Those strata are the scarce ones. `data/holdout/` is never merged into the corpus, so training never sees these NOTAMs. Run it at least every few weeks, because the API drops NOTAMs 30 days after they expire.

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
./label_silver.py run A --keys FILE   # relabel a few NOTAMs now, outside a batch
./label_silver.py disagreements       # after both runs
./label_silver.py cost
```

Two independent runs label every candidate through the Message Batches API, with structured outputs constrained to the schema. Before each batch, one synchronous request writes the prompt cache so the batch's requests can read it:

- run A uses Claude Opus 5.5;
- run B uses Claude Opus 5, with the prompt's examples shuffled.

The cached system prompt is [`labeler/system_prompt.md`](labeler/system_prompt.md), then `SCHEMA.md`, then [`labeler/examples.jsonl`](labeler/examples.jsonl). Each label comes with the exact text it relied on (its evidence) and a note on anything ambiguous.

To relabel a few dozen NOTAMs, for example after a rule change, use `run`. It sends the NOTAMs as ordinary synchronous requests at standard prices. Those requests read the prompt cache reliably, whereas concurrent batch requests can miss it and pay for a cache write each.

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

The queue puts re-reviews first (see below), then unreviewed NOTAMs, then everything already decided. Unreviewed NOTAMs go to whichever stratum has the fewest gold labels in its half (dev or test), so every stratum fills evenly. Within a stratum, the NOTAMs the two runs disagree on most come first. You can filter the queue by stratum, half, disagreement and status, and the filters persist across reloads.

When a rule change leads to a NOTAM being relabelled, and the new run-A label differs from the saved review, the NOTAM comes back as **Needs re-review**. The export leaves it out until it's reviewed again.

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

### 6. A fresh held-out set

The test half stays honest only while nobody tunes against it. Once it has gated a few models, a fresh set of NOTAMs that no model has trained or been tuned on replaces it:

```bash
./download_notams.py --holdout        # daily, until the scarce strata fill
./select_holdout.py                   # 200 candidates → data/notam_holdout.sqlite
./label_silver.py --holdout run A --confirm-cost
./label_silver.py --holdout run B --confirm-cost
./label_silver.py --holdout disagreements
./review.py --holdout
./export_gold.py --holdout            # eval/notam_holdout.jsonl
```

Candidates come from the NOTAMs `--holdout` collected, which are newer than the corpus. A stratum they can't fill takes the rest from the [Zenodo dataset 17208970](https://zenodo.org/records/17208970) (CC BY 4.0), downloaded to `data/external/zenodo-17208970/`. Zenodo NOTAMs are rewritten into the text the NOTAM API serves. No candidate shares a reissue template with the corpus, and training selection excludes every held-out candidate, as it does gold. The held-out set has no halves: all of it is for the accuracy gate.

## The training set

Models trained here learn from silver-labelled corpus NOTAMs. Training data never includes a gold
NOTAM, its reissues, or its text, and nothing from `eval/notam_dev.jsonl` or
`eval/notam_test.jsonl`. Run these steps from the repository root.

1. `swift run -c release --package-path ../iOS/NOTAMModel notam-corpus < <(gzip -dc data/corpus.jsonl.gz) > data/parsed.jsonl`
   lists the NOTAMs the app's parsers read, which are left out.
2. `python -m training.select_training --parsed data/parsed.jsonl` samples the training NOTAMs
   into `data/notam_train.sqlite`.
3. `python -m training.label_budgeted A --budget 180 --dual-only`, then `… B …`, then `… A …` labels
   them in synchronous chunks sized so the worst case never passes the budget. Strata where run A
   alone erred on reviewed gold get both runs and keep only agreements.
4. `python -m training.build_dataset` writes `data/training/{train,val}.jsonl`.

## Tests

```bash
ruff check . && ruff format --check . && pytest
```

`tests/e2e/` drives the review site through Playwright in headless Chromium and in WebKit, the engine Safari uses. Each test gets the app running over its own freshly seeded temporary database, never `data/`. `setup.sh` installs both browsers; to install them by hand, run `python -m playwright install chromium webkit`.

## License

MIT License - see [LICENSE](LICENSE)

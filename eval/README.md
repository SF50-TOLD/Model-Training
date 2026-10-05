# Gold NOTAM evaluation set

These files contain reviewed NOTAM extractions for Xcode's Evaluations framework. `export_gold.py` generates them; don't edit them by hand.

| File | Contents |
| --- | --- |
| `notam_gold.jsonl` | Every NOTAM whose review was accepted or edited |
| `notam_dev.jsonl` | About 40% of them, for tuning instructions |
| `notam_test.jsonl` | The other 60%, held out for the accuracy gate |
| `notam_holdout.jsonl` | A fresh held-out set of NOTAMs no model has trained or been tuned on, for the accuracy gate once the test half has been used up |

Each sample line is a `ModelSample`:

```json
{"input": {"prompt": "Location: KSFO\n\nSFO RWY 28L DECLARED DIST: …"}, "output": {"value": {"isCanceled": false, "effects": […], "obstacles": […]}}}
```

- `prompt` is exactly what the app sends: `Location: <icao_location>`, a blank line, then the NOTAM text as the NOTAM API returns it.
- `value` follows [`schema/notam_extraction.schema.json`](../schema/notam_extraction.schema.json). Every key is present, `null` means the NOTAM doesn't state that fact, and effects, obstacles and contaminants are in canonical order.
- There is no `instructions` key; the app supplies its own.

Each `.jsonl` file has a matching `.meta.jsonl` file. Meta line *n* describes sample line *n*, and carries these fields:

- `notamId`, `icaoLocation`, `notamKey`
- `strata` and `selectedStratum`
- `reviewer`, `reviewedAt`, `edited`
- `schemaVersion`
- `silverModel`, `silverPromptVersion`, `silverLabelId`
- `silverDisagreement`, `disagreementPaths`
- `metadataCanceled`: the NMS message type is C, whether or not the text says so
- `source`: where the NOTAM came from: the month of the NOTAM API download (`2025-11`, `2026-09`), the date of a held-out collection, or `zenodo-17208970`
- `workedExample`: the NOTAM is also a worked example in `SCHEMA.md` or the labeler prompt
- `effectiveStart`, `effectiveEnd`

A salted hash of `notamKey` assigns each NOTAM to dev or test. A NOTAM therefore stays in the same half when the set grows or is re-exported. The split is stratified in expectation; the export prints the per-stratum counts. Worked examples never go in `notam_test.jsonl`, because the model may have seen their answers.

Some held-out NOTAMs (`source` `zenodo-17208970`) come from the dataset published with "A semi-supervised approach to multi-label classification of NOTAMs using BERT", [Zenodo record 17208970](https://zenodo.org/records/17208970), under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). They are rewritten into the text form the NOTAM API serves (the E) item, or an FAA domestic NOTAM without its header and validity times) and labelled here.

# Gold NOTAM evaluation set

These files contain reviewed NOTAM extractions for Xcode's Evaluations framework. `export_gold.py` generates them; don't edit them by hand.

| File | Contents |
|---|---|
| `notam_gold.jsonl` | Every NOTAM whose review was accepted or edited |
| `notam_dev.jsonl` | About 40% of them, for tuning instructions |
| `notam_test.jsonl` | The other 60%, held out for the accuracy gate |

Each sample line is a `ModelSample`:

```json
{"input": {"prompt": "Location: KSFO\n\nSFO RWY 28L DECLARED DIST: …"}, "output": {"value": {"isCanceled": false, "effects": […]}}}
```

- `prompt` is exactly what the app sends: `Location: <icao_location>`, a blank line, then the NOTAM text as the NOTAM API returns it.
- `value` follows [`schema/notam_extraction.schema.json`](../schema/notam_extraction.schema.json). Every key is present, `null` means the NOTAM doesn't state that fact, and effects and contaminants are in canonical order.
- There is no `instructions` key; the app supplies its own.

Each `.jsonl` file has a matching `.meta.jsonl` file. Meta line *n* describes sample line *n*, and carries these fields:

- `notamId`, `icaoLocation`, `notamKey`
- `strata` and `selectedStratum`
- `reviewer`, `reviewedAt`, `edited`
- `schemaVersion`
- `silverModel`, `silverPromptVersion`, `silverLabelId`
- `silverDisagreement`, `disagreementPaths`
- `metadataCanceled`: the NMS message type is C, whether or not the text says so
- `effectiveStart`, `effectiveEnd`

A salted hash of `notamKey` assigns each NOTAM to dev or test. A NOTAM therefore stays in the same half when the set grows or is re-exported. The split is stratified in expectation; the export prints the per-stratum counts.

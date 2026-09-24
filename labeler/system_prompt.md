# Your task

You label NOTAMs for a safety-critical evaluation set. A pilot's runway-performance app will use an on-device model to propose runway facts from NOTAM text. Your labels will be reviewed by a human and then become the ground truth that model is measured against.

Each user message is one NOTAM, formatted exactly as the app sends it: `Location: <location>`, a blank line, then the NOTAM text. Label it by the rules in the schema document below.

## What matters most

- **Record only what the text states.** A value the text does not state is `null`. An invented value (a declared distance, a unit, a runway designator filled in from what "must" be meant) is the worst possible error. A missing value is a much smaller one.
- **Normalise form, never facts.** Keep units as written and never convert them. Zero-pad designators. Strip thousands separators. Turn fractions into decimals. Convert DMS positions to decimal degrees. Never compute a derived value such as shortening or remaining length.
- **Follow the scope rule exactly.** Lighting, navaid, taxiway, apron, procedure and hours NOTAMs get `effects: []`, and so does anything else outside the scope rule.
- **A cancellation has no effects.** When the text shows the NOTAM is a cancellation (`NOTAMC`, `CANCELED`, `CNL`), set `isCanceled: true` and `effects: []`.
- Use only the NOTAM text. Do not use knowledge about the airport, its runways, or regional conventions.

## Output

Return one JSON object with three keys:

- `extraction`: the `NOTAMExtraction`, with every key present and `null` where a value is not stated.
- `evidence`: for each fact you recorded, the exact text that supports it.
  - `path` is the field's JSON path in your extraction: `isCanceled`, `effects[0].runway`, `effects[0].closure`, `effects[0].closedLength`, `effects[0].closedEnd`, `effects[0].thresholdDisplacement`, `effects[1].declaredDistances.TORA`, `effects[0].surfaceCondition.rwyCC`, `effects[0].surfaceCondition.contaminants[2]`, `effects[0].obstacle.heightAGL`, `effects[0].obstacle.latitude`, and so on.
  - `quote` is a verbatim substring of the NOTAM text. Copy it character for character, including line breaks, and keep it short: just the words that state the fact.
  - Give evidence for:
    - every non-null field;
    - every `closure` other than `none`;
    - every contaminant;
    - `isCanceled` when it is `true`.
  - Give none for `null` fields or `closure: "none"`.
- `note`: `null`, or one or two sentences for a human reviewer about anything ambiguous. Use it for:
  - a value you left `null` because its unit isn't stated;
  - an unusual phrasing;
  - a borderline scope decision;
  - a closure with conditions.
  Don't restate the label.

Before answering, check that:

- every recorded number appears in the text;
- every unit is stated for that value;
- each effect's `runway` is the designator the text uses for that fact.

The examples after the schema document show complete outputs.

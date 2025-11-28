#!/usr/bin/env python3
"""
Format silver labels into FoundationModels adapter training format.

This script converts the silver dataset into the JSONL format required
by Apple's FoundationModels adapter training toolkit.
"""

import json
import random
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "data" / "silver_dataset.jsonl"
OUTPUT_DIR = Path(__file__).parent / "data"

TRAIN_FILE = OUTPUT_DIR / "train.jsonl"
VALID_FILE = OUTPUT_DIR / "valid.jsonl"
TEST_FILE = OUTPUT_DIR / "test.jsonl"

# Training data split ratios
TRAIN_RATIO = 0.8
VALID_RATIO = 0.1
TEST_RATIO = 0.1

# Random seed for reproducibility
RANDOM_SEED = 42


def is_canceled_notam(notam_text: str) -> bool:
    """Check if NOTAM text indicates a cancellation."""
    text_upper = notam_text.upper()
    # Common cancellation indicators
    return any(indicator in text_upper for indicator in [
        "CANCEL",
        "NOTAMC",  # NOTAM Cancel
        "CNL",     # Cancel abbreviation
        "CNCL",    # Cancel abbreviation
        "WITHDRAWN",
    ])


def format_as_training_example(item: dict) -> list[dict] | None:
    """
    Convert a silver label item to FoundationModels training format.

    The format is a list of messages:
    [
        {"role": "user", "content": "prompt"},
        {"role": "assistant", "content": "response"}
    ]

    Each runway entry becomes a separate training example.
    """
    notam_id = item.get("notam_id", "UNKNOWN")
    notam_text = item.get("notam_text", "")
    icao_location = item.get("icao_location", "")
    effective_start = item.get("effective_start", "")
    effective_end = item.get("effective_end", "")
    runway_entries = item.get("runway_entries", [])

    if not notam_text.strip():
        return None

    # Detect cancellation from text
    is_canceled = is_canceled_notam(notam_text)

    # If no runway entries, this is a non-runway NOTAM - skip it
    if not runway_entries:
        return None

    examples = []

    for entry in runway_entries:
        runway = entry.get("runway")

        # Build user prompt with all context
        user_content = f"""Extract runway performance data from this NOTAM.

Airport: {icao_location}
Runway: {runway or "ALL"}
Effective: {effective_start} to {effective_end}

NOTAM {notam_id}:
{notam_text}"""

        # Build assistant response (structured JSON) with all fields
        response_data = {
            "airportID": icao_location,
            "runway": runway,
            "effectiveStart": effective_start,
            "effectiveEnd": effective_end,
            "isCanceled": is_canceled,
            "runwayClosed": entry.get("runwayClosed"),
            # Shortening
            "takeoffShortening": entry.get("takeoffShortening"),
            "takeoffShorteningUnits": entry.get("takeoffShorteningUnits"),
            "landingShortening": entry.get("landingShortening"),
            "landingShorteningUnits": entry.get("landingShorteningUnits"),
            # Declared distances
            "TORA": entry.get("TORA"),
            "TORAUnits": entry.get("TORAUnits"),
            "TODA": entry.get("TODA"),
            "TODAUnits": entry.get("TODAUnits"),
            "LDA": entry.get("LDA"),
            "LDAUnits": entry.get("LDAUnits"),
            # Obstacles
            "obstacleHeight": entry.get("obstacleHeight"),
            "obstacleHeightUnits": entry.get("obstacleHeightUnits"),
            "obstacleHeightMSL": entry.get("obstacleHeightMSL"),
            "obstacleHeightMSLUnits": entry.get("obstacleHeightMSLUnits"),
            "obstacleDistance": entry.get("obstacleDistance"),
            "obstacleDistanceUnits": entry.get("obstacleDistanceUnits"),
            "obstacleBearing": entry.get("obstacleBearing"),
            "obstacleCoordinates": entry.get("obstacleCoordinates"),
            "obstacleReferencePoint": entry.get("obstacleReferencePoint"),
            # Contamination
            "contaminations": entry.get("contaminations", []),
            # Climb
            "requiredClimbGradient": entry.get("requiredClimbGradient"),
            "requiredClimbGradientUnits": entry.get("requiredClimbGradientUnits"),
            # Source
            "sourceNOTAMIds": [notam_id],
            "notes": entry.get("notes"),
        }

        # Format with exactly 1 space after each comma and colon (required for guided generation)
        assistant_content = json.dumps(response_data, separators=(", ", ": "))

        example = [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]

        examples.append(example)

    return examples


def load_silver_dataset() -> list[dict]:
    """Load the silver dataset from JSONL file."""
    items = []

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return items


def split_dataset(
    examples: list, train_ratio: float, valid_ratio: float, test_ratio: float
) -> tuple[list, list, list]:
    """Split dataset into train/valid/test sets."""
    random.seed(RANDOM_SEED)
    random.shuffle(examples)

    n = len(examples)
    train_end = int(n * train_ratio)
    valid_end = train_end + int(n * valid_ratio)

    train = examples[:train_end]
    valid = examples[train_end:valid_end]
    test = examples[valid_end:]

    return train, valid, test


def save_jsonl(examples: list, filepath: Path):
    """Save examples to JSONL file."""
    with open(filepath, "w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Training Data Formatter - FoundationModels Format")
    print("=" * 60)

    # Load silver dataset
    if not INPUT_FILE.exists():
        print(f"Error: Input file not found: {INPUT_FILE}")
        print("Run generate_silver_labels.py first.")
        return

    print(f"Loading silver dataset from {INPUT_FILE}...")
    items = load_silver_dataset()
    print(f"Loaded {len(items)} labeled NOTAMs")

    # Convert to training examples
    print("\nConverting to training format...")
    all_examples = []
    skipped = 0
    notams_with_entries = 0

    for item in items:
        examples = format_as_training_example(item)
        if examples:
            all_examples.extend(examples)
            notams_with_entries += 1
        else:
            skipped += 1

    print(f"Generated {len(all_examples)} training examples from {notams_with_entries} NOTAMs")
    print(f"Skipped {skipped} items (empty, invalid, or non-runway NOTAMs)")

    # Split dataset
    print(f"\nSplitting dataset ({TRAIN_RATIO:.0%}/{VALID_RATIO:.0%}/{TEST_RATIO:.0%})...")
    train, valid, test = split_dataset(
        all_examples, TRAIN_RATIO, VALID_RATIO, TEST_RATIO
    )

    print(f"  Train: {len(train)} examples")
    print(f"  Valid: {len(valid)} examples")
    print(f"  Test: {len(test)} examples")

    # Save files
    print(f"\nSaving training files...")
    save_jsonl(train, TRAIN_FILE)
    print(f"  {TRAIN_FILE}")

    save_jsonl(valid, VALID_FILE)
    print(f"  {VALID_FILE}")

    save_jsonl(test, TEST_FILE)
    print(f"  {TEST_FILE}")

    # Print sample
    print("\n" + "-" * 60)
    print("Sample training example:")
    print("-" * 60)
    if train:
        sample = train[0]
        print(f"User: {sample[0]['content'][:200]}...")
        print(f"\nAssistant: {sample[1]['content']}")

    print("\n" + "=" * 60)
    print("Formatting Complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

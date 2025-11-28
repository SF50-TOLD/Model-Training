#!/usr/bin/env python3
"""
Generate silver labels for NOTAMs using Claude API.

This script processes filtered NOTAMs and uses Claude to extract structured
runway performance data, creating a silver dataset for adapter training.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from tqdm.asyncio import tqdm

# Load environment variables
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Error: ANTHROPIC_API_KEY not set in .env file")
    sys.exit(1)

INPUT_FILE = Path(__file__).parent / "data" / "filtered_notams.json"
OUTPUT_FILE = Path(__file__).parent / "data" / "silver_dataset.jsonl"
LOW_CONFIDENCE_FILE = Path(__file__).parent / "data" / "low_confidence.jsonl"

# Initialize async Anthropic client
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Concurrent request limit (Anthropic rate limit is typically 50-100 RPM for most tiers)
MAX_CONCURRENT = 20

EXTRACTION_PROMPT = """You are a NOTAM parsing expert for aviation runway performance calculations.
Extract runway performance data from this NOTAM. Create ONE ENTRY PER RUNWAY if conditions differ.

NOTAM {notam_id}:
{notam_text}

Return a JSON array of runway entries. Each entry has these fields (use null if not applicable):

RUNWAY IDENTIFICATION:
- runway: The runway designator (e.g., "09L", "27R"). Use null ONLY if this NOTAM doesn't affect any runway.
- runwayClosed: true if runway is fully closed, false otherwise

RUNWAY SHORTENING (displaced thresholds, partial closures):
- takeoffShortening: Number for takeoff distance reduction
- takeoffShorteningUnits: "ft" or "m" (preserve original units, no conversion)
- landingShortening: Number for landing distance reduction
- landingShorteningUnits: "ft" or "m"

DECLARED DISTANCES (if explicitly stated):
- TORA: Takeoff Run Available
- TORAUnits: "ft" or "m"
- TODA: Takeoff Distance Available
- TODAUnits: "ft" or "m"
- LDA: Landing Distance Available
- LDAUnits: "ft" or "m"

OBSTACLES (cranes, towers, etc.):
- obstacleHeight: Height AGL (use HTG value, NOT ELEV)
- obstacleHeightUnits: "ft" or "m"
- obstacleHeightMSL: Elevation above sea level (ELEV value)
- obstacleHeightMSLUnits: "ft" or "m"
- obstacleDistance: Distance from reference point
- obstacleDistanceUnits: "ft", "m", or "nm"
- obstacleBearing: Bearing from reference point (degrees magnetic or true)
- obstacleCoordinates: GPS coordinates if provided (e.g., "6449N14751W")
- obstacleReferencePoint: What the distance is measured from (e.g., "THR 27", "ARP")

CONTAMINATION (FICON reports only):
- contaminations: Array of contamination objects, each with:
  - type: One of [water, slush, wetSnow, drySnow, ice, compactedSnow, sand, mud, rubber, oil, fuel, gravel, vegetation]
  - coverage: Percentage if stated (e.g., 80)
  - depth: Depth value if stated
  - depthUnits: "in", "mm", or "cm"

CLIMB REQUIREMENTS:
- requiredClimbGradient: Minimum climb gradient if stated
- requiredClimbGradientUnits: "percent" or "ft/nm"

METADATA:
- confidence: 0.0-1.0 (1.0 = clear, unambiguous; <0.5 = uncertain)
- notes: Any warnings or ambiguities

CRITICAL RULES:
1. APRON/TAXIWAY NOTAMs: Set runway to null. These do NOT affect runways.
2. U/S OBSTACLE LIGHTS: These are NOT obstacle NOTAMs. Only extract if there's an actual obstacle hazard.
3. UAV/DRONE ACTIVITY with radius: These are NOT obstacles. Set all obstacle fields to null.
4. Q-LINE COORDINATES (e.g., "6449N14751W005"): These are GPS positions, NOT distances!
5. APPROACH OBSTACLES: If obstacle is from "approach threshold" of RWY XX, it affects the RECIPROCAL runway (relevant for climbout/go-around).
6. "RWY" WITHOUT NUMBER: If airport has one runway, this means all runway directions (e.g., ["09", "27"]).
7. RUNWAY-SPECIFIC CONDITIONS: If a NOTAM lists different contaminations for different runways, create separate entries.
8. NO UNIT CONVERSION: Preserve original units exactly as stated in the NOTAM.
9. NON-RUNWAY NOTAMs: If NOTAM doesn't affect runway performance (ILS outage, lighting, etc.), return empty array [].

Return ONLY valid JSON array, no explanation:
[{{"runway": "09", "runwayClosed": false, "takeoffShortening": null, "takeoffShorteningUnits": null, "landingShortening": null, "landingShorteningUnits": null, "TORA": null, "TORAUnits": null, "TODA": null, "TODAUnits": null, "LDA": null, "LDAUnits": null, "obstacleHeight": null, "obstacleHeightUnits": null, "obstacleHeightMSL": null, "obstacleHeightMSLUnits": null, "obstacleDistance": null, "obstacleDistanceUnits": null, "obstacleBearing": null, "obstacleCoordinates": null, "obstacleReferencePoint": null, "contaminations": [], "requiredClimbGradient": null, "requiredClimbGradientUnits": null, "confidence": 0.9, "notes": null}}]"""


async def extract_notam_data(notam: dict, semaphore: asyncio.Semaphore) -> dict | None:
    """Use Claude to extract structured data from a NOTAM."""
    notam_id = notam.get("notam_id", "UNKNOWN")
    notam_text = notam.get("notam_text", "")

    if not notam_text.strip():
        return None

    prompt = EXTRACTION_PROMPT.format(notam_id=notam_id, notam_text=notam_text)

    async with semaphore:
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract JSON from response
            content = response.content[0].text.strip()

            # Try to parse as JSON array
            try:
                extraction = json.loads(content)
            except json.JSONDecodeError:
                # Try to find JSON array in response
                json_match = re.search(r"\[.*\]", content, re.DOTALL)
                if json_match:
                    extraction = json.loads(json_match.group())
                else:
                    # Try to find single object
                    json_match = re.search(r"\{.*\}", content, re.DOTALL)
                    if json_match:
                        extraction = [json.loads(json_match.group())]
                    else:
                        return None

            # Ensure extraction is a list
            if isinstance(extraction, dict):
                extraction = [extraction]

            # Calculate minimum confidence across all runway entries
            min_confidence = min(
                (entry.get("confidence", 1.0) for entry in extraction),
                default=1.0
            )

            return {
                "notam_id": notam.get("notam_id"),
                "icao_location": notam.get("icao_location"),
                "notam_text": notam.get("notam_text"),
                "effective_start": notam.get("effective_start"),
                "effective_end": notam.get("effective_end"),
                "runway_entries": extraction,
                "min_confidence": min_confidence,
            }

        except Exception as e:
            print(f"\nError processing {notam_id}: {e}")
            return None


async def process_notams_async(notams: list[dict]) -> list[dict]:
    """Process NOTAMs concurrently with rate limiting."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    tasks = [extract_notam_data(notam, semaphore) for notam in notams]

    results = []
    for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Processing NOTAMs"):
        result = await coro
        if result:
            results.append(result)

            # Write incrementally to file
            with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return results


async def main_async():
    """Main async entry point."""
    print("=" * 60)
    print("Silver Label Generator - Claude API (Async)")
    print("=" * 60)
    print(f"Concurrent requests: {MAX_CONCURRENT}")

    # Load filtered NOTAMs
    if not INPUT_FILE.exists():
        print(f"Error: Input file not found: {INPUT_FILE}")
        print("Run filter_relevant_notams.py first.")
        return

    print(f"Loading NOTAMs from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        notams = json.load(f)

    print(f"Loaded {len(notams)} NOTAMs to process")
    print()

    # Check for existing partial results
    existing_ids = set()
    if OUTPUT_FILE.exists():
        print(f"Found existing output file, loading processed IDs...")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                    existing_ids.add(item.get("notam_id"))
                except json.JSONDecodeError:
                    continue
        print(f"Already processed: {len(existing_ids)} NOTAMs")

    # Filter out already processed NOTAMs
    notams_to_process = [n for n in notams if n.get("notam_id") not in existing_ids]
    print(f"Remaining to process: {len(notams_to_process)} NOTAMs")

    if not notams_to_process:
        print("All NOTAMs already processed!")
        return

    # Process NOTAMs
    print("\nProcessing NOTAMs with Claude API...")
    results = await process_notams_async(notams_to_process)

    # Load all results (including previously processed)
    all_results = []
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                all_results.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Separate low confidence results
    low_confidence = [r for r in all_results if r.get("min_confidence", 1.0) < 0.8]

    print(f"\nSaving {len(low_confidence)} low-confidence results to {LOW_CONFIDENCE_FILE}...")
    with open(LOW_CONFIDENCE_FILE, "w", encoding="utf-8") as f:
        for result in low_confidence:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Print summary
    print("\n" + "=" * 60)
    print("Processing Complete!")
    print("=" * 60)
    print(f"Newly processed: {len(results)} NOTAMs")
    print(f"Total in dataset: {len(all_results)} NOTAMs")
    print(f"Low confidence (<0.8): {len(low_confidence)}")

    # Count extraction types across all runway entries
    total_runway_entries = sum(len(r.get("runway_entries", [])) for r in all_results)
    contamination_count = sum(
        1 for r in all_results
        for entry in r.get("runway_entries", [])
        if entry.get("contaminations")
    )
    shortening_count = sum(
        1 for r in all_results
        for entry in r.get("runway_entries", [])
        if entry.get("takeoffShortening") or entry.get("landingShortening")
    )
    obstacle_count = sum(
        1 for r in all_results
        for entry in r.get("runway_entries", [])
        if entry.get("obstacleHeight")
    )
    closure_count = sum(
        1 for r in all_results
        for entry in r.get("runway_entries", [])
        if entry.get("runwayClosed")
    )

    print(f"\nExtraction breakdown:")
    print(f"  Total runway entries: {total_runway_entries}")
    print(f"  Contamination: {contamination_count}")
    print(f"  Distance shortening: {shortening_count}")
    print(f"  Obstacles: {obstacle_count}")
    print(f"  Closures: {closure_count}")


def main():
    """Sync wrapper for main."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Test the labeler on a small subset of NOTAMs.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Error: ANTHROPIC_API_KEY not set in .env file")
    sys.exit(1)

INPUT_FILE = Path(__file__).parent / "data" / "test_subset.json"
OUTPUT_FILE = Path(__file__).parent / "data" / "test_output.jsonl"

# Initialize async Anthropic client
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

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


async def extract_notam_data(notam: dict) -> dict | None:
    """Use Claude to extract structured data from a NOTAM."""
    notam_id = notam.get("notam_id", "UNKNOWN")
    notam_text = notam.get("notam_text", "")

    if not notam_text.strip():
        return None

    prompt = EXTRACTION_PROMPT.format(notam_id=notam_id, notam_text=notam_text)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract JSON from response
        content = response.content[0].text.strip()
        print(f"\n--- Raw response for {notam_id} ---")
        print(content)
        print("---")

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
                    print(f"Failed to parse JSON for {notam_id}")
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


async def main():
    """Main entry point."""
    print("=" * 60)
    print("Test Labeler - Small Subset")
    print("=" * 60)

    # Load test subset
    if not INPUT_FILE.exists():
        print(f"Error: Input file not found: {INPUT_FILE}")
        print("Create test_subset.json first.")
        return

    print(f"Loading NOTAMs from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        notams = json.load(f)

    print(f"Loaded {len(notams)} NOTAMs to process")

    # Process each NOTAM
    results = []
    for notam in notams:
        print(f"\nProcessing {notam.get('notam_id')}...")
        result = await extract_notam_data(notam)
        if result:
            results.append(result)
            print(f"  -> {len(result['runway_entries'])} runway entries")

    # Save results
    print(f"\nSaving {len(results)} results to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Print summary
    print("\n" + "=" * 60)
    print("Results Summary:")
    print("=" * 60)
    for result in results:
        print(f"\n{result['notam_id']} ({result['icao_location']}):")
        print(f"  NOTAM: {result['notam_text'][:60]}...")
        for i, entry in enumerate(result['runway_entries']):
            runway = entry.get('runway') or 'null'
            closed = '[CLOSED]' if entry.get('runwayClosed') else ''
            print(f"  Entry {i+1}: Runway {runway} {closed} (confidence: {entry.get('confidence')})")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Filter NOTAMs to identify those potentially relevant to runway performance.

This script applies keyword-based filtering to separate potentially relevant
NOTAMs from those that clearly don't affect runway performance calculations.
"""

import json
import re
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "data" / "all_notams.json"
OUTPUT_FILTERED = Path(__file__).parent / "data" / "filtered_notams.json"
OUTPUT_EXCLUDED = Path(__file__).parent / "data" / "excluded_notams.json"

# Keywords that indicate potential relevance to runway performance
INCLUSION_KEYWORDS = {
    # Runway-related
    "RWY",
    "RUNWAY",
    "THR",
    "THRESHOLD",
    # Contamination
    "FICON",
    "CONTAMINATED",
    "ICE",
    "SNOW",
    "SN",
    "SLUSH",
    "WATER",
    "WET",
    "COMPACTED",
    "BRAKING",
    # Obstacles
    "OBST",
    "OBSTACLE",
    "CRANE",
    "TOWER",
    "HTG",
    # Closures and displacements
    "CLSD",
    "CLOSED",
    "DSPLCD",
    "DISPLACED",
}

# Keywords for NOTAMs that should be excluded UNLESS they also contain runway keywords
NAVIGATION_KEYWORDS = {"ILS", "VOR", "GPS", "NDB", "DME", "RNAV", "LOC", "GS", "PAPI", "VASI"}
PROCEDURE_KEYWORDS = {"APCH", "APPROACH", "DEP", "DEPARTURE", "SID", "STAR", "IAP"}
TAXIWAY_ONLY_PATTERN = re.compile(r"\bTWY\b(?!.*\bRWY\b)", re.IGNORECASE)


def has_inclusion_keyword(text: str) -> bool:
    """Check if text contains any inclusion keyword."""
    text_upper = text.upper()
    return any(kw in text_upper for kw in INCLUSION_KEYWORDS)


def has_runway_reference(text: str) -> bool:
    """Check if text contains a runway reference."""
    text_upper = text.upper()
    # Match RWY, RUNWAY, or specific runway patterns like "RWY 04R/22L"
    return "RWY" in text_upper or "RUNWAY" in text_upper


def is_navigation_only(text: str) -> bool:
    """Check if NOTAM is navigation-related without runway performance impact."""
    text_upper = text.upper()

    # If it has runway reference with performance keywords, it's relevant
    if has_runway_reference(text_upper):
        # Check for displacement, closure, or contamination
        if any(kw in text_upper for kw in ["DSPLCD", "CLSD", "CLOSED", "FICON", "CONTAMINATED"]):
            return False

    # Check if it's purely navigation-related
    has_nav = any(kw in text_upper for kw in NAVIGATION_KEYWORDS)
    has_proc = any(kw in text_upper for kw in PROCEDURE_KEYWORDS)

    if has_nav or has_proc:
        # Only exclude if there's no runway performance impact
        if not has_runway_reference(text_upper):
            return True
        # Check for specific nav-only phrases
        nav_only_phrases = [
            "U/S",  # Unserviceable
            "OTS",  # Out of service
            "NOT AVBL",  # Not available
            "INOP",  # Inoperative
            "ON TEST",  # Testing
            "MAINT",  # Maintenance
        ]
        if any(phrase in text_upper for phrase in nav_only_phrases):
            # If it's just about nav equipment status, likely not runway performance
            if not any(kw in text_upper for kw in ["DSPLCD", "CLSD", "FICON", "CONTAMINATED"]):
                return True

    return False


def is_taxiway_only(text: str) -> bool:
    """Check if NOTAM is taxiway-only without runway reference."""
    return bool(TAXIWAY_ONLY_PATTERN.search(text))


def classify_notam(notam: dict) -> tuple[bool, str]:
    """
    Classify a NOTAM as relevant or not.

    Returns:
        tuple: (is_relevant: bool, reason: str)
    """
    text = notam.get("notam_text", "")

    # Check for empty text
    if not text.strip():
        return False, "empty_text"

    # Check for taxiway-only NOTAMs
    if is_taxiway_only(text):
        return False, "taxiway_only"

    # Check for navigation-only NOTAMs
    if is_navigation_only(text):
        return False, "navigation_only"

    # Check for inclusion keywords
    if has_inclusion_keyword(text):
        return True, "has_relevant_keyword"

    # Default: exclude if no inclusion keywords
    return False, "no_relevant_keywords"


def filter_notams(notams: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Filter NOTAMs into relevant and excluded lists.

    Returns:
        tuple: (relevant_notams, excluded_notams)
    """
    relevant = []
    excluded = []

    exclusion_reasons = {}

    for notam in notams:
        is_relevant, reason = classify_notam(notam)

        if is_relevant:
            relevant.append(notam)
        else:
            notam["_exclusion_reason"] = reason
            excluded.append(notam)
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

    return relevant, excluded, exclusion_reasons


def main():
    """Main entry point."""
    print("=" * 60)
    print("NOTAM Filter - Keyword-Based Relevance Classification")
    print("=" * 60)

    # Load NOTAMs
    if not INPUT_FILE.exists():
        print(f"Error: Input file not found: {INPUT_FILE}")
        print("Run download_all_notams.py first.")
        return

    print(f"Loading NOTAMs from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        notams = json.load(f)

    print(f"Loaded {len(notams)} NOTAMs")
    print()

    # Filter NOTAMs
    print("Filtering NOTAMs...")
    relevant, excluded, exclusion_reasons = filter_notams(notams)

    # Save results
    print(f"\nSaving {len(relevant)} relevant NOTAMs to {OUTPUT_FILTERED}...")
    with open(OUTPUT_FILTERED, "w", encoding="utf-8") as f:
        json.dump(relevant, f, indent=2, ensure_ascii=False)

    print(f"Saving {len(excluded)} excluded NOTAMs to {OUTPUT_EXCLUDED}...")
    with open(OUTPUT_EXCLUDED, "w", encoding="utf-8") as f:
        json.dump(excluded, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("Filtering Complete!")
    print("=" * 60)
    print(f"Total NOTAMs: {len(notams)}")
    print(f"Relevant: {len(relevant)} ({100*len(relevant)/len(notams):.1f}%)")
    print(f"Excluded: {len(excluded)} ({100*len(excluded)/len(notams):.1f}%)")

    print("\nExclusion reasons:")
    for reason, count in sorted(exclusion_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    # Sample some relevant NOTAMs
    print("\n" + "-" * 60)
    print("Sample relevant NOTAMs:")
    print("-" * 60)
    for notam in relevant[:5]:
        print(f"\n[{notam.get('notam_id')}] {notam.get('icao_location')}")
        print(f"  {notam.get('notam_text', '')[:100]}...")


if __name__ == "__main__":
    main()

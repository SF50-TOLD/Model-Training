#!/usr/bin/env python3
"""
Simple CLI tool to review and edit silver labels.

Usage:
    python review_tool.py                    # Review all items
    python review_tool.py --low-confidence   # Review only low-confidence items
    python review_tool.py --random 20        # Review 20 random items
"""

import argparse
import json
import random
import sys
from pathlib import Path

from rich.console import Console

console = Console()

SILVER_FILE = Path(__file__).parent / "data" / "silver_dataset.jsonl"
LOW_CONFIDENCE_FILE = Path(__file__).parent / "data" / "low_confidence.jsonl"

# Valid contamination types
CONTAMINATION_TYPES = [
    "water", "slush", "wetSnow", "drySnow", "ice", "compactedSnow",
    "sand", "mud", "rubber", "oil", "fuel", "gravel", "vegetation"
]

# All runway entry fields grouped by category
RUNWAY_FIELDS = {
    "runway": {"type": "string", "hint": "Runway designator (e.g., 09L, 27R) or null"},
    "runwayClosed": {"type": "bool", "hint": "true if fully closed, false otherwise"},
    # Shortening
    "takeoffShortening": {"type": "number", "hint": "Takeoff distance reduction"},
    "takeoffShorteningUnits": {"type": "string", "hint": "ft or m"},
    "landingShortening": {"type": "number", "hint": "Landing distance reduction"},
    "landingShorteningUnits": {"type": "string", "hint": "ft or m"},
    # Declared distances
    "TORA": {"type": "number", "hint": "Takeoff Run Available"},
    "TORAUnits": {"type": "string", "hint": "ft or m"},
    "TODA": {"type": "number", "hint": "Takeoff Distance Available"},
    "TODAUnits": {"type": "string", "hint": "ft or m"},
    "LDA": {"type": "number", "hint": "Landing Distance Available"},
    "LDAUnits": {"type": "string", "hint": "ft or m"},
    # Obstacles
    "obstacleHeight": {"type": "number", "hint": "Height AGL (use HTG, not ELEV)"},
    "obstacleHeightUnits": {"type": "string", "hint": "ft or m"},
    "obstacleHeightMSL": {"type": "number", "hint": "Elevation MSL (ELEV value)"},
    "obstacleHeightMSLUnits": {"type": "string", "hint": "ft or m"},
    "obstacleDistance": {"type": "number", "hint": "Distance from reference point"},
    "obstacleDistanceUnits": {"type": "string", "hint": "ft, m, or nm"},
    "obstacleBearing": {"type": "number", "hint": "Bearing in degrees"},
    "obstacleCoordinates": {"type": "string", "hint": "GPS coords (e.g., 6449N14751W)"},
    "obstacleReferencePoint": {"type": "string", "hint": "Reference (e.g., THR 27, ARP)"},
    # Climb
    "requiredClimbGradient": {"type": "number", "hint": "Minimum climb gradient"},
    "requiredClimbGradientUnits": {"type": "string", "hint": "percent or ft/nm"},
    # Metadata
    "confidence": {"type": "number", "hint": "0.0-1.0"},
    "notes": {"type": "string", "hint": "Free text notes"},
}


def load_jsonl(filepath: Path) -> list[dict]:
    """Load items from JSONL file."""
    items = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return items


def save_jsonl(items: list[dict], filepath: Path):
    """Save items to JSONL file."""
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def print_field(name: str, value, indent: int = 2):
    """Print a field, graying out None/empty values."""
    prefix = " " * indent
    if value is None or value == [] or value == "":
        console.print(f"{prefix}[grey50]{name}: None[/grey50]")
    else:
        print(f"{prefix}{name}: {value}")


def display_runway_entry(entry: dict, entry_idx: int, total_entries: int):
    """Display a single runway entry."""
    runway = entry.get("runway") or "null"
    closed = entry.get("runwayClosed", False)
    closed_str = " [CLOSED]" if closed else ""
    print(f"\n  --- Runway Entry {entry_idx + 1}/{total_entries}: {runway}{closed_str} ---")

    # Shortening
    has_shortening = entry.get("takeoffShortening") or entry.get("landingShortening")
    if has_shortening:
        print("  Shortening:")
        print_field("takeoffShortening", f"{entry.get('takeoffShortening')} {entry.get('takeoffShorteningUnits') or ''}", 4)
        print_field("landingShortening", f"{entry.get('landingShortening')} {entry.get('landingShorteningUnits') or ''}", 4)

    # Declared distances
    has_declared = entry.get("TORA") or entry.get("TODA") or entry.get("LDA")
    if has_declared:
        print("  Declared Distances:")
        if entry.get("TORA"):
            print_field("TORA", f"{entry.get('TORA')} {entry.get('TORAUnits') or ''}", 4)
        if entry.get("TODA"):
            print_field("TODA", f"{entry.get('TODA')} {entry.get('TODAUnits') or ''}", 4)
        if entry.get("LDA"):
            print_field("LDA", f"{entry.get('LDA')} {entry.get('LDAUnits') or ''}", 4)

    # Obstacles
    has_obstacle = (entry.get("obstacleHeight") or entry.get("obstacleHeightMSL") or
                    entry.get("obstacleDistance") or entry.get("obstacleCoordinates"))
    if has_obstacle:
        print("  Obstacle:")
        if entry.get("obstacleHeight"):
            print_field("height AGL", f"{entry.get('obstacleHeight')} {entry.get('obstacleHeightUnits') or ''}", 4)
        if entry.get("obstacleHeightMSL"):
            print_field("height MSL", f"{entry.get('obstacleHeightMSL')} {entry.get('obstacleHeightMSLUnits') or ''}", 4)
        if entry.get("obstacleDistance"):
            print_field("distance", f"{entry.get('obstacleDistance')} {entry.get('obstacleDistanceUnits') or ''}", 4)
        if entry.get("obstacleBearing"):
            print_field("bearing", f"{entry.get('obstacleBearing')}°", 4)
        if entry.get("obstacleCoordinates"):
            print_field("coordinates", entry.get("obstacleCoordinates"), 4)
        if entry.get("obstacleReferencePoint"):
            print_field("reference", entry.get("obstacleReferencePoint"), 4)

    # Contamination
    contaminations = entry.get("contaminations", [])
    if contaminations:
        print("  Contaminations:")
        for i, c in enumerate(contaminations):
            coverage = f" ({c.get('coverage')}%)" if c.get("coverage") else ""
            depth = f", {c.get('depth')} {c.get('depthUnits')}" if c.get("depth") else ""
            print(f"    [{i+1}] {c.get('type')}{coverage}{depth}")

    # Climb gradient
    if entry.get("requiredClimbGradient"):
        print("  Climb:")
        print_field("requiredClimbGradient", f"{entry.get('requiredClimbGradient')} {entry.get('requiredClimbGradientUnits') or ''}", 4)

    # Metadata
    print_field("confidence", entry.get("confidence"), 2)
    if entry.get("notes"):
        print_field("notes", entry.get("notes"), 2)


def display_item(item: dict, index: int, total: int):
    """Display a single NOTAM item with its runway entries."""
    print("\n" + "=" * 70)
    print(f"NOTAM {index + 1} of {total}")
    print("=" * 70)

    print(f"\n[{item.get('notam_id')}] {item.get('icao_location')}")
    print(f"Effective: {item.get('effective_start')} to {item.get('effective_end')}")

    # Check if NOTAM is canceled
    notam_text = item.get("notam_text", "").upper()
    is_canceled = any(indicator in notam_text for indicator in ["CANCEL", "NOTAMC", "CNL", "CNCL", "WITHDRAWN"])
    print(f"Canceled: {is_canceled}")
    print()
    print("NOTAM Text:")
    print("-" * 40)
    print(item.get("notam_text", ""))
    print("-" * 40)

    runway_entries = item.get("runway_entries", [])
    if not runway_entries:
        console.print("\n[grey50]No runway entries (non-runway NOTAM)[/grey50]")
    else:
        print(f"\nRunway Entries ({len(runway_entries)}):")
        for i, entry in enumerate(runway_entries):
            display_runway_entry(entry, i, len(runway_entries))

    print(f"\nMin Confidence: {item.get('min_confidence', 'N/A')}")


def edit_simple_field(entry: dict, field: str) -> bool:
    """Edit a simple field in a runway entry."""
    field_info = RUNWAY_FIELDS.get(field, {})
    field_type = field_info.get("type", "string")
    hint = field_info.get("hint", "")

    current_value = entry.get(field)
    print(f"\nCurrent value for '{field}': {current_value}")
    if hint:
        console.print(f"  [grey50]Hint: {hint}[/grey50]")

    new_value = input("New value (or 'null', or Enter to keep): ").strip()

    if not new_value:
        return False

    if new_value.lower() == "null":
        entry[field] = None
    elif field_type == "number":
        try:
            entry[field] = float(new_value)
        except ValueError:
            print("Invalid number, keeping original value")
            return False
    elif field_type == "bool":
        entry[field] = new_value.lower() in ["true", "yes", "1", "y"]
    else:
        entry[field] = new_value

    return True


def edit_contaminations(entry: dict) -> bool:
    """Edit the contaminations array for a runway entry."""
    contaminations = entry.get("contaminations", [])

    while True:
        print("\nContaminations:")
        if not contaminations:
            console.print("  [grey50]No contaminations[/grey50]")
        else:
            for i, c in enumerate(contaminations):
                coverage = f" ({c.get('coverage')}%)" if c.get("coverage") else ""
                depth = f", {c.get('depth')} {c.get('depthUnits')}" if c.get("depth") else ""
                print(f"  [{i+1}] {c.get('type')}{coverage}{depth}")

        print("\nCommands: [a] Add  [e] Edit  [d] Delete  [Enter] Done")
        cmd = input("Contamination command: ").strip().lower()

        if cmd == "" or cmd == "done":
            break
        elif cmd == "a":
            # Add new contamination
            print(f"\nTypes: {', '.join(CONTAMINATION_TYPES)}")
            ctype = input("Type: ").strip()
            if ctype not in CONTAMINATION_TYPES:
                print(f"Invalid type. Must be one of: {', '.join(CONTAMINATION_TYPES)}")
                continue

            coverage_str = input("Coverage % (or Enter for none): ").strip()
            coverage = int(coverage_str) if coverage_str else None

            depth_str = input("Depth (or Enter for none): ").strip()
            depth = float(depth_str) if depth_str else None

            depth_units = None
            if depth is not None:
                depth_units = input("Depth units (in/mm/cm): ").strip() or None

            contaminations.append({
                "type": ctype,
                "coverage": coverage,
                "depth": depth,
                "depthUnits": depth_units,
            })

        elif cmd == "e":
            if not contaminations:
                print("No contaminations to edit")
                continue
            idx_str = input("Index to edit: ").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(contaminations):
                    c = contaminations[idx]
                    print(f"\nEditing: {c}")
                    print(f"Types: {', '.join(CONTAMINATION_TYPES)}")

                    new_type = input(f"Type [{c.get('type')}]: ").strip()
                    if new_type and new_type in CONTAMINATION_TYPES:
                        c["type"] = new_type

                    new_coverage = input(f"Coverage % [{c.get('coverage')}]: ").strip()
                    if new_coverage:
                        c["coverage"] = int(new_coverage) if new_coverage.lower() != "null" else None

                    new_depth = input(f"Depth [{c.get('depth')}]: ").strip()
                    if new_depth:
                        c["depth"] = float(new_depth) if new_depth.lower() != "null" else None

                    if c.get("depth") is not None:
                        new_units = input(f"Depth units [{c.get('depthUnits')}]: ").strip()
                        if new_units:
                            c["depthUnits"] = new_units if new_units.lower() != "null" else None
                else:
                    print("Invalid index")
            except ValueError:
                print("Invalid index")

        elif cmd == "d":
            if not contaminations:
                print("No contaminations to delete")
                continue
            idx_str = input("Index to delete: ").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(contaminations):
                    removed = contaminations.pop(idx)
                    print(f"Removed: {removed}")
                else:
                    print("Invalid index")
            except ValueError:
                print("Invalid index")

    entry["contaminations"] = contaminations
    return True


def edit_runway_entry(entry: dict) -> bool:
    """Edit a single runway entry."""
    # Group fields by category for display
    categories = [
        ("Runway", ["runway", "runwayClosed"]),
        ("Shortening", ["takeoffShortening", "takeoffShorteningUnits", "landingShortening", "landingShorteningUnits"]),
        ("Declared Distances", ["TORA", "TORAUnits", "TODA", "TODAUnits", "LDA", "LDAUnits"]),
        ("Obstacle", ["obstacleHeight", "obstacleHeightUnits", "obstacleHeightMSL", "obstacleHeightMSLUnits",
                      "obstacleDistance", "obstacleDistanceUnits", "obstacleBearing",
                      "obstacleCoordinates", "obstacleReferencePoint"]),
        ("Climb", ["requiredClimbGradient", "requiredClimbGradientUnits"]),
        ("Metadata", ["confidence", "notes"]),
    ]

    # Build numbered field list
    field_list = []
    print("\nFields:")
    num = 1
    for cat_name, fields in categories:
        print(f"  {cat_name}:")
        for field in fields:
            print(f"    {num}. {field}")
            field_list.append(field)
            num += 1
    print(f"    {num}. contaminations (array)")

    field_num = input("Field number to edit: ").strip()

    try:
        idx = int(field_num) - 1
        if idx == len(field_list):
            # Contaminations
            return edit_contaminations(entry)
        elif 0 <= idx < len(field_list):
            return edit_simple_field(entry, field_list[idx])
        else:
            print("Invalid field number")
            return False
    except ValueError:
        print("Invalid field number")
        return False


def add_runway_entry(item: dict) -> bool:
    """Add a new runway entry to the item."""
    runway_entries = item.get("runway_entries", [])

    runway = input("Runway designator (e.g., 09L): ").strip() or None

    new_entry = {
        "runway": runway,
        "runwayClosed": False,
        "takeoffShortening": None,
        "takeoffShorteningUnits": None,
        "landingShortening": None,
        "landingShorteningUnits": None,
        "TORA": None,
        "TORAUnits": None,
        "TODA": None,
        "TODAUnits": None,
        "LDA": None,
        "LDAUnits": None,
        "obstacleHeight": None,
        "obstacleHeightUnits": None,
        "obstacleHeightMSL": None,
        "obstacleHeightMSLUnits": None,
        "obstacleDistance": None,
        "obstacleDistanceUnits": None,
        "obstacleBearing": None,
        "obstacleCoordinates": None,
        "obstacleReferencePoint": None,
        "contaminations": [],
        "requiredClimbGradient": None,
        "requiredClimbGradientUnits": None,
        "confidence": 1.0,
        "notes": None,
    }

    runway_entries.append(new_entry)
    item["runway_entries"] = runway_entries

    print(f"Added runway entry for {runway or 'null'}")
    return True


def delete_runway_entry(item: dict) -> bool:
    """Delete a runway entry from the item."""
    runway_entries = item.get("runway_entries", [])

    if not runway_entries:
        print("No runway entries to delete")
        return False

    idx_str = input("Entry index to delete: ").strip()
    try:
        idx = int(idx_str) - 1
        if 0 <= idx < len(runway_entries):
            removed = runway_entries.pop(idx)
            print(f"Removed entry for runway: {removed.get('runway')}")
            item["runway_entries"] = runway_entries
            return True
        else:
            print("Invalid index")
            return False
    except ValueError:
        print("Invalid index")
        return False


def update_min_confidence(item: dict):
    """Recalculate min_confidence from runway entries."""
    runway_entries = item.get("runway_entries", [])
    if runway_entries:
        item["min_confidence"] = min(
            (entry.get("confidence", 1.0) for entry in runway_entries),
            default=1.0
        )
    else:
        item["min_confidence"] = 1.0


def review_item(item: dict, index: int, total: int) -> tuple[str, bool]:
    """
    Review a single item interactively.

    Returns:
        Tuple of (action, modified):
        - action: 'next', 'prev', 'quit', 'save', or ('goto', index)
        - modified: True if item was edited during this review
    """
    display_item(item, index, total)
    item_modified = False

    def print_commands():
        print("\nCommands: [Enter] Next  [p] Prev  [g] Go to #  [e] Edit entry  [a] Add entry  [d] Delete entry  [s] Save+quit  [q] Quit")

    print_commands()

    while True:
        cmd = input("Command: ").strip().lower()

        if cmd == "" or cmd == "n":
            return ("next", item_modified)
        elif cmd == "p":
            return ("prev", item_modified)
        elif cmd == "g":
            num_str = input(f"Go to NOTAM # (1-{total}): ").strip()
            try:
                num = int(num_str)
                if 1 <= num <= total:
                    return (("goto", num - 1), item_modified)
                else:
                    print(f"Invalid number. Must be 1-{total}")
                    print_commands()
            except ValueError:
                print("Invalid number")
                print_commands()
            continue
        elif cmd == "e":
            runway_entries = item.get("runway_entries", [])
            if not runway_entries:
                print("No runway entries to edit. Use 'a' to add one.")
                print_commands()
                continue

            if len(runway_entries) == 1:
                edit_runway_entry(runway_entries[0])
            else:
                idx_str = input(f"Entry index to edit (1-{len(runway_entries)}): ").strip()
                try:
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(runway_entries):
                        edit_runway_entry(runway_entries[idx])
                    else:
                        print("Invalid index")
                        print_commands()
                        continue
                except ValueError:
                    print("Invalid index")
                    print_commands()
                    continue

            item_modified = True
            update_min_confidence(item)
            display_item(item, index, total)
            print_commands()
        elif cmd == "a":
            add_runway_entry(item)
            item_modified = True
            update_min_confidence(item)
            display_item(item, index, total)
            print_commands()
        elif cmd == "d":
            if delete_runway_entry(item):
                item_modified = True
            update_min_confidence(item)
            display_item(item, index, total)
            print_commands()
        elif cmd == "s":
            return ("save", item_modified)
        elif cmd == "q":
            return ("quit", item_modified)
        else:
            print("Unknown command")
            print_commands()


def main():
    parser = argparse.ArgumentParser(description="Review and edit silver labels")
    parser.add_argument(
        "--low-confidence",
        action="store_true",
        help="Review only low-confidence items",
    )
    parser.add_argument(
        "--random",
        type=int,
        metavar="N",
        help="Review N random items",
    )
    args = parser.parse_args()

    # Determine which file to load
    if args.low_confidence:
        if not LOW_CONFIDENCE_FILE.exists():
            print(f"Error: {LOW_CONFIDENCE_FILE} not found")
            sys.exit(1)
        items = load_jsonl(LOW_CONFIDENCE_FILE)
        output_file = LOW_CONFIDENCE_FILE
        print(f"Loaded {len(items)} low-confidence items")
    else:
        if not SILVER_FILE.exists():
            print(f"Error: {SILVER_FILE} not found")
            sys.exit(1)
        items = load_jsonl(SILVER_FILE)
        output_file = SILVER_FILE
        print(f"Loaded {len(items)} items")

    if not items:
        print("No items to review")
        return

    # Random sampling
    if args.random:
        if args.random < len(items):
            items = random.sample(items, args.random)
            print(f"Selected {len(items)} random items for review")

    # Sort by min_confidence (lowest first)
    items.sort(key=lambda x: x.get("min_confidence", 1.0))
    print("Sorted by confidence (lowest first)")

    # Review loop
    index = 0
    has_changes = False

    while 0 <= index < len(items):
        action, item_modified = review_item(items[index], index, len(items))
        if item_modified:
            has_changes = True

        if action == "next":
            index += 1
        elif action == "prev":
            index = max(0, index - 1)
        elif isinstance(action, tuple) and action[0] == "goto":
            index = action[1]
        elif action == "save":
            has_changes = True  # Force save
            break
        elif action == "quit":
            if has_changes:
                save_choice = input("\nYou have unsaved changes. Save? (y/n): ").strip().lower()
                if save_choice != "y":
                    has_changes = False  # Don't save
            break

    # Auto-save when reaching the end or explicit save
    if index >= len(items):
        print(f"\n--- Reached end of {len(items)} items ---")
        if has_changes:
            print(f"Saving changes to {output_file}...")
            save_jsonl(items, output_file)
            print("Saved!")
        else:
            save_choice = input("Save reviewed items? (y/n): ").strip().lower()
            if save_choice == "y":
                save_jsonl(items, output_file)
                print("Saved!")
            else:
                print("No changes saved.")
    elif has_changes:
        print(f"\nSaving changes to {output_file}...")
        save_jsonl(items, output_file)
        print("Saved!")
    else:
        print("\nNo changes saved.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Fix systemic labeling issues in the silver dataset.

Issues fixed:
1. "ALL" runway designator → null
2. Coordinates → degrees decimal format
3. Cardinal bearings → degrees
"""

import json
import re
from pathlib import Path

SILVER_FILE = Path(__file__).parent / "data" / "silver_dataset.jsonl"
BACKUP_FILE = Path(__file__).parent / "data" / "silver_dataset.jsonl.bak"


def parse_single_coordinate(coord_str: str) -> str | None:
    """
    Parse a single coordinate pair to degrees decimal format.

    Handles formats:
        "6449N14751W" (DDMM)
        "010641N1040624E" (DDMMSS)
        "101529.6N1235820.2E" (DDMMSS.s)
        "243433.9N 814228.8W" (with space)
        "243433.9N0814228.8W" (with leading zero)
    """
    if not coord_str:
        return None

    coord_str = coord_str.strip()

    # Already in decimal format
    if re.match(r"-?\d+\.\d+,\s*-?\d+\.\d+", coord_str):
        return coord_str

    # Remove spaces and normalize
    clean = coord_str.replace(" ", "").replace("/", "").upper()

    # Pattern for DDMMSS.s format (e.g., "243433.9N0814228.8W" or "010641N1040624E")
    match = re.match(
        r"(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([NS])\s*(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)([EW])",
        clean
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_sec = float(match.group(3))
        lat_dir = match.group(4)
        lon_deg = int(match.group(5))
        lon_min = int(match.group(6))
        lon_sec = float(match.group(7))
        lon_dir = match.group(8)

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    # Pattern for DDMM format (e.g., "6449N14751W", "5022N00330E")
    match = re.match(
        r"(\d{2})(\d{2})([NS])\s*(\d{2,3})(\d{2})([EW])",
        clean
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_dir = match.group(3)
        lon_deg = int(match.group(4))
        lon_min = int(match.group(5))
        lon_dir = match.group(6)

        lat = lat_deg + lat_min / 60
        lon = lon_deg + lon_min / 60

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.4f}, {lon:.4f}"

    # Pattern for degrees/minutes with symbols (e.g., "64°49'N 147°51'W")
    match = re.match(
        r"(\d+)[°](\d+)['\s]*([NS])\s*(\d+)[°](\d+)['\s]*([EW])",
        coord_str.upper()
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_dir = match.group(3)
        lon_deg = int(match.group(4))
        lon_min = int(match.group(5))
        lon_dir = match.group(6)

        lat = lat_deg + lat_min / 60
        lon = lon_deg + lon_min / 60

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.4f}, {lon:.4f}"

    # Pattern for "N24 34 33.9/W81 42 28.8" format (direction prefix with spaces)
    match = re.match(
        r"([NS])(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s*/\s*([EW])(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)",
        coord_str.upper()
    )
    if match:
        lat_dir = match.group(1)
        lat_deg = int(match.group(2))
        lat_min = int(match.group(3))
        lat_sec = float(match.group(4))
        lon_dir = match.group(5)
        lon_deg = int(match.group(6))
        lon_min = int(match.group(7))
        lon_sec = float(match.group(8))

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    # Pattern for DMS with symbols: "37°5'7.3"N, 127°2'26.1"E" or "35°44'50.6"N 139°20'37.6"E"
    match = re.match(
        r"(\d+)°(\d+)'(\d+(?:\.\d+)?)[\"″]?\s*([NS])[,\s]+(\d+)°(\d+)'(\d+(?:\.\d+)?)[\"″]?\s*([EW])",
        coord_str
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_sec = float(match.group(3))
        lat_dir = match.group(4)
        lon_deg = int(match.group(5))
        lon_min = int(match.group(6))
        lon_sec = float(match.group(7))
        lon_dir = match.group(8)

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    # Pattern for "N521603.9 E1042055.1" (direction prefix, compact DDMMSS.s)
    match = re.match(
        r"([NS])(\d{2})(\d{2})(\d{2}(?:\.\d+)?)\s+([EW])(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)",
        coord_str.upper()
    )
    if match:
        lat_dir = match.group(1)
        lat_deg = int(match.group(2))
        lat_min = int(match.group(3))
        lat_sec = float(match.group(4))
        lon_dir = match.group(5)
        lon_deg = int(match.group(6))
        lon_min = int(match.group(7))
        lon_sec = float(match.group(8))

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    # Pattern for DDMMSS.sN DDDMMSS.sW with comma decimal (e.g., "363818.4N 0062043,6W")
    # Normalize comma to period first
    normalized = clean.replace(",", ".")
    match = re.match(
        r"(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([NS])\s*(\d{2,3})(\d{2})(\d{2}(?:\.\d+)?)([EW])",
        normalized
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_sec = float(match.group(3))
        lat_dir = match.group(4)
        lon_deg = int(match.group(5))
        lon_min = int(match.group(6))
        lon_sec = float(match.group(7))
        lon_dir = match.group(8)

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    # Pattern for 7-digit lat / 8-digit lon: "4500511S1684416E" (DDMMSS.sSDDDMMSS.sE)
    match = re.match(
        r"(\d{2})(\d{2})(\d{3})([NS])(\d{3})(\d{2})(\d{2,3})([EW])",
        clean
    )
    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_sec = int(match.group(3)) / 10  # 3 digits = SS.s
        lat_dir = match.group(4)
        lon_deg = int(match.group(5))
        lon_min = int(match.group(6))
        lon_sec_raw = match.group(7)
        lon_sec = int(lon_sec_raw) / (10 if len(lon_sec_raw) == 3 else 1)
        lon_dir = match.group(8)

        lat = lat_deg + lat_min / 60 + lat_sec / 3600
        lon = lon_deg + lon_min / 60 + lon_sec / 3600

        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        return f"{lat:.6f}, {lon:.6f}"

    return None  # Unrecognized


def parse_coordinate(coord_str: str) -> str | None:
    """
    Parse coordinate string to degrees decimal format.
    For multiple coordinates (areas), returns the first one.
    """
    if not coord_str:
        return None

    # Already in decimal format
    if re.match(r"-?\d+\.\d+,\s*-?\d+\.\d+", coord_str):
        return coord_str

    # If it contains multiple coordinates (separated by comma, dash, or space followed by another coord)
    # Just parse the first one
    separators = [" - ", ", ", ","]
    for sep in separators:
        if sep in coord_str:
            parts = coord_str.split(sep)
            first_coord = parse_single_coordinate(parts[0].strip())
            if first_coord:
                return first_coord

    # Try parsing as single coordinate
    result = parse_single_coordinate(coord_str)
    if result:
        return result

    return coord_str  # Return as-is if unrecognized


def parse_bearing(bearing) -> float | None:
    """
    Convert cardinal bearing to degrees.

    Examples:
        "N" → 0
        "NE" → 45
        "E" → 90
        "S" → 180
        "SW" → 225
        180 → 180
    """
    if bearing is None:
        return None

    if isinstance(bearing, (int, float)):
        return float(bearing)

    bearing_str = str(bearing).strip().upper()

    # Check if it's already a number
    try:
        return float(bearing_str)
    except ValueError:
        pass

    # Cardinal directions
    cardinal_map = {
        "N": 0,
        "NNE": 22.5,
        "NE": 45,
        "ENE": 67.5,
        "E": 90,
        "ESE": 112.5,
        "SE": 135,
        "SSE": 157.5,
        "S": 180,
        "SSW": 202.5,
        "SW": 225,
        "WSW": 247.5,
        "W": 270,
        "WNW": 292.5,
        "NW": 315,
        "NNW": 337.5,
    }

    if bearing_str in cardinal_map:
        return cardinal_map[bearing_str]

    return None  # Unrecognized


def fix_runway_entry(entry: dict) -> dict:
    """Fix issues in a single runway entry."""
    # Fix "ALL" runway → null
    if entry.get("runway") == "ALL":
        entry["runway"] = None

    # Fix coordinates
    if entry.get("obstacleCoordinates"):
        parsed = parse_coordinate(entry["obstacleCoordinates"])
        if parsed:
            entry["obstacleCoordinates"] = parsed

    # Fix bearing
    if entry.get("obstacleBearing"):
        parsed = parse_bearing(entry["obstacleBearing"])
        entry["obstacleBearing"] = parsed

    return entry


def fix_item(item: dict) -> dict:
    """Fix issues in a single NOTAM item."""
    runway_entries = item.get("runway_entries", [])
    item["runway_entries"] = [fix_runway_entry(e) for e in runway_entries]
    return item


def main():
    """Main entry point."""
    print("=" * 60)
    print("Silver Label Fixer")
    print("=" * 60)

    if not SILVER_FILE.exists():
        print(f"Error: {SILVER_FILE} not found")
        return

    # Load items
    print(f"Loading {SILVER_FILE}...")
    items = []
    with open(SILVER_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    print(f"Loaded {len(items)} items")

    # Count issues before fixing
    all_runways = 0
    coords_to_fix = 0
    bearings_to_fix = 0

    for item in items:
        for entry in item.get("runway_entries", []):
            if entry.get("runway") == "ALL":
                all_runways += 1
            if entry.get("obstacleCoordinates"):
                coord = entry["obstacleCoordinates"]
                if not re.match(r"-?\d+\.\d+,\s*-?\d+\.\d+", coord):
                    coords_to_fix += 1
            if entry.get("obstacleBearing"):
                bearing = entry["obstacleBearing"]
                if isinstance(bearing, str) and not bearing.replace(".", "").replace("-", "").isdigit():
                    bearings_to_fix += 1

    print(f"\nIssues found:")
    print(f"  'ALL' runways: {all_runways}")
    print(f"  Coordinates to convert: {coords_to_fix}")
    print(f"  Bearings to convert: {bearings_to_fix}")

    if all_runways == 0 and coords_to_fix == 0 and bearings_to_fix == 0:
        print("\nNo issues to fix!")
        return

    # Create backup
    print(f"\nCreating backup at {BACKUP_FILE}...")
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Fix items
    print("Fixing issues...")
    fixed_items = [fix_item(item) for item in items]

    # Save fixed items
    print(f"Saving to {SILVER_FILE}...")
    with open(SILVER_FILE, "w", encoding="utf-8") as f:
        for item in fixed_items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Verify fixes
    all_runways_after = 0
    coords_fixed = 0
    bearings_fixed = 0

    for item in fixed_items:
        for entry in item.get("runway_entries", []):
            if entry.get("runway") == "ALL":
                all_runways_after += 1
            if entry.get("obstacleCoordinates"):
                coord = entry["obstacleCoordinates"]
                if re.match(r"-?\d+\.\d+,\s*-?\d+\.\d+", coord):
                    coords_fixed += 1
            if entry.get("obstacleBearing") is not None:
                bearing = entry["obstacleBearing"]
                if isinstance(bearing, (int, float)):
                    bearings_fixed += 1

    print(f"\nAfter fixing:")
    print(f"  'ALL' runways remaining: {all_runways_after}")
    print(f"  Coordinates in decimal format: {coords_fixed}")
    print(f"  Bearings as numbers: {bearings_fixed}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()

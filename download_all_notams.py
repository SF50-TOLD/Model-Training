#!/usr/bin/env python3
"""
Download all NOTAMs from the API database using pagination.

This script fetches the complete NOTAM database and saves it to a JSON file
for further processing.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()

API_BASE_URL = os.getenv("NOTAM_API_BASE_URL", "https://notams.fly.dev")
API_TOKEN = os.getenv("NOTAM_API_TOKEN")

if not API_TOKEN:
    print("Error: NOTAM_API_TOKEN not set in .env file")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "application/json",
}

OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "all_notams.json"


def fetch_notams(limit: int = 100, offset: int = 0) -> dict:
    """Fetch a page of NOTAMs from the API."""
    url = f"{API_BASE_URL}/api/notams"
    params = {"limit": limit, "offset": offset}

    response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def download_all_notams() -> list[dict]:
    """Download all NOTAMs from the database using pagination."""
    all_notams = []
    offset = 0
    limit = 100

    # First request to get total count
    print("Fetching initial page to determine total count...")
    result = fetch_notams(limit=limit, offset=0)
    total = result.get("pagination", {}).get("total", 0)

    if total == 0:
        print("No NOTAMs found in database")
        return []

    print(f"Total NOTAMs in database: {total}")
    all_notams.extend(result.get("data", []))
    offset = limit

    # Create progress bar for remaining pages
    with tqdm(total=total, initial=len(all_notams), desc="Downloading NOTAMs") as pbar:
        while offset < total:
            try:
                result = fetch_notams(limit=limit, offset=offset)
                data = result.get("data", [])

                if not data:
                    break

                all_notams.extend(data)
                pbar.update(len(data))
                offset += limit

            except requests.RequestException as e:
                print(f"\nError fetching page at offset {offset}: {e}")
                print("Continuing with partial data...")
                break

    return all_notams


def main():
    """Main entry point."""
    print("=" * 60)
    print("NOTAM Database Downloader")
    print("=" * 60)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Output file: {OUTPUT_FILE}")
    print()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Download all NOTAMs
    notams = download_all_notams()

    if not notams:
        print("No NOTAMs downloaded")
        return

    # Save to file
    print(f"\nSaving {len(notams)} NOTAMs to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(notams, f, indent=2, ensure_ascii=False)

    # Print summary statistics
    print("\n" + "=" * 60)
    print("Download Complete!")
    print("=" * 60)
    print(f"Total NOTAMs: {len(notams)}")

    # Count by ICAO location
    locations = {}
    for notam in notams:
        loc = notam.get("icao_location", "UNKNOWN")
        locations[loc] = locations.get(loc, 0) + 1

    print(f"Unique airports: {len(locations)}")
    print(f"\nTop 10 airports by NOTAM count:")
    for loc, count in sorted(locations.items(), key=lambda x: -x[1])[:10]:
        print(f"  {loc}: {count}")


if __name__ == "__main__":
    main()

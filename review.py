#!/usr/bin/env python3
"""Run the gold-label review app at http://127.0.0.1:8765.

Backs up the database first, then serves the review UI locally. Reviews are
attributed to --reviewer, defaulting to `git config user.name`.
"""

import argparse
import shutil
import subprocess
from datetime import datetime

import uvicorn

from notam_gold.paths import DATABASE
from notam_gold.review.app import create_app


def git_user() -> str | None:
    result = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or None


def back_up():
    if DATABASE.exists():
        backups = DATABASE.parent / "backups"
        backups.mkdir(exist_ok=True)
        shutil.copy2(DATABASE, backups / f"{DATABASE.stem}-{datetime.now():%Y%m%dT%H%M%S}.sqlite")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", default=git_user())
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not args.reviewer:
        raise SystemExit("Pass --reviewer (git config user.name is not set).")
    back_up()
    print(f"Reviewing as {args.reviewer} at http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(DATABASE, args.reviewer), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

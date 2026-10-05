#!/usr/bin/env python3
"""Run the gold-label review app at http://127.0.0.1:8765.

Backs up the database first, then serves the review UI locally. --holdout reviews
the held-out set's database instead of the gold set's. Reviews are
attributed to --reviewer, defaulting to `git config user.name`.
"""

import argparse
import subprocess

import uvicorn

from notam_gold.db import back_up
from notam_gold.export import split_of
from notam_gold.paths import DATABASE, HOLDOUT_DATABASE
from notam_gold.review.app import create_app


def git_user() -> str | None:
    result = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", default=git_user())
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--holdout", action="store_true", help="review the held-out set, which has no halves")
    args = parser.parse_args()
    if not args.reviewer:
        raise SystemExit("Pass --reviewer (git config user.name is not set).")
    database = HOLDOUT_DATABASE if args.holdout else DATABASE
    back_up(database)
    print(f"Reviewing {database.name} as {args.reviewer} at http://127.0.0.1:{args.port}")
    app = create_app(database, args.reviewer, half_of=(lambda _key: None) if args.holdout else split_of)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

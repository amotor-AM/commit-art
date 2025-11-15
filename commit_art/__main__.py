"""Paint the current date onto the GitHub contribution graph."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from commit_art.paint import describe, paint, push, run_checks


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(
        description="Light contribution-graph squares so they spell the current date."
    )
    parser.add_argument("--preview", action="store_true", help="Print the date and where it will sit. Do not commit.")
    parser.add_argument("--paint", action="store_true", help="Rebuild this repository's commits into that date.")
    parser.add_argument("--push", action="store_true", help="Force-push the dedicated commit-art repository.")
    parser.add_argument("--date", help="Paint this YYYY-MM-DD instead of today. For a trial run.")
    parser.add_argument("--self-test", action="store_true", help="Check the font and the week math.")
    args = parser.parse_args(argv)

    if args.self_test:
        run_checks()
        return 0

    chosen = date.fromisoformat(args.date) if args.date else None
    if args.preview or not args.paint:
        print(describe(chosen or date.today()))
    if args.paint:
        paint(chosen)
    if args.push:
        if not args.paint:
            print("Pass --paint with --push so the commits being pushed are today's date.", file=sys.stderr)
            return 1
        push()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

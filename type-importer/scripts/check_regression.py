#!/usr/bin/env python3
"""Compare a fresh coverage_report.py --json-out snapshot against the
committed baseline (../coverage_baseline.json) and fail (exit 1) if any
class got WORSE. This is the CI gate: patches 0001-0005 got 4 classes
right by hand; the sweep found only 311/2814 checkable classes are
byte-accurate at scale. This script is how a future patch proves it
didn't silently break one of those 311 (or any other previously-working
class) while fixing something else.

Status ordering, best to worst: OK > NO_GROUND_TRUTH > MISMATCH > EMPTY > UNRESOLVED
(NO_GROUND_TRUTH ranks above MISMATCH/EMPTY: a class we can't check
against a static_assert but that resolved to *some* non-trivial size is
in better shape than one we know is wrong or empty.)

A class regresses if its new status is worse than its baseline status,
OR (belt-and-suspenders for MISMATCH/OK) its `actual` size baseline
was correct and the new size differs.

A class NOT in the baseline is fine (sweep coverage grew, or it's a
first run) -- it's recorded as new, not a regression. A class in the
baseline but absent from the new snapshot entirely is treated as
UNRESOLVED (the worst status) for comparison purposes.

Usage:
    python3 check_regression.py --baseline ../coverage_baseline.json --new snapshot.json
Exit code 0 if no regressions, 1 if any (and prints the list either way).
"""
import argparse
import json
import sys
from pathlib import Path

RANK = {"UNRESOLVED": 0, "EMPTY": 1, "MISMATCH": 2, "NO_GROUND_TRUTH": 3, "OK": 4}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text())
    new = json.loads(args.new.read_text())

    regressions = []
    improvements = []
    newly_seen = []

    for name, base_entry in baseline.items():
        new_entry = new.get(name, {"status": "UNRESOLVED", "expected": base_entry.get("expected"), "actual": None})
        base_rank = RANK[base_entry["status"]]
        new_rank = RANK[new_entry["status"]]
        if base_entry["status"] in ("MISMATCH", "OK") and new_entry["status"] == "NO_GROUND_TRUTH":
            # NO_GROUND_TRUTH normally ranks ABOVE MISMATCH/EMPTY (a class
            # with no assert to check is "less bad" than one we know is
            # wrong) -- but if the BASELINE had a real `expected` value
            # (MISMATCH or OK) and the new run has none, that means the
            # static_assert miner failed to re-find an assert it found
            # before, not that the archive itself improved. Treat that
            # specific transition as a regression in the miner, not an
            # improvement in coverage. Found while
            # that traced a real mislabeled class (SkyObject) back to
            # this exact blind spot.
            regressions.append((name, base_entry, new_entry))
        elif new_rank < base_rank:
            regressions.append((name, base_entry, new_entry))
        elif new_rank > base_rank:
            improvements.append((name, base_entry, new_entry))
        elif base_entry["status"] == "OK" and new_entry.get("actual") != base_entry.get("actual"):
            # Same rank (OK) but a different actual size -- shouldn't be
            # reachable given OK's definition, but check explicitly rather
            # than trust it silently.
            regressions.append((name, base_entry, new_entry))

    for name in new:
        if name not in baseline:
            newly_seen.append(name)

    print(f"# Regression check: baseline={len(baseline)} new={len(new)} "
          f"regressions={len(regressions)} improvements={len(improvements)} newly_seen={len(newly_seen)}")

    if regressions:
        print(f"\n## REGRESSIONS ({len(regressions)}) -- these got WORSE, investigate before merging")
        for name, base_entry, new_entry in sorted(regressions):
            print(f"{name}: {base_entry['status']} (actual={base_entry.get('actual')}) "
                  f"-> {new_entry['status']} (actual={new_entry.get('actual')})")

    if improvements:
        print(f"\n## Improvements ({len(improvements)}) -- consider updating the baseline to lock these in")
        for name, base_entry, new_entry in sorted(improvements)[:50]:
            print(f"{name}: {base_entry['status']} -> {new_entry['status']}")
        if len(improvements) > 50:
            print(f"... and {len(improvements) - 50} more")

    sys.exit(1 if regressions else 0)


if __name__ == "__main__":
    main()

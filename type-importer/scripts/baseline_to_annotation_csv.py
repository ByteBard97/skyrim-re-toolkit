#!/usr/bin/env python3
"""Convert a coverage_baseline*.json file into a simple `name,STATUS` CSV
that GenerateGdt.java's --annotate-coverage can consume without needing a
JSON parser on the Java side (mirrors the existing tail_padding_hints.csv
convention already used by --tail-padding-hints).

Usage: baseline_to_annotation_csv.py <coverage_baseline.json> <out.csv>
"""
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    baseline_path, out_path = sys.argv[1], sys.argv[2]
    data = json.load(open(baseline_path))
    # Plain "name,STATUS" lines, no CSV quoting -- matches the same simple
    # split(",", 2) convention GenerateGdt.java already uses for
    # tail_padding_hints.csv. Confirmed no baseline key contains a comma.
    with open(out_path, "w") as f:
        for name, entry in data.items():
            status = entry.get("status", "")
            if not status or "," in name:
                continue
            f.write(f"{name},{status}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

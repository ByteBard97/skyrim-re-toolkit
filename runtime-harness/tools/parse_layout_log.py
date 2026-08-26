#!/usr/bin/env python3
"""Parse `LayoutValidator: LAYOUT/ADDR/LIVE` lines out of a RuntimeHarness.log
and, optionally, diff the LAYOUT sizes against type-importer's
coverage_baseline.json for a mechanical three-way comparison:

    parser (baseline `actual`, from libclang/type-importer)
    vs. header static_assert (baseline `expected`)
    vs. compiled plugin (this log's LAYOUT `sizeof`, real MSVC output)

This is Linux-side and needs no Windows access or live game -- it only
reads text. See runtime-harness/docs/LAYOUT_VALIDATOR.md for what the
log lines mean and their honest limitations (most of these 11 classes
are SE-view sizes in the compiled plugin, not AE ground truth; see that
doc before treating a "diff" against the AE-targeted baseline as a bug).

Usage:
    python3 parse_layout_log.py RuntimeHarness.log
        -> prints parsed LAYOUT/ADDR/LIVE entries as JSON to stdout

    python3 parse_layout_log.py RuntimeHarness.log --diff-baseline ../../type-importer/coverage_baseline.json
        -> also prints a three-way diff table and exits 1 if any LAYOUT
           class's compiled sizeof disagrees with the baseline's
           `expected` (static_assert) value, when one exists
"""
import argparse
import json
import re
import sys
from pathlib import Path

LAYOUT_RE = re.compile(
    r"LayoutValidator: LAYOUT class=(?P<class>\S+) sizeof=0x(?P<sizeof>[0-9A-Fa-f]+)(?P<rest>.*)$"
)
OFFSET_RE = re.compile(r"off\.(?P<field>\S+)=0x(?P<value>[0-9A-Fa-f]+)")
NOTE_RE = re.compile(r"note=(?P<note>\S+)")

ADDR_BASE_RE = re.compile(r"LayoutValidator: ADDR module\.base=0x(?P<base>[0-9A-Fa-f]+)")
ADDR_VTABLE_RE = re.compile(
    r"LayoutValidator: ADDR vtable=(?P<name>[^\s\[]+)\[(?P<idx>\d+)\](?: id=(?P<id>\S+))? "
    r"resolved=0x(?P<resolved>[0-9A-Fa-f]+) rva=0x(?P<rva>[0-9A-Fa-f]+)"
)
ADDR_RTTI_RE = re.compile(
    r"LayoutValidator: ADDR rtti=(?P<name>\S+) id=(?P<id>\S+) "
    r"resolved=0x(?P<resolved>[0-9A-Fa-f]+) rva=0x(?P<rva>[0-9A-Fa-f]+)"
)

LIVE_SKIPPED_RE = re.compile(r"LayoutValidator: LIVE (?P<what>.+) instance=nullptr \(skipped\)")
LIVE_CHECK_RE = re.compile(
    r"LayoutValidator: LIVE (?P<what>.+?) formID=(?P<formid>[0-9A-Fa-f]+)\(raw=(?P<rawformid>[0-9A-Fa-f]+),(?P<formid_status>OK|MISMATCH)\) "
    r"formType=0x(?P<formtype>[0-9A-Fa-f]+)\(raw=0x(?P<rawformtype>[0-9A-Fa-f]+),(?P<formtype_status>OK|MISMATCH)\)"
)
LIVE_RTTI_RE = re.compile(
    r"LayoutValidator: LIVE rtti=(?P<name>\S+) mangled_name=(?P<mangled>\S+)\((?P<status>OK|MISMATCH)\)"
)
# vtbl check is informational only (see LayoutValidator.cpp's comment on why
# it's not compared against a specific expected VTABLE_* address) -- parsed
# for completeness, no OK/MISMATCH verdict to extract.
LIVE_VTBL_RE = re.compile(
    r"LayoutValidator: LIVE (?P<what>.+?) vtbl=0x(?P<vtbl>[0-9A-Fa-f]+) rva=0x(?P<rva>[0-9A-Fa-f]+)"
)


def parse_log(text):
    layout = {}
    addr = {"module_base": None, "vtables": [], "rtti": []}
    live = []
    live_rtti = []
    live_vtbl = []

    for line in text.splitlines():
        m = LAYOUT_RE.search(line)
        if m:
            offsets = {om.group("field"): int(om.group("value"), 16) for om in OFFSET_RE.finditer(m.group("rest"))}
            note_m = NOTE_RE.search(m.group("rest"))
            layout[m.group("class")] = {
                "sizeof": int(m.group("sizeof"), 16),
                "offsets": offsets,
                "note": note_m.group("note") if note_m else None,
            }
            continue

        m = ADDR_BASE_RE.search(line)
        if m:
            addr["module_base"] = int(m.group("base"), 16)
            continue

        m = ADDR_VTABLE_RE.search(line)
        if m:
            addr["vtables"].append({
                "name": m.group("name"),
                "index": int(m.group("idx")),
                "id": m.group("id"),
                "resolved": int(m.group("resolved"), 16),
                "rva": int(m.group("rva"), 16),
            })
            continue

        m = ADDR_RTTI_RE.search(line)
        if m:
            addr["rtti"].append({
                "name": m.group("name"),
                "id": m.group("id"),
                "resolved": int(m.group("resolved"), 16),
                "rva": int(m.group("rva"), 16),
            })
            continue

        m = LIVE_SKIPPED_RE.search(line)
        if m:
            live.append({"what": m.group("what"), "skipped": True})
            continue

        m = LIVE_CHECK_RE.search(line)
        if m:
            live.append({
                "what": m.group("what"),
                "skipped": False,
                "formID": int(m.group("formid"), 16),
                "rawFormID": int(m.group("rawformid"), 16),
                "formID_status": m.group("formid_status"),
                "formType": int(m.group("formtype"), 16),
                "rawFormType": int(m.group("rawformtype"), 16),
                "formType_status": m.group("formtype_status"),
            })
            continue

        m = LIVE_RTTI_RE.search(line)
        if m:
            live_rtti.append({
                "name": m.group("name"),
                "mangled_name": m.group("mangled"),
                "status": m.group("status"),
            })
            continue

        m = LIVE_VTBL_RE.search(line)
        if m:
            live_vtbl.append({
                "what": m.group("what"),
                "vtbl": int(m.group("vtbl"), 16),
                "rva": int(m.group("rva"), 16),
            })
            continue

    return {"layout": layout, "addr": addr, "live": live, "live_rtti": live_rtti, "live_vtbl": live_vtbl}


def diff_against_baseline(layout, baseline):
    """Three-way comparison per LAYOUT class: parser `actual`, header
    `expected` (static_assert), and this log's compiled `sizeof`.
    Returns (rows, mismatch_count) where a mismatch is only counted when
    the baseline has a static_assert-backed `expected` value AND it
    disagrees with the compiled sizeof -- NO_GROUND_TRUTH baseline
    entries (no static_assert to check against) never count as a
    mismatch, they're just reported for visibility.
    """
    rows = []
    mismatches = 0
    for name, entry in sorted(layout.items()):
        base = baseline.get(name)
        compiled = entry["sizeof"]
        if base is None:
            rows.append((name, "?", "?", compiled, "NOT-IN-BASELINE"))
            continue

        parser_actual = base.get("actual")
        expected = base.get("expected")
        status = base.get("status")

        if expected is not None and expected != compiled:
            verdict = "MISMATCH"
            mismatches += 1
        elif expected is not None:
            verdict = "OK"
        else:
            verdict = f"NO-STATIC-ASSERT(baseline={status})"

        rows.append((name, parser_actual, expected, compiled, verdict))

    return rows, mismatches


def print_diff_table(rows):
    header = ("class", "parser actual", "header expected", "compiled sizeof", "verdict")
    widths = [max(len(str(r[i])) for r in ([header] + rows)) for i in range(5)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*header))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path, help="RuntimeHarness.log (or an excerpt containing LayoutValidator lines)")
    parser.add_argument("--diff-baseline", type=Path, default=None,
                         help="path to type-importer/coverage_baseline.json; if given, prints a three-way diff and exits 1 on any confirmed mismatch")
    parser.add_argument("--json-out", type=Path, default=None, help="also write the parsed structure as JSON to this path")
    args = parser.parse_args()

    text = args.log.read_text()
    parsed = parse_log(text)

    if args.json_out:
        args.json_out.write_text(json.dumps(parsed, indent=2))
    else:
        print(json.dumps(parsed, indent=2))

    if args.diff_baseline:
        baseline = json.loads(args.diff_baseline.read_text())
        rows, mismatches = diff_against_baseline(parsed["layout"], baseline)
        sys.stderr.write("\n--- three-way diff vs coverage_baseline.json ---\n")
        sys.stderr.flush()
        print_diff_table(rows)
        sys.stdout.flush()
        if mismatches:
            sys.stderr.write(f"\n{mismatches} confirmed mismatch(es) against a static_assert-backed baseline value.\n")
            return 1
        sys.stderr.write("\nNo confirmed mismatches against static_assert-backed baseline values.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

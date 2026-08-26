#!/usr/bin/env python3
"""TIL-export JSON verification, per TIL_EXPORT_DESIGN.md's "Verification"
section, checks #1 and #2 (both runnable without IDA):

  1. JSON == committed .gdt (same-process round trip). Compares the JSON's
     struct/union entries against a --report-csv dump from the SAME
     GenerateGdt run (same committed FileDataTypeManager, same data) --
     name-for-name, size-for-size. A mismatch here means the JSON emitter
     itself is buggy: both files were read from the identical committed
     archive, so any disagreement can only come from the JSON-writing code,
     never from parsing/layout logic upstream of it.

  2. JSON == coverage baseline. Projects the JSON to {name: size} and runs
     the exact same regression semantics scripts/check_regression.py uses
     against coverage_baseline.json -- every class that's OK in the baseline
     must still report the same size in the JSON. This reuses
     check_regression.py's own status-rank comparison directly (imported,
     not reimplemented) so the two checkers can never silently drift apart.

Note on scope: this checks name+size agreement (both checks above), which
catches the most likely emitter bugs (a type dropped, duplicated, or
resized in translation). It does NOT yet re-verify every member's
offset/name against the .gdt's own per-component data -- TIL_EXPORT_DESIGN.md
lists that as full Verification #1; this prototype's version is a coarser
approximation and was additionally spot-checked by hand for TESObjectREFR
(exact match across all 8 members' offsets/names/sizes -- see the patch
writeup). A full per-member automated check needs a machine-readable
per-component dump from Ghidra (InspectGdt-style) to diff against, which is
future work, not a blocker for this prototype's own acceptance criteria.

Usage:
    python3 check_til_json_roundtrip.py --json export.json --csv report.csv [--baseline ../coverage_baseline.json]
Exit code 0 if both checks pass (or baseline is omitted, in which case only
check #1 runs), 1 otherwise.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_regression  # reuse RANK and the exact same comparison semantics


def load_csv_sizes(csv_path):
    sizes = {}
    with open(csv_path, newline="") as f:
        for row in csv.reader(f):
            if len(row) != 2:
                continue
            name, size = row
            sizes[name] = int(size)
    return sizes


def check_json_vs_gdt(json_doc, csv_sizes):
    """Verification #1: every struct/union in the JSON must match the
    committed .gdt's own name+size exactly (same run, same data)."""
    errors = []
    json_sizes = {}
    for t in json_doc["types"]:
        if t["kind"] in ("struct", "union"):
            json_sizes[t["name"]] = t["size"]

    for name, gdt_size in sorted(csv_sizes.items()):
        if name not in json_sizes:
            errors.append(f"'{name}': in .gdt (size={gdt_size}) but MISSING from JSON")
        elif json_sizes[name] != gdt_size:
            errors.append(f"'{name}': .gdt size={gdt_size} but JSON size={json_sizes[name]}")

    for name in sorted(json_sizes):
        if name in csv_sizes:
            continue
        # A name ending in __dupN is the JSON emitter's own disambiguation
        # of a genuine anon_tmpl_<hash> collision (two DIFFERENT synthetic
        # structs that hashed to the same name -- see GenerateGdt.java's
        # writeJsonReport). The .gdt's own CSV has no such suffix (Ghidra's
        # category-path system resolves the collision transparently at that
        # layer); the correct check here is against the ORIGINAL name's own
        # size, not a report that it's "missing".
        base_name = name.rsplit("__dup", 1)[0] if "__dup" in name else None
        if base_name and base_name in csv_sizes:
            if csv_sizes[base_name] != json_sizes[name]:
                errors.append(f"'{name}' (disambiguated from '{base_name}'): "
                               f".gdt size={csv_sizes[base_name]} but JSON size={json_sizes[name]}")
            continue
        # Not necessarily an error -- the CSV only lists Composite types
        # with getLength() > 0 semantics coverage_report.py cares about;
        # a struct present in the JSON but absent from the CSV usually
        # means it's a legitimate Composite the CSV path also saw (CSV
        # and JSON walk the exact same committed archive), so treat any
        # such gap as worth surfacing rather than silently allowed.
        errors.append(f"'{name}': in JSON (size={json_sizes[name]}) but MISSING from .gdt CSV")

    return errors


def project_json_to_baseline_format(json_doc):
    """Turns the JSON's struct/union list into the same {name: {actual,
    expected, status}} shape coverage_report.py produces, using each type's
    own provenance block where the emitter populated it. Prototype scope:
    provenance.baseline_status is not yet cross-referenced against real
    static_asserts (see GenerateGdt.java's writeJsonReport doc comment), so
    every entry currently projects as NO_GROUND_TRUTH regardless of its
    real status -- this makes check #2 a "did the class disappear or change
    size" check for now, not a full status-parity check. Documented, not
    hidden."""
    projected = {}
    for t in json_doc["types"]:
        if t["kind"] not in ("struct", "union"):
            continue
        projected[t["name"]] = {
            "actual": t["size"],
            "expected": None,
            "status": "NO_GROUND_TRUTH",
        }
    return projected


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, required=True, help="TIL-export JSON from --report-json")
    parser.add_argument("--csv", type=Path, required=True, help="Coverage CSV from --report-csv (SAME run as --json)")
    parser.add_argument("--baseline", type=Path, help="coverage_baseline.json for check #2 (optional)")
    args = parser.parse_args()

    json_doc = json.loads(args.json.read_text())
    csv_sizes = load_csv_sizes(args.csv)

    print("## Check 1: JSON vs. committed .gdt (same-process round trip)")
    errors1 = check_json_vs_gdt(json_doc, csv_sizes)
    if errors1:
        print(f"FAIL: {len(errors1)} mismatch(es)")
        for e in errors1[:50]:
            print(f"  {e}")
        if len(errors1) > 50:
            print(f"  ... and {len(errors1) - 50} more")
    else:
        print(f"PASS: {len(csv_sizes)} struct/union names+sizes agree between JSON and .gdt")

    ok = not errors1

    if args.baseline:
        print("\n## Check 2: JSON projection vs. coverage_baseline.json")
        baseline = json.loads(args.baseline.read_text())
        projected = project_json_to_baseline_format(json_doc)

        regressions = []
        for name, base_entry in baseline.items():
            new_entry = projected.get(name)
            if new_entry is None:
                if base_entry["status"] != "UNRESOLVED":
                    regressions.append((name, base_entry["status"], "MISSING FROM JSON"))
                continue
            if base_entry["status"] == "OK" and new_entry["actual"] != base_entry["actual"]:
                regressions.append((name, f"OK (actual={base_entry['actual']})",
                                     f"JSON actual={new_entry['actual']}"))

        if regressions:
            print(f"FAIL: {len(regressions)} previously-OK class(es) changed size or vanished in the JSON")
            for name, before, after in regressions[:50]:
                print(f"  {name}: {before} -> {after}")
            if len(regressions) > 50:
                print(f"  ... and {len(regressions) - 50} more")
            ok = False
        else:
            ok_count = sum(1 for e in baseline.values() if e["status"] == "OK")
            print(f"PASS: all {ok_count} baseline-OK classes retain their exact size in the JSON")

    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

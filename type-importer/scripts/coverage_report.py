#!/usr/bin/env python3
"""Step 4 of the coverage sweep (see ../COVERAGE_SWEEP_PLAN.md): cross-
reference mine_static_asserts.py's expected-size ground truth against
GenerateGdt.java's --report-csv actual-resolved-size output, and bucket
every class into:

    OK          resolved, size matches the AE-applicable static_assert
    MISMATCH    resolved, size does NOT match the static_assert
    EMPTY       resolved but size <= 1 -- the "TESForm came back as 0x1"
                failure signature hit five times during early patch
                development (patches 0001-0005), not the same as MISMATCH:
                it means the type is a placeholder, not "subtly wrong"
    UNRESOLVED  requested/expected but never appears in the resolved set
    NO_GROUND_TRUTH  resolved, no AE-applicable static_assert to check
                against -- still checked for EMPTY, just can't confirm OK

`anon_tmpl_*` synthetic structs (from patches 0003/0005's template-field
inlining) are reported separately, not folded into the main buckets --
bucket them by whether they consist solely of the `opaque` padding field
(see GenerateGdt's --report-csv: this script can't inspect field contents
from the CSV alone, so it only reports the anon_tmpl_* COUNT and defers
the opaque-vs-real-fields check to manual .gdt inspection, per the plan's
"Verification to run early" note).

Usage:
    python3 coverage_report.py --expected mine_static_asserts_output.json \
        --actual report.csv [--actual-unresolved report.csv.unresolved.txt] \
        [--json-out snapshot.json]

--json-out writes a machine-readable {ClassName: {status, expected, actual}}
snapshot -- this is the artifact scripts/check_regression.py diffs against
a committed baseline in CI (see COVERAGE_SWEEP_PLAN.md's CI section).
"""
import argparse
import csv
import json
import re
from pathlib import Path

EMPTY_THRESHOLD = 1  # size <= this is "resolved but empty"

# libclang spells anonymous types as "(unnamed enum at /abs/path/file.h:L:C)".
# The absolute path makes the name machine-specific, so a baseline recorded on
# one machine reports 55 phantom "regressions" on any other (CI included).
# Normalize to the path suffix after the last "/include/" (both the vendored
# CommonLibSSE-NG headers and the xwin-splatted SDK live under an include/
# directory), falling back to the basename, so keys are checkout-independent.
_UNNAMED_AT_RE = re.compile(r"\(unnamed ([a-z]+) at ([^)]*)\)")


def _stable_unnamed_path(match: re.Match) -> str:
    kind, loc = match.group(1), match.group(2)
    idx = loc.rfind("/include/")
    if idx != -1:
        loc = loc[idx + len("/include/"):]
    elif "/" in loc:
        loc = loc.rsplit("/", 1)[1]
    return f"(unnamed {kind} at {loc})"


def normalize_name(name: str) -> str:
    return _UNNAMED_AT_RE.sub(_stable_unnamed_path, name)


def load_expected(path: Path) -> dict:
    return json.loads(path.read_text())


def load_actual(path: Path) -> dict:
    actual = {}
    with path.open(newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            name, size = normalize_name(row[0]), int(row[1])
            actual.setdefault(name, []).append(size)
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expected", type=Path, required=True, help="JSON {ClassName: expected_size} from mine_static_asserts.py --json")
    parser.add_argument("--actual", type=Path, required=True, help="CSV ClassName,SizeInBytes from GenerateGdt --report-csv")
    parser.add_argument("--actual-unresolved", type=Path, help="<report>.unresolved.txt from GenerateGdt --report-csv")
    parser.add_argument("--scope-note", default=None,
                         help="Free text describing what subset of RE/ this sweep covered (required if not the full namespace) -- printed in the report header, per the plan's 'no silent caps' rule")
    parser.add_argument("--json-out", type=Path, help="Write a machine-readable {ClassName: {status, expected, actual}} snapshot here, for scripts/check_regression.py")
    args = parser.parse_args()

    expected = load_expected(args.expected)
    actual = load_actual(args.actual)
    unresolved_names = set()
    if args.actual_unresolved and args.actual_unresolved.exists():
        unresolved_names = {normalize_name(l.strip()) for l in args.actual_unresolved.read_text().splitlines() if l.strip()}

    anon_tmpl = {name: sizes for name, sizes in actual.items() if name.startswith("anon_tmpl_")}
    real_actual = {name: sizes for name, sizes in actual.items() if not name.startswith("anon_tmpl_")}

    ok, mismatch, empty, unresolved, no_ground_truth = [], [], [], [], []

    all_names = set(expected) | set(real_actual)
    for name in sorted(all_names):
        exp_size = expected.get(name)
        act_sizes = real_actual.get(name)

        if act_sizes is None:
            unresolved.append((name, exp_size))
            continue

        act_size = act_sizes[0]  # DataTypeManager de-dupes by name; one size expected
        if act_size <= EMPTY_THRESHOLD and (exp_size is None or exp_size > EMPTY_THRESHOLD):
            empty.append((name, exp_size, act_size))
        elif exp_size is None:
            no_ground_truth.append((name, act_size))
        elif act_size == exp_size:
            ok.append((name, exp_size))
        else:
            mismatch.append((name, exp_size, act_size))

    print("# Coverage sweep report")
    if args.scope_note:
        print(f"# SCOPE: {args.scope_note}")
    else:
        print("# SCOPE: full sweep (no subset restriction specified)")
    print(f"# OK={len(ok)} MISMATCH={len(mismatch)} EMPTY={len(empty)} "
          f"(of which {len([e for e in empty if e[1] is not None])} confirmed wrong "
          f"vs a known static_assert, {len([e for e in empty if e[1] is None])} unverified) "
          f"UNRESOLVED={len(unresolved)} NO_GROUND_TRUTH={len(no_ground_truth)} "
          f"anon_tmpl_synthetics={len(anon_tmpl)}")
    print()

    # EMPTY (actual<=EMPTY_THRESHOLD) mixes two very different things: a class
    # whose static_assert PROVES the placeholder is wrong (confirmed bug --
    # e.g. a reference-type member the parser drops, real content lost), and
    # a class with no static_assert to check at all. The latter is NOT
    # necessarily a bug: many are genuinely-empty-by-design C++ types (enum-
    # only namespacing structs, RAII guards whose only state is a reference,
    # deleted-everything utility classes) that legitimately compile to
    # sizeof==1. Don't conflate "can't verify" with "verified wrong."
    empty_confirmed = [(n, e, a) for n, e, a in empty if e is not None]
    empty_unverified = [(n, e, a) for n, e, a in empty if e is None]
    print(f"## EMPTY, CONFIRMED WRONG ({len(empty_confirmed)}) -- static_assert proves this size is incorrect; highest priority")
    for name, exp, act in empty_confirmed:
        print(f"{name}: actual=0x{act:x} expected=0x{exp:x}")
    print()
    print(f"## EMPTY, UNVERIFIED ({len(empty_unverified)}) -- no static_assert to check against; "
          f"NOT necessarily wrong (many are legitimately-empty C++ types)")
    for name, exp, act in empty_unverified:
        print(f"{name}: actual=0x{act:x} expected=unknown")
    print()

    print(f"## MISMATCH ({len(mismatch)})")
    for name, exp, act in mismatch:
        print(f"{name}: expected=0x{exp:x} actual=0x{act:x}")
    print()

    print(f"## UNRESOLVED ({len(unresolved)}) -- expected but absent from resolved set")
    for name, exp in unresolved:
        print(f"{name}: expected={'0x%x' % exp if exp is not None else 'unknown'}")
    print()

    print(f"## anon_tmpl_* synthetics ({len(anon_tmpl)}) -- not bucketed above; "
          f"inspect the .gdt directly to check which are opaque-padding-only vs. real fields")
    print()

    print(f"## OK ({len(ok)}) -- no action needed, list suppressed for brevity")
    print(f"## NO_GROUND_TRUTH ({len(no_ground_truth)}) -- resolved, non-empty, no static_assert to confirm against")

    if args.json_out:
        # Anonymous types are keyed by clang's "(anonymous union at
        # /abs/path/file.h:LINE)" spelling, which embeds a machine-specific
        # absolute path -- a baseline recorded on one machine reports every
        # such entry as a spurious UNRESOLVED "regression" on any other
        # machine (this broke the first hosted CI run). They can never have
        # static_assert ground truth (nothing can name them), so they add no
        # regression-gate value: exclude them from the snapshot entirely.
        def track(name):
            return "(anonymous" not in name

        snapshot = {}
        for name, exp in ok:
            if track(name):
                snapshot[name] = {"status": "OK", "expected": exp, "actual": exp}
        for name, exp, act in mismatch:
            if track(name):
                snapshot[name] = {"status": "MISMATCH", "expected": exp, "actual": act}
        for name, exp, act in empty:
            if track(name):
                snapshot[name] = {"status": "EMPTY", "expected": exp, "actual": act}
        for name, exp in unresolved:
            if track(name):
                snapshot[name] = {"status": "UNRESOLVED", "expected": exp, "actual": None}
        for name, act in no_ground_truth:
            if track(name):
                snapshot[name] = {"status": "NO_GROUND_TRUTH", "expected": None, "actual": act}
        args.json_out.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
        print(f"\n# Wrote {len(snapshot)}-entry JSON snapshot to {args.json_out}")


if __name__ == "__main__":
    main()

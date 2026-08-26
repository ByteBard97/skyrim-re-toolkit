#!/usr/bin/env python3
"""Mine `REL::RelocateMember[IfNewer]<T>(this, seOffset, aeOffset, ...)` call
sites from CommonLibSSE-NG source, to recover the true in-memory tail size
of classes whose real fields are accessed via this runtime-offset trick
rather than declared as compiled struct members under a given runtime (see
DESIGN.md's "invisible relocated member" writeup and
COVERAGE_SWEEP_PLAN.md's "BaseExtraList / ExtraDataList" section).

Scope (deliberately narrow -- see type-importer/patches/0019-*.md for the
full writeup): only scans `.cpp` files under CommonLibSSE-NG/src, and only
recognizes pointer-typed `T` (T ending in `*`), which covers every known
target of this feature (BaseExtraList::GetData/GetPresence). Broader
coverage (inline .h accessors, non-pointer T, general sizeof lookup) is
NOT attempted here -- this is a from-scratch, minimally-scoped miner
sibling to mine_static_asserts.py, not a general C++ parser. Findings for
call sites this script can't confidently attribute to a class or size are
reported separately as "skipped", not silently dropped.

For each recognized call, computes ae_offset + sizeof(T) (8, since T is a
pointer) and reports the max across all calls per class -- an inferred
LOWER BOUND on that class's true AE in-memory size, not a proven exact
size (there is no static_assert or binary ground truth to check this
against -- see DESIGN.md).

Usage:
    python3 mine_relocate_member_offsets.py <path-to-CommonLibSSE-NG>/src \
        [--json out.json] [--csv out.csv]

--csv writes a simple `ClassName,MinSize` file for GenerateGdt.java's
--tail-padding-hints to consume directly (no JSON parsing needed on the
Java side, matching this codebase's existing plain-CSV convention).
"""
import argparse
import re
from pathlib import Path

POINTER_SIZE = 8

# ClassName::MethodName(...) -- used to attribute a call site to a class
# when it appears in an out-of-line (.cpp) method definition.
METHOD_DEF_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)::[A-Za-z_~][A-Za-z0-9_]*\s*\(')

# REL::RelocateMember<T>(this, seOffset, aeOffset, ...) or the IfNewer
# variant, whose first data-carrying args are (version, this, seOffset,
# aeOffset). Only the trailing (this, seOffset, aeOffset) shape matters
# here since IfNewer's extra leading `version` arg doesn't change the
# offset extraction below (it's just skipped as part of the args list).
CALL_RE = re.compile(
    r'RelocateMember(?:IfNewer)?\s*<\s*([^>]+?)\s*>\s*\('
    r'([^;]*?this\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*,\s*(0[xX][0-9a-fA-F]+|\d+))\s*[,)]')


def parse_int(s: str) -> int:
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def scan_file(path: Path, findings: dict, skipped: list):
    text = path.read_text(errors="ignore")
    lines = text.splitlines()

    # Track the most recent "ClassName::Method(" seen, scanning top-down --
    # good enough for this codebase's style (one out-of-line definition
    # per top-level function, no nested local classes defining methods).
    current_class = None
    for line in lines:
        m = METHOD_DEF_RE.search(line)
        if m:
            current_class = m.group(1)

        for cm in CALL_RE.finditer(line):
            type_str, _args, se_str, ae_str = cm.groups()
            type_str = type_str.strip()
            if not type_str.endswith("*"):
                skipped.append((str(path), line.strip(), f"non-pointer type '{type_str}', size unknown"))
                continue
            if current_class is None:
                skipped.append((str(path), line.strip(), "no enclosing ClassName::Method(...) found"))
                continue

            ae_offset = parse_int(ae_str)
            min_size = ae_offset + POINTER_SIZE
            entry = findings.setdefault(current_class, {"inferred_min_size": 0, "evidence": []})
            entry["evidence"].append(f"{path.name}: {type_str} @ ae_offset=0x{ae_offset:x}")
            entry["inferred_min_size"] = max(entry["inferred_min_size"], min_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src_dir", type=Path, help="Path to CommonLibSSE-NG/src")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()

    findings = {}
    skipped = []
    for path in sorted(args.src_dir.rglob("*.cpp")):
        scan_file(path, findings, skipped)

    print(f"# {len(findings)} class(es) with a pointer-typed RelocateMember[IfNewer] tail found")
    for cls in sorted(findings):
        e = findings[cls]
        print(f"{cls} inferred_min_size=0x{e['inferred_min_size']:x}")
        for ev in e["evidence"]:
            print(f"    {ev}")

    print(f"\n# {len(skipped)} call site(s) skipped (non-pointer type or unattributed class)")
    for path, line, reason in skipped:
        print(f"  {path}: {reason}\n    {line}")

    if args.json:
        import json
        args.json.write_text(json.dumps(findings, indent=2, sort_keys=True))
    if args.csv:
        with args.csv.open("w") as f:
            for cls in sorted(findings):
                f.write(f"{cls},{findings[cls]['inferred_min_size']}\n")


if __name__ == "__main__":
    main()

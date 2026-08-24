#!/usr/bin/env python3
"""Mine `static_assert(sizeof(ClassName) == N)` ground truth from
CommonLibSSE-NG headers, respecting the runtime preprocessor guards
(`#ifndef ENABLE_SKYRIM_AE` etc.) discovered the hard way while getting
TESObjectREFR and BaseExtraList to byte-accurate layouts (see DESIGN.md).

This is Step 1 of the coverage sweep (see ../COVERAGE_SWEEP_PLAN.md): it
produces the expected-size ground truth that Step 4's coverage_report.py
cross-references against the parser's actual output.

Only a handful of guard macros actually appear wrapping a `static_assert
(sizeof(...))` in this codebase (confirmed by grep across all of RE/):
ENABLE_SKYRIM_AE, ENABLE_SKYRIM_SE, ENABLE_SKYRIM_VR, SKYRIM_SUPPORT_AE
(an old CommonLibSSE-original macro name, not set by CommonLibSSE-NG's own
CMakeLists -- treated as always-undefined here), and __INTELLISENSE__
(always undefined for a real compile). This script does NOT attempt a
general C preprocessor -- it tracks a stack of (condition, active) through
#if/#ifdef/#ifndef/#else/#elif/#endif and evaluates only conditions built
from those known macros with `!`/`&&`/`||`/`defined(...)`. Any assert whose
enclosing guard references an unrecognized macro is recorded separately
as "unevaluated guard" rather than silently guessed.

Usage:
    python3 mine_static_asserts.py <path-to-CommonLibSSE-NG>/include [--json out.json]

Output (stdout, unless --json is given): one line per class,
    ClassName 0xNN                  # has an AE-applicable assert
    ClassName NO_AE_ASSERT          # only has asserts guarded for other runtimes
    ClassName UNEVALUATED_GUARD     # guard references an unrecognized macro
"""
import argparse
import json
import re
from pathlib import Path

# Our target runtime: AE defined, SE/VR/legacy-AE-alias/IntelliSense undefined.
# Matches --runtime ENABLE_SKYRIM_AE=1 in tools/GenerateGdt.java / generate_gdt.sh.
TARGET_DEFINED = {"ENABLE_SKYRIM_AE"}
KNOWN_MACROS = {
    "ENABLE_SKYRIM_AE",
    "ENABLE_SKYRIM_SE",
    "ENABLE_SKYRIM_VR",
    "SKYRIM_SUPPORT_AE",
    "__INTELLISENSE__",
}

DIRECTIVE_RE = re.compile(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$')
ASSERT_RE = re.compile(r'static_assert\s*\(\s*sizeof\s*\(\s*([A-Za-z_][A-Za-z0-9_:]*)\s*\)\s*==\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)')
DEFINED_RE = re.compile(r'defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)|defined\s+([A-Za-z_][A-Za-z0-9_]*)')


class UnevaluableGuard(Exception):
    pass


def eval_condition(cond: str) -> bool:
    """Evaluate a preprocessor condition built only from KNOWN_MACROS via
    defined(...)/!/&&/||. Raises UnevaluableGuard for anything else (a
    bare macro used for value comparison, an unrecognized macro, etc.)."""
    cond = cond.strip()
    for name in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', cond):
        if name in ("defined",):
            continue
        if name not in KNOWN_MACROS:
            raise UnevaluableGuard(f"unrecognized macro {name!r} in {cond!r}")

    def sub_defined(m):
        name = m.group(1) or m.group(2)
        return "True" if name in TARGET_DEFINED else "False"

    py_expr = DEFINED_RE.sub(sub_defined, cond)
    py_expr = py_expr.replace("&&", " and ").replace("||", " or ").replace("!", " not ")
    # Bare macro name (used as `#if MACRO`) not wrapped in defined(...):
    # treat identically to defined(MACRO) for this codebase's usage.
    for name in KNOWN_MACROS:
        py_expr = re.sub(rf'\b{name}\b', "True" if name in TARGET_DEFINED else "False", py_expr)
    # eval() here is safe: py_expr is built only from True/False/and/or/not/
    # parens after every identifier was checked against KNOWN_MACROS above
    # (raising UnevaluableGuard otherwise) -- it never contains header text.
    if not re.fullmatch(r'[\sA-Za-z()]*', py_expr):
        raise UnevaluableGuard(f"condition {cond!r} produced unexpected expression {py_expr!r}")
    try:
        return bool(eval(py_expr, {"__builtins__": {}}, {}))
    except Exception as e:
        raise UnevaluableGuard(f"could not evaluate {cond!r} -> {py_expr!r}: {e}")


def ifdef_to_cond(directive: str, rest: str) -> str:
    rest = rest.strip()
    if directive == "ifdef":
        return f"defined({rest})"
    if directive == "ifndef":
        return f"!defined({rest})"
    return rest  # if / elif already carry a full expression


def scan_file(path: Path, results: dict, ambiguous: dict, unevaluated: dict):
    text = path.read_text(errors="ignore")
    # Stack of frames; each frame is a list of (cond_or_None, active_bool_or_None)
    # branches seen so far for that #if group, and whether we're currently in
    # the active (taken) branch. active=None means "guard uses an unrecognized
    # macro -- can't tell if this branch is live for our target runtime".
    stack = []  # each entry: {"taken": bool, "active": bool|None}

    def currently_active():
        return all(frame["active"] is True for frame in stack) if stack else True

    def any_unevaluated():
        return any(frame["active"] is None for frame in stack)

    for line in text.splitlines():
        m = DIRECTIVE_RE.match(line)
        if m:
            directive, rest = m.group(1), m.group(2)
            if directive in ("if", "ifdef", "ifndef"):
                cond = ifdef_to_cond(directive, rest)
                try:
                    active = eval_condition(cond)
                except UnevaluableGuard:
                    active = None
                stack.append({"taken": (active is True), "active": active})
            elif directive == "elif":
                if stack:
                    frame = stack[-1]
                    if frame["taken"]:
                        frame["active"] = False
                    else:
                        try:
                            active = eval_condition(rest)
                        except UnevaluableGuard:
                            active = None
                        frame["active"] = active
                        frame["taken"] = frame["taken"] or (active is True)
            elif directive == "else":
                if stack:
                    frame = stack[-1]
                    if frame["active"] is None:
                        pass  # stays unevaluated
                    else:
                        frame["active"] = not frame["taken"]
                    frame["taken"] = True
            elif directive == "endif":
                if stack:
                    stack.pop()
            continue

        for am in ASSERT_RE.finditer(line):
            cls, size_str = am.group(1), am.group(2)
            size = int(size_str, 16) if size_str.lower().startswith("0x") else int(size_str)
            if any_unevaluated():
                unevaluated.setdefault(cls, []).append((size, str(path)))
            elif currently_active():
                results.setdefault(cls, []).append((size, str(path)))
            else:
                ambiguous.setdefault(cls, []).append((size, str(path)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("include_dir", type=Path, help="Path to CommonLibSSE-NG/include")
    parser.add_argument("--json", type=Path, help="Write JSON {class: expected_size_for_AE} here instead of/in addition to stdout")
    args = parser.parse_args()

    re_dir = args.include_dir / "RE"
    if not re_dir.is_dir():
        raise SystemExit(f"error: {re_dir} not found -- pass the CommonLibSSE-NG/include directory")

    ae_applicable = {}    # class -> [(size, file), ...] active under our target runtime
    other_runtime = {}    # class -> [(size, file), ...] guarded out for our target runtime
    unevaluated = {}      # class -> [(size, file), ...] guard uses an unrecognized macro

    for path in sorted(re_dir.rglob("*.h")):
        scan_file(path, ae_applicable, other_runtime, unevaluated)

    conflicts = {cls: sizes for cls, sizes in ae_applicable.items()
                 if len({s for s, _ in sizes}) > 1}

    ae_map = {}
    for cls, sizes in ae_applicable.items():
        if cls in conflicts:
            continue
        ae_map[cls] = sizes[0][0]

    print(f"# {len(ae_map)} classes with an AE-applicable static_assert(sizeof(...))")
    for cls in sorted(ae_map):
        print(f"{cls} 0x{ae_map[cls]:x}")

    only_other = sorted(set(other_runtime) - set(ae_applicable) - set(unevaluated))
    print(f"\n# {len(only_other)} classes with sizeof asserts only for other runtimes (NO_AE_ASSERT)")
    for cls in only_other:
        print(f"{cls} NO_AE_ASSERT")

    print(f"\n# {len(unevaluated)} classes whose assert sits behind an unrecognized guard (UNEVALUATED_GUARD)")
    for cls in sorted(unevaluated):
        print(f"{cls} UNEVALUATED_GUARD")

    if conflicts:
        print(f"\n# WARNING: {len(conflicts)} classes have multiple DIFFERING AE-applicable "
              f"asserts (different files, or duplicate contradictory asserts) -- excluded "
              f"from the ae_map above, listed here for manual inspection:")
        for cls, sizes in sorted(conflicts.items()):
            print(f"  {cls}: {sizes}")

    if args.json:
        args.json.write_text(json.dumps(ae_map, indent=2, sort_keys=True))
        print(f"\n# Wrote {len(ae_map)}-entry JSON map to {args.json}")


if __name__ == "__main__":
    main()

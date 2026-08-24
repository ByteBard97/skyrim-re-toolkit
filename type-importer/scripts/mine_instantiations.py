#!/usr/bin/env python3
"""Mine concrete template instantiations used across CommonLibSSE-NG's RE/
namespace, for the force-instantiation preprocessing step neither libclang
nor CastXML does automatically (see DESIGN.md's "Base tooling" section).

Handles nested templates (e.g. `BSTArray<NiPointer<NiAVObject>>`), which a
naive single-level regex misses -- confirmed present in this codebase
(8 occurrences of exactly that nesting) during source recon.

Usage:
    python3 mine_instantiations.py <path-to-CommonLibSSE-NG>/include \
        [--template BSTArray] [--template NiPointer] ... \
        [--top N]

Default templates match the ones flattened in DESIGN.md's template table:
BSTArray, NiPointer, BSTSmartPointer, REL::Relocation, stl::enumeration.

Output: one instantiation per line, `TemplateName<Arg1, Arg2, ...>`, with
nested instantiations also emitted standalone (so `BSTArray<NiPointer<X>>`
also yields a separate `NiPointer<X>` line) -- both need force-instantiating
independently, since the outer one requires the inner one to already be a
complete type.
"""
import argparse
import re
from collections import Counter
from pathlib import Path

DEFAULT_TEMPLATES = [
    "BSTArray",
    "NiPointer",
    "BSTSmartPointer",
    "REL::Relocation",
    "stl::enumeration",
]


def find_matching_angle(text: str, open_pos: int) -> int:
    """Given text[open_pos] == '<', return the index of its matching '>'."""
    depth = 0
    i = open_pos
    while i < len(text):
        if text[i] == "<":
            depth += 1
        elif text[i] == ">":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level_args(arg_str: str) -> list[str]:
    """Split `A, B<C, D>, E` into ['A', 'B<C, D>', 'E'] -- commas inside
    nested <...> don't split."""
    args = []
    depth = 0
    current = []
    for ch in arg_str:
        if ch == "<":
            depth += 1
            current.append(ch)
        elif ch == ">":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def mine_template(text: str, template_name: str, counter: Counter, nested_counter: Counter):
    """Find every instantiation of template_name in text, recording it and
    recursively recording any nested instantiations of the SAME set of
    templates found inside its argument list."""
    pattern = re.compile(re.escape(template_name) + r"\s*<")
    for m in pattern.finditer(text):
        open_pos = m.end() - 1
        close_pos = find_matching_angle(text, open_pos)
        if close_pos == -1:
            continue
        arg_str = text[open_pos + 1:close_pos]
        args = split_top_level_args(arg_str)
        instantiation = f"{template_name}<{', '.join(args)}>"
        counter[instantiation] += 1

        # Recurse into each argument looking for nested instantiations of
        # any known template (not just this one) -- BSTArray<NiPointer<X>>
        # needs NiPointer<X> instantiated independently, before BSTArray's
        # own instantiation can complete.
        for arg in args:
            for name in ALL_TEMPLATE_NAMES:
                if re.search(re.escape(name) + r"\s*<", arg):
                    mine_template(arg, name, nested_counter, nested_counter)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("include_dir", type=Path, help="Path to CommonLibSSE-NG/include")
    parser.add_argument("--template", action="append", dest="templates",
                         help="Template name to mine (repeatable). Default: the DESIGN.md flattening-table set.")
    parser.add_argument("--top", type=int, default=0,
                         help="Only print the top N instantiations per template (0 = all)")
    args = parser.parse_args()

    global ALL_TEMPLATE_NAMES
    ALL_TEMPLATE_NAMES = args.templates or DEFAULT_TEMPLATES

    re_dir = args.include_dir / "RE"
    if not re_dir.is_dir():
        raise SystemExit(f"error: {re_dir} not found -- pass the CommonLibSSE-NG/include directory")

    per_template = {name: Counter() for name in ALL_TEMPLATE_NAMES}
    nested_all = Counter()

    for path in re_dir.rglob("*.h"):
        text = path.read_text(errors="ignore")
        for name in ALL_TEMPLATE_NAMES:
            mine_template(text, name, per_template[name], nested_all)

    for name in ALL_TEMPLATE_NAMES:
        counter = per_template[name]
        items = counter.most_common(args.top if args.top > 0 else None)
        print(f"# {name}<T> -- {len(counter)} distinct instantiations")
        for instantiation, count in items:
            print(f"{count:6d}  {instantiation}")
        print()

    if nested_all:
        print(f"# Nested instantiations found inside other templates' arguments "
              f"({len(nested_all)} distinct) -- these need independent force-instantiation")
        print(f"# BEFORE their enclosing template, since the outer one requires them complete:")
        for instantiation, count in nested_all.most_common(args.top if args.top > 0 else None):
            print(f"{count:6d}  {instantiation}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate stub RTTI_*/VTABLE_* constants so CommonLibSSE-NG headers parse
under a bare clang -fsyntax-only pass, without a real per-runtime build.

These names appear only as `inline static constexpr auto RTTI = RTTI_Foo;`
class members (compile-time constants, zero bytes in the instance layout) —
their actual values come from CommonLibSSE-NG's generated, runtime-specific
RTTI/VTABLE tables, which we don't have without a full build. Stubbing them
to 0 cannot corrupt a record layout: they contribute no storage to the class.

Usage:
    python3 generate_symbol_stubs.py <path-to-CommonLibSSE-NG>/include > stubs/generated_symbols.h
"""
import re
import sys
from pathlib import Path

def mine(include_dir: Path, member: str) -> set[str]:
    pattern = re.compile(rf"{member}\s*=\s*({member}_\w+)")
    names = set()
    for path in (include_dir / "RE").rglob("*.h"):
        text = path.read_text(errors="ignore")
        names.update(pattern.findall(text))
    return names

def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    include_dir = Path(sys.argv[1])
    rtti_names = sorted(mine(include_dir, "RTTI"))
    vtable_names = sorted(mine(include_dir, "VTABLE"))

    print("// GENERATED FILE — do not edit by hand.")
    print("// Regenerate with: python3 scripts/generate_symbol_stubs.py "
          "<CommonLibSSE-NG>/include > stubs/generated_symbols.h")
    print("//")
    print("// Stub values for RE/'s per-runtime generated RTTI_*/VTABLE_* constants.")
    print("// These are static-constexpr CLASS members, not instance data — a wrong")
    print("// (or zero) value here cannot change any struct's sizeof or field offsets.")
    print("// They only need to exist and type-check so clang can finish parsing the")
    print("// class body far enough to lay out the actual data members.")
    print("#pragma once")
    print("#include <cstdint>")
    print()
    print(f"// {len(rtti_names)} RTTI_* constants")
    for name in rtti_names:
        print(f"constexpr std::uintptr_t {name} = 0;")
    print()
    print(f"// {len(vtable_names)} VTABLE_* constants")
    for name in vtable_names:
        print(f"constexpr std::uintptr_t {name} = 0;")

if __name__ == "__main__":
    main()

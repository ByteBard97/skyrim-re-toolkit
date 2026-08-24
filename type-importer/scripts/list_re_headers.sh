#!/usr/bin/env bash
# Enumerates every RE/ header that's safe to force-include for a layout-only
# clang parse, for the coverage sweep (see ../COVERAGE_SWEEP_PLAN.md Step 3).
#
# Excludes RE/Skyrim.h: it's CommonLibSSE-NG's own umbrella header, and its
# first line is `#include "SKSE/Impl/PCH.h"` -- the exact header
# stubs/layout_pch.h exists to replace (it pulls spdlog -> real
# <windows.h> -> trips REX/W32/BASE.h's "Windows API detected" guard, and
# collides with our REL::Relocation<T> stand-in). This was hit for real:
# a full sweep that included RE/Skyrim.h in its header list produced
# "'spdlog/spdlog.h' file not found" and "redefinition of 'Relocation'"
# clang errors that don't occur when it's excluded.
#
# Usage:
#   scripts/list_re_headers.sh <path-to-CommonLibSSE-NG>/include
set -euo pipefail

INCLUDE_DIR="${1:?Usage: $0 <path-to-CommonLibSSE-NG>/include}"

EXCLUDE=(
    "RE/Skyrim.h"
)

cd "$INCLUDE_DIR"
find RE -name '*.h' | sort | while read -r h; do
    skip=0
    for ex in "${EXCLUDE[@]}"; do
        [ "$h" = "$ex" ] && skip=1 && break
    done
    [ "$skip" -eq 0 ] && echo "$h"
done

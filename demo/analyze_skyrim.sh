#!/usr/bin/env bash
# Demo driver (issue #1): produce a fully-typed Ghidra project from the
# user's own SkyrimSE.exe plus this repo's generated .gdt, and export
# before/after decompilations of demo target functions.
#
# Nothing from the game is redistributed: this runs against a locally-owned
# binary and produces a local Ghidra project.
#
# Usage:
#   JAVA_HOME=<jdk22+> GHIDRA_INSTALL_DIR=<ghidra12+> \
#     ./analyze_skyrim.sh <SkyrimSE.exe> <archive.gdt> <workdir> [hex-addr ...]
#
# Default demo address: 0x1401D72D0 -- SkyrimSE.exe+01D72D0, a real
# community-reported crash site (null-deref at `mov rax,[rcx+0x30]`),
# used to show crash-log triage: the crash log gives you an address, the
# type archive tells you what it means.
set -euo pipefail

: "${JAVA_HOME:?Set JAVA_HOME to a JDK 22+ install}"
: "${GHIDRA_INSTALL_DIR:?Set GHIDRA_INSTALL_DIR to a Ghidra 12+ install}"

EXE="${1:?path to SkyrimSE.exe}"
GDT="${2:?path to generated .gdt}"
WORK="${3:?working directory for the Ghidra project + outputs}"
shift 3
ADDRS=("${@:-0x1401D72D0}")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEADLESS="$GHIDRA_INSTALL_DIR/support/analyzeHeadless"
export PATH="$JAVA_HOME/bin:$PATH"
mkdir -p "$WORK"

if [ ! -d "$WORK/SkyrimDemo.rep" ] && [ ! -f "$WORK/SkyrimDemo.gpr" ]; then
    echo "== Pass 1: import + auto-analysis (long: 30-90 min) + baseline decompilation" >&2
    "$HEADLESS" "$WORK" SkyrimDemo \
        -import "$EXE" \
        -scriptPath "$SCRIPT_DIR/ghidra_scripts" \
        -postScript DumpDecomp.java "$WORK/before.c" "${ADDRS[@]}"
else
    echo "== Pass 1 skipped: project exists ($WORK/SkyrimDemo.gpr)" >&2
fi

PROG="$(basename "$EXE")"

echo "== Pass 2: apply $GDT (types persist to the project DB)" >&2
"$HEADLESS" "$WORK" SkyrimDemo \
    -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPT_DIR/ghidra_scripts" \
    -postScript ApplyGdt.java "$GDT"

# Optional: type the first parameter of each demo function as a struct from
# the archive, so member accesses render as named fields. Pairs are given as
# RETYPE="<hex-addr>=<TypeName> ..." in the environment.
if [ -n "${RETYPE:-}" ]; then
    RETYPE_ARGS=()
    for pair in $RETYPE; do
        RETYPE_ARGS+=("0x${pair%%=*}" "${pair##*=}")
    done
    echo "== Pass 2b: retype demo functions (${RETYPE})" >&2
    "$HEADLESS" "$WORK" SkyrimDemo \
        -process "$PROG" -noanalysis \
        -scriptPath "$SCRIPT_DIR/ghidra_scripts" \
        -postScript RetypeThis.java "${RETYPE_ARGS[@]}"
fi

echo "== Pass 3: typed decompilation" >&2
"$HEADLESS" "$WORK" SkyrimDemo \
    -process "$PROG" -noanalysis \
    -scriptPath "$SCRIPT_DIR/ghidra_scripts" \
    -postScript DumpDecomp.java "$WORK/after.c" "${ADDRS[@]}"

echo "== Done. Compare:" >&2
echo "   before: $WORK/before.c" >&2
echo "   after:  $WORK/after.c" >&2

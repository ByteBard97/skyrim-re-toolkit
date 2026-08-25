#!/usr/bin/env bash
# End-to-end wrapper: patches the vendored GhidraClangPoweredParse submodule,
# builds it, compiles tools/GenerateGdt.java against it, runs it, and reverts
# the submodule back to pristine afterward.
#
# This is the reusable form of the ad hoc test harnesses used tonight to
# develop and verify patches/0001 through 0005 -- see type-importer/DESIGN.md
# and type-importer/patches/*.md for the full investigation behind why each
# of these pieces is needed.
#
# Requirements (none vendored in-repo -- see DESIGN.md's toolchain note):
#   - JDK 21+ (Temurin or similar), set JAVA_HOME
#   - Ghidra 12+, set GHIDRA_INSTALL_DIR
#   - A real libclang.so reporting as Clang 19+ (the system libclang-14 on
#     many Linux distros is NOT sufficient -- MSVC STL's own version check
#     rejects it). Point LD_LIBRARY_PATH at a directory containing a
#     libclang.so symlink to one, e.g. from a LLVM 19+ release tarball.
#   - Windows SDK + MSVC CRT/STL headers via `xwin` (see DESIGN.md)
#
# Usage:
#   JAVA_HOME=... GHIDRA_INSTALL_DIR=... LD_LIBRARY_PATH=... [REPORT_CSV=...] \
#     ./generate_gdt.sh <winsdk-splat-dir> <output.gdt> [header1.h header2.h ...]
#
# Set REPORT_CSV to also emit a coverage-sweep report (see
# ../COVERAGE_SWEEP_PLAN.md and scripts/coverage_report.py) -- writes
# $REPORT_CSV (ClassName,SizeInBytes for every resolved type) and
# $REPORT_CSV.unresolved.txt (names that never resolved at all).
#
# Example:
#   JAVA_HOME=~/.local/tools/jdk-21.0.12.1+1 \
#   GHIDRA_INSTALL_DIR=~/.local/tools/ghidra_12.1.3_PUBLIC \
#   LD_LIBRARY_PATH=~/.local/tools/compat-libs \
#     ./generate_gdt.sh ~/.local/tools/winsdk /tmp/CommonLibSSE_AE.gdt \
#     RE/T/TESForm.h RE/T/TESObject.h RE/T/TESBoundObject.h RE/T/TESObjectREFR.h
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TYPE_IMPORTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GCPP_DIR="$TYPE_IMPORTER_DIR/vendor/GhidraClangPoweredParse"
COMMONLIB_DIR="$TYPE_IMPORTER_DIR/vendor/CommonLibSSE-NG/include"
STUBS_DIR="$TYPE_IMPORTER_DIR/stubs"

: "${JAVA_HOME:?Set JAVA_HOME to a JDK 21+ install}"
: "${GHIDRA_INSTALL_DIR:?Set GHIDRA_INSTALL_DIR to a Ghidra 12+ install}"

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <winsdk-splat-dir> <output.gdt> <header1.h> [header2.h ...]" >&2
    exit 1
fi
WINSDK_DIR="$1"
OUTPUT_GDT="$2"
shift 2
HEADERS=("$@")

export PATH="$JAVA_HOME/bin:$PATH"

# Panama FFI (java.lang.foreign) is preview in JDK 21, final in JDK 22+.
# On 21 the preview implementation requires -Xint (upcalls crash under JIT)
# and STILL gives order-dependent wrong values from struct-by-value downcalls
# at full-sweep scale -- confirmed by a pure-C libclang probe that shows the
# identical queries are stable and correct at the same scale (see
# patches/0007-inline-template-base-classes.md and patches/0010-*.md).
# JDK 22+ (final FFM) is therefore strongly preferred; patch 0010 ports the
# vendored bindings to the final API and only applies on 22+.
JAVA_MAJOR="$("$JAVA_HOME/bin/java" -version 2>&1 | head -1 | sed 's/[^"]*"\([0-9]*\).*/\1/')"
if [ "$JAVA_MAJOR" -ge 22 ]; then
    JAVAC_FLAGS=(--release 22)
    JAVA_FLAGS=()
else
    echo "warning: JDK $JAVA_MAJOR uses the preview FFM API, which is known to" >&2
    echo "warning: return wrong values at full-sweep scale -- use JDK 22+ instead" >&2
    JAVAC_FLAGS=(--release 21 --enable-preview)
    JAVA_FLAGS=(-Xint --enable-preview)
fi

BUILD_DIR="$(mktemp -d)"
cleanup() {
    echo "Reverting $GCPP_DIR to pristine..." >&2
    (cd "$GCPP_DIR" && git checkout -- . && git clean -fd -- . >/dev/null 2>&1 || true)
    rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

echo "Applying patches 0001-0005 to $GCPP_DIR..." >&2
cd "$GCPP_DIR"
git status --short | grep -q . && {
    echo "error: $GCPP_DIR has uncommitted changes -- refusing to patch over them" >&2
    exit 1
}
for patch in "$TYPE_IMPORTER_DIR"/patches/000{1,2,3,4,5,6,9}-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0011-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0012-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0013-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0014-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0015-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0016-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0017-*.patch \
             "$TYPE_IMPORTER_DIR"/patches/0018-*.patch; do
    patch -p1 < "$patch"
done
if [ "$JAVA_MAJOR" -ge 22 ]; then
    # FFM final-API port -- the renamed methods don't exist on JDK 21.
    patch -p1 < "$TYPE_IMPORTER_DIR"/patches/0010-jdk22-ffm-final-api.patch
fi

echo "Building GhidraClangPoweredParse..." >&2
./gradlew compileJava --offline 2>&1 | tail -5

echo "Building classpath..." >&2
CP="$GCPP_DIR/build/classes/java/main"
CP="$CP:$(find "$GHIDRA_INSTALL_DIR/Ghidra" -iname '*.jar' | tr '\n' ':')"
GRADLE_CACHE_JARS="$(find "$HOME/.gradle/caches" -iname '*.jar' 2>/dev/null | tr '\n' ':')"
CP="$CP:$GRADLE_CACHE_JARS"

echo "Compiling GenerateGdt.java (JDK $JAVA_MAJOR)..." >&2
javac -cp "$CP" -d "$BUILD_DIR" "${JAVAC_FLAGS[@]}" \
    "$TYPE_IMPORTER_DIR/tools/GenerateGdt.java" 2>&1 | grep -v "^Note:\|^warning:" || true

REPORT_ARGS=()
if [ -n "${REPORT_CSV:-}" ]; then
    REPORT_ARGS=(--report-csv "$REPORT_CSV")
fi

# LLVM installs its own SIGSEGV handler ("crash recovery") when an index is
# created. HotSpot's JIT-compiled code deliberately triggers benign SIGSEGVs
# (implicit null checks), which LLVM's handler misreads as crashes and kills
# the JVM -- this was the real cause of the "Panama upcalls crash under JIT"
# symptom that previously forced -Xint. Confirmed via hs_err: SIGSEGV "(sent
# by kill)" inside JIT-compiled Ghidra code, nowhere near FFM or libclang.
export LIBCLANG_DISABLE_CRASH_RECOVERY=1

echo "Running GenerateGdt (JDK $JAVA_MAJOR: flags '${JAVA_FLAGS[*]:-none}')..." >&2
cd "$GHIDRA_INSTALL_DIR"
java "${JAVA_FLAGS[@]}" --enable-native-access=ALL-UNNAMED \
    -cp "$BUILD_DIR:$CP" GenerateGdt \
    --commonlib "$COMMONLIB_DIR" \
    --stubs "$STUBS_DIR" \
    --winsdk-crt "$WINSDK_DIR/crt/include" \
    --winsdk-ucrt "$WINSDK_DIR/sdk/include/ucrt" \
    --output "$OUTPUT_GDT" \
    --runtime ENABLE_SKYRIM_AE=1 \
    "${REPORT_ARGS[@]}" \
    "${HEADERS[@]}"

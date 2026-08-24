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
#   JAVA_HOME=... GHIDRA_INSTALL_DIR=... LD_LIBRARY_PATH=... \
#     ./generate_gdt.sh <winsdk-splat-dir> <output.gdt> [header1.h header2.h ...]
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
for patch in "$TYPE_IMPORTER_DIR"/patches/000{1,2,3,4,5}-*.patch; do
    patch -p1 < "$patch"
done

echo "Building GhidraClangPoweredParse..." >&2
./gradlew compileJava --offline 2>&1 | tail -5

echo "Building classpath..." >&2
CP="$GCPP_DIR/build/classes/java/main"
CP="$CP:$(find "$GHIDRA_INSTALL_DIR/Ghidra" -iname '*.jar' | tr '\n' ':')"
GRADLE_CACHE_JARS="$(find "$HOME/.gradle/caches" -iname '*.jar' 2>/dev/null | tr '\n' ':')"
CP="$CP:$GRADLE_CACHE_JARS"

echo "Compiling GenerateGdt.java..." >&2
javac -cp "$CP" -d "$BUILD_DIR" --release 21 --enable-preview \
    "$TYPE_IMPORTER_DIR/tools/GenerateGdt.java" 2>&1 | grep -v "^Note:\|^warning:" || true

echo "Running GenerateGdt (interpreter mode -- Panama FFI upcalls crash under JIT, a documented GhidraClangPoweredParse limitation)..." >&2
cd "$GHIDRA_INSTALL_DIR"
java -Xint --enable-preview --enable-native-access=ALL-UNNAMED \
    -cp "$BUILD_DIR:$CP" GenerateGdt \
    --commonlib "$COMMONLIB_DIR" \
    --stubs "$STUBS_DIR" \
    --winsdk-crt "$WINSDK_DIR/crt/include" \
    --winsdk-ucrt "$WINSDK_DIR/sdk/include/ucrt" \
    --output "$OUTPUT_GDT" \
    --runtime ENABLE_SKYRIM_AE=1 \
    "${HEADERS[@]}"

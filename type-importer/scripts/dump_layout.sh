#!/usr/bin/env bash
# Compile one or more CommonLibSSE-NG RE/ headers with clang-cl targeting
# x86_64-pc-windows-msvc, and dump every record's layout. This is the
# working incantation from DESIGN.md's toolchain note, turned into a
# reusable script instead of retyping it by hand each time.
#
# Requires (none of these are vendored in-repo — see DESIGN.md's toolchain
# note for why, and for licensing caveats on the Windows SDK/CRT headers):
#   - clang-cl from a recent LLVM release (tested: LLVM 19.1.0 Linux X64).
#     The Ubuntu-18.04-targeted official LLVM tarball does NOT work on a
#     modern glibc/libtinfo6 system -- use a newer "Linux-X64" release
#     instead, or your distro's own clang if it's new enough.
#   - Windows SDK + MSVC CRT/STL headers, acquired via `xwin` (see
#     https://github.com/Jake-Shadle/xwin) -- `xwin --accept-license splat
#     --output <dir>`. These come from Microsoft under their own license;
#     do not commit or redistribute them.
#
# Usage:
#   CLANG_CL=/path/to/clang-cl WINSDK=/path/to/xwin-splat-output \
#     ./dump_layout.sh RE/T/TESForm.h RE/T/TESObjectREFR.h [-- extra clang flags]
#
# Env vars (all overridable):
#   CLANG_CL          path to clang-cl binary (required)
#   WINSDK            path to xwin splat output directory (required)
#   COMMONLIB_INCLUDE path to CommonLibSSE-NG/include (default: vendored submodule)
#   RUNTIME_DEFINE    which runtime macro to define (default: ENABLE_SKYRIM_AE=1)
#   COMPLETE          if set to 1, dump ALL records (even unused ones) via
#                     -fdump-record-layouts-complete instead of only the
#                     ones actually instantiated/used in the TU
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STUBS_DIR="$SCRIPT_DIR/../stubs"
DEFAULT_COMMONLIB="$SCRIPT_DIR/../vendor/CommonLibSSE-NG/include"

: "${CLANG_CL:?Set CLANG_CL to your clang-cl binary path}"
: "${WINSDK:?Set WINSDK to your xwin splat output directory}"
COMMONLIB_INCLUDE="${COMMONLIB_INCLUDE:-$DEFAULT_COMMONLIB}"
RUNTIME_DEFINE="${RUNTIME_DEFINE:-ENABLE_SKYRIM_AE=1}"

if [ "$#" -eq 0 ]; then
    echo "Usage: $0 <header1.h> [header2.h ...] [-- extra clang flags]" >&2
    exit 1
fi

headers=()
extra_flags=()
seen_dashdash=0
for arg in "$@"; do
    if [ "$arg" = "--" ]; then
        seen_dashdash=1
        continue
    fi
    if [ "$seen_dashdash" -eq 1 ]; then
        extra_flags+=("$arg")
    else
        headers+=("$arg")
    fi
done

tmpfile="$(mktemp --suffix=.cpp)"
trap 'rm -f "$tmpfile"' EXIT
for h in "${headers[@]}"; do
    echo "#include \"$h\"" >> "$tmpfile"
done

dump_flag="-fdump-record-layouts"
[ "${COMPLETE:-0}" = "1" ] && dump_flag="-fdump-record-layouts-complete"

"$CLANG_CL" "$tmpfile" -fsyntax-only -ferror-limit=0 -Xclang "$dump_flag" \
    /std:c++20 /EHsc \
    /FI"layout_pch.h" \
    -I "$STUBS_DIR" \
    -I "$COMMONLIB_INCLUDE" \
    -imsvc "$WINSDK/crt/include" \
    -imsvc "$WINSDK/sdk/include/ucrt" \
    -D_WIN64 -DWIN32 -D"$RUNTIME_DEFINE" \
    "${extra_flags[@]}"

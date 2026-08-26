#!/usr/bin/env python3
"""Cross-check every REL::VariantID(se_id, ae_id, vr_offset) triple mined
from CommonLibSSE-NG's own headers against a real meh321 Address Library
version.bin/versionlib.bin file, to confirm the IDs CommonLibSSE-NG
declares are genuine, real Address Library entries -- not typos or
placeholder values.

Binary format ported directly from CommonLibSSE-NG's REL/ID.h
(header_t::read, IDDatabase::unpack_file) -- see that file for the
authoritative C++ source this mirrors 1:1. Format 1 = version.bin (SE/VR
naming), format 2 = versionlib.bin (AE naming); same delta-encoded
mapping_t layout in both.

Scope note: this validates ID *existence and resolvability*, not that a
specific offset is correct against a specific target binary (we don't
have real game binaries here, and none of this touches type-importer's
own struct-LAYOUT output -- REL::VariantID has nothing to do with
sizeof()). It's a provenance check on CommonLibSSE-NG's own data, using
whatever real Address Library .bin fixture is available (e.g. the ones
vendored under vendor/CommonLibSSE-NG/tests/REL/ for its own unit tests).

Usage:
    python3 check_address_library_ids.py <path-to-CommonLibSSE-NG>/include \
        --addrlib <path/to/version-X.Y.Z-0.bin> --format {1,2} --column {se,ae}
"""
import argparse
import glob
import re
import struct
from pathlib import Path

VARIANT_ID_RE = re.compile(
    r'REL::VariantID\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)')


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, fmt):
        size = struct.calcsize(fmt)
        val = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return val[0] if len(val) == 1 else val

    def skip(self, n):
        self.pos += n


def parse_address_library(path: Path, expect_format: int) -> dict:
    """Returns {id: offset} for every entry in the .bin file."""
    r = _Reader(path.read_bytes())

    fmt = r.read("<i")
    if fmt != expect_format:
        raise ValueError(f"{path}: format mismatch (file has {fmt}, expected {expect_format})")
    r.skip(4 * 4)  # version[4]
    name_len = r.read("<i")
    r.skip(name_len)
    pointer_size = r.read("<i")
    address_count = r.read("<i")

    mapping = {}
    prev_id = prev_offset = 0
    for _ in range(address_count):
        type_byte = r.read("<B")
        lo, hi = type_byte & 0xF, type_byte >> 4

        if lo == 0: id_ = r.read("<Q")
        elif lo == 1: id_ = prev_id + 1
        elif lo == 2: id_ = prev_id + r.read("<B")
        elif lo == 3: id_ = prev_id - r.read("<B")
        elif lo == 4: id_ = prev_id + r.read("<H")
        elif lo == 5: id_ = prev_id - r.read("<H")
        elif lo == 6: id_ = r.read("<H")
        elif lo == 7: id_ = r.read("<I")
        else: raise ValueError(f"unhandled id type {lo}")

        tmp = (prev_offset // pointer_size) if (hi & 8) else prev_offset
        sub = hi & 7
        if sub == 0: offset = r.read("<Q")
        elif sub == 1: offset = tmp + 1
        elif sub == 2: offset = tmp + r.read("<B")
        elif sub == 3: offset = tmp - r.read("<B")
        elif sub == 4: offset = tmp + r.read("<H")
        elif sub == 5: offset = tmp - r.read("<H")
        elif sub == 6: offset = r.read("<H")
        elif sub == 7: offset = r.read("<I")
        else: raise ValueError(f"unhandled offset type {sub}")
        if hi & 8:
            offset *= pointer_size

        mapping[id_] = offset
        prev_id, prev_offset = id_, offset

    return mapping


def mine_variant_ids(include_dir: Path, column: str) -> set:
    idx = {"se": 0, "ae": 1}[column]
    ids = set()
    for path in glob.glob(str(include_dir / "**" / "*.h"), recursive=True):
        text = Path(path).read_text(errors="ignore")
        for m in VARIANT_ID_RE.finditer(text):
            ids.add(int(m.group(1 + idx)))
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("include_dir", type=Path)
    parser.add_argument("--addrlib", type=Path, required=True)
    parser.add_argument("--format", type=int, choices=[1, 2], required=True,
                         help="1 = version.bin (SE/VR), 2 = versionlib.bin (AE)")
    parser.add_argument("--column", choices=["se", "ae"], required=True,
                         help="Which REL::VariantID column to check (se_id or ae_id)")
    args = parser.parse_args()

    real = parse_address_library(args.addrlib, args.format)
    ids = mine_variant_ids(args.include_dir, args.column)
    ids.discard(0)  # 0 is CommonLibSSE-NG's own "not applicable to this runtime" sentinel

    found = sorted(i for i in ids if i in real)
    missing = sorted(i for i in ids if i not in real)

    print(f"# {args.column}_id cross-check against {args.addrlib.name} "
          f"({len(real)} real entries)")
    print(f"Checked: {len(ids)} unique non-zero {args.column}_ids from headers")
    print(f"Found:   {len(found)} ({100 * len(found) / len(ids):.2f}%)")
    print(f"Missing: {len(missing)}")
    if missing:
        print("Missing IDs (not in the real Address Library -- investigate):")
        for i in missing[:50]:
            print(f"  {i}")
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")


if __name__ == "__main__":
    main()

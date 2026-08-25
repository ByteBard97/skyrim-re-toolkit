#!/usr/bin/env python3
"""Build the self-contained type-layout explorer (index.html) from a .gdt
dump plus the coverage ground truth.

Pipeline:
  1. tools/DumpGdtJson.java (headless Ghidra) dumps a .gdt to types.json
  2. this script cross-references scripts/mine_static_asserts.py ground truth
     and inlines the result into explorer/template.html -> explorer/index.html

Usage:
  python3 build.py <types.json> <ae_sizes.json> [--patchset 0001-0014]
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("types_json", type=Path)
    ap.add_argument("ground_truth", type=Path)
    ap.add_argument("--patchset", default="")
    ap.add_argument("--out", type=Path, default=HERE / "index.html")
    args = ap.parse_args()

    types = json.loads(args.types_json.read_text())
    gt = json.loads(args.ground_truth.read_text())
    gt_bare = {}
    for k, v in gt.items():
        gt_bare.setdefault(k.split("::")[-1], []).append(v)

    # This explorer is about SKYRIM engine types. The .gdt also carries every
    # C++ stdlib and Windows-SDK type the headers pull in transitively; those
    # are noise here. Drop them: STL lives in extension-less umbrella headers
    # (/algorithm, /atomic) or /__msvc_*.hpp; a small set of Windows-API
    # headers (D3D*, DINPUT, DXGI, KERNEL32, USER32, XINPUT, COM, SCEPAD)
    # are the REX::W32 stand-ins; and STL internal names start with '_'.
    WINSDK = {"/D3D.h", "/D3D11.h", "/D3D11_1.h", "/D3D11_2.h", "/D3D11_3.h",
              "/DINPUT.h", "/DXGI.h", "/KERNEL32.h", "/USER32.h", "/XINPUT.h",
              "/COM.h", "/SCEPAD.h", "/D3DCOMPILER.h"}

    def is_game(t):
        n, c = t["name"], t.get("category", "")
        if n.startswith("_") or "(unnamed" in n or "(anonymous" in n:
            return False
        if c in WINSDK:
            return False
        if not c.endswith(".h"):   # STL umbrella headers / __msvc_*.hpp
            return False
        return True

    out, ok, mism, noref, dropped = [], 0, 0, 0, 0
    for t in types["types"]:
        if t["kind"] not in ("struct", "union", "enum"):
            continue
        if not is_game(t):
            dropped += 1
            continue
        name = t["name"]
        exp = gt.get(name)
        if exp is None:
            cands = gt_bare.get(name.split("::")[-1], [])
            if len(cands) == 1:
                exp = cands[0]
        status = "unverified"
        if t["kind"] != "enum" and exp is not None:
            if t["size"] == exp:
                status, ok = "verified", ok + 1
            else:
                status, mism = "mismatch", mism + 1
        elif t["kind"] != "enum":
            noref += 1
        rec = {"name": name, "kind": t["kind"], "size": t["size"], "status": status}
        if t["kind"] == "enum":
            rec["values"] = t.get("values", [])
        else:
            rec["fields"] = t.get("fields", [])
        if exp is not None and t["kind"] != "enum":
            rec["expected"] = exp
        out.append(rec)

    out.sort(key=lambda r: r["name"].lower())
    payload = {
        "generated_from": types.get("source", ""),
        "patchset": args.patchset,
        "counts": {"verified": ok, "mismatch": mism, "unverified": noref},
        "types": out,
    }
    html = (HERE / "template.html").read_text()
    html = html.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    args.out.write_text(html)
    print(f"wrote {args.out} ({args.out.stat().st_size/1024:.0f} KB) — "
          f"{len(out)} game types, {ok} verified, {mism} mismatch, {noref} no-assert "
          f"({dropped} stdlib/SDK types filtered out)")


if __name__ == "__main__":
    main()

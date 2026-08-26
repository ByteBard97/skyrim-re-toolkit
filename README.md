# skyrim-re-toolkit

**Reverse-engineering infrastructure for Skyrim and the Creation Engine.**

This is a collection of tools, type archives, and runtime instrumentation that lowers the friction of Skyrim binary reverse engineering. If you have ever opened Ghidra to a stripped `SkyrimSE.exe` and wondered why you were hand-typing struct definitions that the community already figured out five years ago, this toolkit is for you.

> The Skyrim modding ecosystem has spent fifteen years mapping the Creation Engine. The accumulated knowledge lives in [CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG), [meh321's Address Library](https://github.com/meh321/AddressLibraryDatabase), and a handful of pinned Discord attachments. Our goal is to turn that knowledge into versioned, reproducible, public infrastructure.

---

## What's in here

```
skyrim-re-toolkit/
├── type-importer/          # C++ headers → Ghidra / IDA type archives
│   ├── DESIGN.md           # Full investigation log: root-causes, verification, open questions
│   ├── patches/            # 13 accepted fixes for the vendored parser (+ 2 deferred investigations), each with a .md writeup
│   ├── scripts/            # generate_gdt.sh, coverage sweep + supporting tooling (mining, layout dumps)
│   ├── tools/              # GenerateGdt.java — the real CLI
│   ├── stubs/              # Minimal headers so real CommonLibSSE-NG parses without a full build
│   └── vendor/             # CommonLibSSE-NG + GhidraClangPoweredParse (git submodules)
├── symbol-archive/         # CI-built AE .gdt workflow artifact (early scaffold, see its README)
└── runtime-harness/        # SKSE plugins for live engine inspection (skeleton, first Windows build in progress)
```

### 1. type-importer

**The problem:** CommonLibSSE-NG contains thousands of reverse-engineered C++ class definitions, struct layouts, vtables, and bitfields. Getting them into Ghidra currently means either (a) hunting for a floating `types.h` file in a Discord server, or (b) manually recreating every struct by hand.

**The solution:** A parser pipeline that reads CommonLibSSE-NG headers and emits Ghidra Data Type Archives (`.gdt`) and IDA Type Libraries (`.til`), built on [`playday3008/GhidraClangPoweredParse`](https://github.com/playday3008/GhidraClangPoweredParse) (a libclang-based Ghidra extension), vendored as a submodule and patched with **fifteen accepted fixes** (patches 0001–0006, 0009–0018; 0007 template base-class inlining and 0008 `isPolymorphic` template-blindness remain deferred — see `type-importer/patches/`) developed and verified against real CommonLibSSE-NG headers. A full-namespace coverage sweep now reports **1,934 classes byte-accurate** against the headers' own `static_assert`s (up from ~1,000), gated in CI so no change can silently regress a previously-correct class. A prioritized 39-class "hotspot" list of the most modder-relevant classes is 37/39 exact.

- **Primary approach:** libclang preprocessing → flattened C-compatible structs → Ghidra's Java type-manager API
- **Handles:** `BSTArray<T>`, `REL::Relocation`, `stl::enumeration`, multiple inheritance (including template-specialization base classes), MSVC bitfield packing, `std::`-qualified builtin types

**Status: working v0.1 MVP, verified against real headers — now with a full-namespace coverage sweep.** The `TESForm → TESObject → TESBoundObject → TESObjectREFR` hierarchy (AE 1.6.1170) resolves to byte-accurate layouts, cross-checked three independent ways: the headers' own `static_assert`s, hand-derived offset math, and real `clang-cl` compilation. Beyond that hierarchy, a coverage sweep (`type-importer/scripts/coverage_report.py`) checks every class in `RE/` against its own `static_assert` — as of the last full sweep, **1,934 of 3,019 checkable classes (64%) are byte-accurate**, with a CI regression gate (`.github/workflows/type-importer-coverage.yml`) ensuring future patches can't silently break a previously-correct class. A prioritized 39-class "hotspot" list of the most modder-relevant classes is 37/39 exact, with the last 2 gaps root-caused and documented (not silent failures — see `type-importer/COVERAGE_SWEEP_PLAN.md`). Full investigation, root-causes, and verification methodology in `type-importer/DESIGN.md` and `type-importer/patches/*.md`. SE 1.5.97 and VR 1.4.15 layouts are now validated and CI-gated; AE 1.7.99 and GOG use the same header macro as 1.6.1170 and need no separate work. Not yet done: IDA `.til` output (blocked on IDA access for verification) and Address Library RVA-level cross-checks against real game binaries (out of scope per this project's ground rules against acquiring Bethesda binaries).

**Try it now:** see [Quick Start](#quick-start) below — `type-importer/scripts/generate_gdt.sh` runs the whole pipeline end to end in one command.

### 2. symbol-archive

**The problem:** Every time Bethesda ships a patch, class layouts shift, Address Library format changes (ask anyone who hit `Unsupported address library format: 5` on 1.7.99), and the community's accumulated Ghidra databases become stale. There is no canonical, versioned archive of pre-built type files.

**The solution (planned):** A CI-driven repository that publishes pre-built type archives for every supported Skyrim runtime — SE 1.5.97, AE 1.6.640/1.6.1170/1.7.99, VR 1.4.15, GOG 1.6.1179.

**Status: early scaffold, AE only.** A GitHub Actions workflow (`.github/workflows/symbol-archive-build.yml`, manual dispatch) wraps `type-importer/scripts/generate_gdt.sh` to build a full-namespace AE `.gdt` and publish it as a workflow artifact. See `symbol-archive/README.md` for the honest accuracy caveat — 1,934 classes are byte-accurate today, so this is a real, traceable build artifact, with the rest of the long tail documented rather than silently wrong. SE/VR layouts are now validated (see `type-importer/`); a first public, versioned GitHub Release (not just a workflow artifact) is the next planned step. See `demo/` for a worked before/after showing what the archive buys you in Ghidra.

### 3. runtime-harness

**The problem:** The Skyrim RE community has excellent static tooling (IDA, Ghidra, BinDiff) and excellent animation introspection (Open Animation Replacer). But the engine's **AI scheduler**, **Havok physics step**, and **savegame serializer** have zero purpose-built runtime visibility. Every finding about them arrives as static RE embedded in patch code.

**The solution (planned):** SKSE plugins that hook into under-instrumented subsystems and log their internal state — e.g. an `AIProcessInspector` for package evaluation and scheduler decisions, a `HavokStepLogger` for collision/ragdoll state, a `SavegameTracer` for `BGSSaveLoadManager` serialization.

**Status: skeleton in progress — Windows build machine online.** `runtime-harness/` now holds a minimal CommonLibSSE-NG plugin (logging + version report + `kDataLoaded` listener) whose only job is to prove the Windows/MSVC/vcpkg toolchain before real inspectors are built. Builds happen on a dedicated Windows machine driven over SSH; this piece still cannot be built or tested on Linux (see `type-importer/DESIGN.md`'s platform-constraints note).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    skyrim-re-toolkit                        │
├──────────────────┬──────────────────┬───────────────────────┤
│   type-importer  │  symbol-archive  │   runtime-harness     │
│  (parse + emit)  │  (distribute)    │   (inspect live)      │
└────────┬─────────┴────────┬─────────┴───────────┬───────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│              CommonLibSSE-NG (source of truth)              │
│         https://github.com/CharmedBaryon/CommonLibSSE-NG   │
├─────────────────────────────────────────────────────────────┤
│  meh321 Address Library  │  SKSE  │  libxse/commonlib-shared │
└─────────────────────────────────────────────────────────────┘
```

**Design principle:** We do not reverse-engineer the game from scratch. We **instrument, package, and distribute** the knowledge that the community has already produced.

---

## Quick Start

### Clone (this repo uses git submodules)

```bash
git clone --recurse-submodules https://github.com/ByteBard97/skyrim-re-toolkit.git
# Already cloned without --recurse-submodules? Run:
#   git submodule update --init --recursive
```

### Prerequisites for the type-importer

None of these are vendored in-repo (large and/or license-bearing — see `type-importer/DESIGN.md`'s toolchain note):

| Requirement | Why | Notes |
|---|---|---|
| JDK 21+ | Panama FFI (used by the Ghidra extension) | Temurin works fine |
| Ghidra 12+ | Provides the type-manager Java API this pipeline runs against headlessly | No GUI/project needed |
| A real `libclang.so`, Clang **19+** | MSVC STL's own headers reject older Clang versions | The `libclang-14` that ships with many Linux distros is **not** sufficient — grab a recent LLVM release tarball and point `LD_LIBRARY_PATH` at a directory containing a `libclang.so` symlink to it |
| Windows SDK + MSVC CRT/STL headers | CommonLibSSE-NG's headers need real `<cstdint>` etc. to lay out correctly | Acquire via [`xwin`](https://github.com/Jake-Shadle/xwin): `xwin --accept-license splat --output <dir>` (Microsoft's own license terms apply — don't commit or redistribute the output) |

### Generate a `.gdt` yourself

```bash
cd type-importer/scripts
JAVA_HOME=/path/to/jdk-21 \
GHIDRA_INSTALL_DIR=/path/to/ghidra_12 \
LD_LIBRARY_PATH=/path/to/dir-containing-libclang.so \
  ./generate_gdt.sh /path/to/xwin-splat-dir /tmp/CommonLibSSE_AE.gdt \
  RE/T/TESForm.h RE/T/TESObject.h RE/T/TESBoundObject.h RE/T/TESObjectREFR.h
```

This patches the vendored `GhidraClangPoweredParse` submodule (from `type-importer/patches/`), builds it, runs the parser against the requested headers, writes a real `.gdt`, and reverts the submodule back to pristine when it's done. See `type-importer/tools/GenerateGdt.java`'s header comment for the full requirement list and manual-invocation form.

### Load the `.gdt` into Ghidra

In Ghidra: **File → Import File** (select `SkyrimSE.exe`) → **Window → Data Type Manager → File → Add Archive** → select your generated `.gdt` → right-click → **Apply Function Data Types**.

### `symbol-archive` and `runtime-harness`

See their sections above for status. `runtime-harness` requires Windows + Visual Studio + SKSE64 (now available via the project's Windows build machine); it can't be built on Linux the way `type-importer` can.

---

## Roadmap

| Milestone | Status | Notes / Blockers |
|-----------|--------|----------|
| v0.1 — GDT for `TESForm`→`TESObjectREFR` chain (AE 1.6.1170) | ✅ **Done, verified** | See `type-importer/DESIGN.md` and `type-importer/patches/` |
| v0.1.1 — Extend to more of the class hierarchy | In progress | Full-namespace coverage sweep built and running (see `type-importer/scripts/coverage_report.py`); **1,934 classes byte-accurate**, 39-class hotspot list 37/39 exact, with the last 2 gaps root-caused and documented (`type-importer/COVERAGE_SWEEP_PLAN.md`) rather than open |
| v0.1.2 — IDA `.til` output | Not started | `.gdt` path is proven; `.til` export is a separate code path; blocked on IDA access for local verification |
| v0.2 — Other runtimes (SE 1.5.97, AE 1.7.99, VR, GOG) | In progress | SE 1.5.97 and VR 1.4.15 validated layout-wise against their own headers' `static_assert`s (see `type-importer/RUNTIME_SE_1_5_97.md`, `RUNTIME_VR_1_4_15.md`); both wired into CI as a matrix job. AE 1.7.99/GOG share AE 1.6.1170's macro and Address Library ID scheme with no compile-time layout distinction, so they're already covered by the existing AE baseline — no separate sweep needed. Address Library ID cross-check done for SE/AE (see `type-importer/ADDRESS_LIBRARY_VALIDATION.md`): 100% of CommonLibSSE-NG's declared IDs (8,379 SE + 8,702 AE) resolve in real Address Library databases. Remaining: confirming resolved RVAs against a real disassembled binary (needs real game binaries, out of scope per this project's ground rules) |
| v0.3 — CI auto-build on CommonLibSSE-NG releases | In progress | `type-importer` has a CI regression gate (`.github/workflows/type-importer-coverage.yml`); `symbol-archive` has a manual-dispatch AE build (`.github/workflows/symbol-archive-build.yml`). Both Linux-native GitHub Actions runners. Automatic rebuild on submodule bump not started |
| v0.4 — AIProcessInspector / runtime-harness plugin | In progress | Windows build machine online; minimal CommonLibSSE-NG plugin **builds to a verified SKSE DLL and runs in-game** (`runtime-harness/`, static x64, all three SKSE exports, `RuntimeHarness.log` confirms plugin load + `kDataLoaded` against a live Skyrim AE 1.6.1170 process); `AIProcessInspector` hook code written and compile-verified but not yet confirmed against live gameplay data |
| v0.5 — Cross-game type propagation (Skyrim → Fallout 4 → Starfield) | Not started | `libxse/commonlib-shared` header unification |
| v1.0 — Stable release with full documentation | Not started | Community validation; maintainer feedback |

---

## Contributing

We are not looking for novel research. We are looking for **reliable engineering**:

- **Type importer:** If you know libclang, Ghidra's Java API, or MSVC ABI quirks, we need you.
- **Symbol archive:** If you can write GitHub Actions workflows or validate struct layouts against live binaries, we need you.
- **Runtime harness:** If you have built SKSE plugins and know your way around `AIProcess`, `hkpCharacterProxy`, or `BGSSaveLoadManager`, we need you.

**Ground rules:**
- No console exploits, no DRM circumvention, no redistribution of game binaries.
- All types and offsets must be derivable from public community sources (CommonLibSSE-NG, Address Library, RTTI).
- Respect the GPL-3.0 + Modding Exception licensing of `libxse` repositories.

---

## Acknowledgments

This toolkit is a packaging layer around fifteen years of community labor:

- **Ryan-rsm-McKenzie** for CommonLibSSE (2018)
- **powerof3, CharmedBaryon, alandtse** for CommonLibSSE-NG and multi-runtime maintenance
- **meh321** for the Address Library and IDADiffCalculator
- **ianpatt / behippo** for SKSE and the `ianpatt/common` shared base
- **DaymareOn** for the SSE-Ghidra-Tutorial and the original "we really need some tooling" TODO
- **Nukem9, himika, aers, shad0wshayd3** for engine-level patches and RE findings
- **The xSE RE Discord** for the knowledge that currently has no other home

If we have done our job right, the next generation of reversers will never know how much of this used to live in pinned Discord messages.

---

## License

This project is licensed under the MIT License. 

Type archives generated from CommonLibSSE-NG inherit the GPL-3.0 license of their source headers (see `type-importer/DESIGN.md`'s licensing note).

> **Note:** We do not ship game binaries, PDBs, or copyrighted assets. The symbol archive contains only community-derived type definitions (struct layouts, enum values, function signatures) which are facts about the game's memory layout, not copies of Bethesda's code.

---

## Contact

- Issues: [GitHub Issues](https://github.com/ByteBard97/skyrim-re-toolkit/issues)
- Discussion: [GitHub Discussions](https://github.com/ByteBard97/skyrim-re-toolkit/discussions)
- Real-time: We monitor the Skyrim SE RE and xSE Discord servers (same handles as GitHub)

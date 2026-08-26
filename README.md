# skyrim-re-toolkit

**Reverse-engineering infrastructure for Skyrim and the Creation Engine.**

[![coverage sweep](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/type-importer-coverage.yml/badge.svg)](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/type-importer-coverage.yml) [![symbol-archive build](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/symbol-archive-build.yml/badge.svg)](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/symbol-archive-build.yml)

This is a collection of tools, type archives, and runtime instrumentation that lowers the friction of Skyrim binary reverse engineering. If you have ever opened Ghidra to a stripped `SkyrimSE.exe` and wondered why you were hand-typing struct definitions that the community already figured out five years ago, this toolkit is for you.

**[→ Browse the docs site](https://bytebard97.github.io/skyrim-re-toolkit/)** for a more scannable, screenshot-driven walkthrough of what's here and how to use it (this README is the thorough version).

> The Skyrim modding ecosystem has spent fifteen years mapping the Creation Engine. The accumulated knowledge lives in [CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG), [meh321's Address Library](https://github.com/meh321/AddressLibraryDatabase), and a handful of pinned Discord attachments. Our goal is to turn that knowledge into versioned, reproducible, public infrastructure.

---

## What's in here

```
skyrim-re-toolkit/
├── type-importer/          # C++ headers → Ghidra / IDA type archives
│   ├── DESIGN.md           # Full investigation log: root-causes, verification, open questions
│   ├── patches/            # 24 accepted fixes/features for the vendored parser (+ 3 deferred investigations: 0007 superseded, 0008 partial, 0020 deferred), each with a .md writeup
│   ├── scripts/            # generate_gdt.sh, coverage sweep + supporting tooling (mining, layout dumps)
│   ├── tools/              # GenerateGdt.java — the real CLI
│   ├── stubs/              # Minimal headers so real CommonLibSSE-NG parses without a full build
│   └── vendor/             # CommonLibSSE-NG + GhidraClangPoweredParse (git submodules)
├── symbol-archive/         # CI-built .gdt workflow artifacts, AE/SE/VR matrix (early scaffold, see its README)
└── runtime-harness/        # SKSE plugins for live engine inspection (AIProcessInspector + SavegameTracer verified in-game; HavokStepLogger deployed, not yet producing output)
```

### 1. type-importer

**The problem:** CommonLibSSE-NG contains thousands of reverse-engineered C++ class definitions, struct layouts, vtables, and bitfields. Getting them into Ghidra currently means either (a) hunting for a floating `types.h` file in a Discord server, or (b) manually recreating every struct by hand.

**The solution:** A parser pipeline that reads CommonLibSSE-NG headers and emits Ghidra Data Type Archives (`.gdt`) and IDA Type Libraries (`.til`), built on [`playday3008/GhidraClangPoweredParse`](https://github.com/playday3008/GhidraClangPoweredParse) (a libclang-based Ghidra extension), vendored as a submodule and patched with **24 accepted fixes/features** (patches 0001–0006, 0009–0019, 0021–0025; 0007 template base-class inlining was superseded and reverted (its remaining known-regression cluster was independently resolved by patch 0025, a fresh root-cause investigation, not a revival of 0007 itself), 0008 `isPolymorphic` template-blindness is partially fixed via 0021 with the rest documented as a follow-on investigation, and 0020's typedef-qualification fix is deferred with a written regression reason — see `type-importer/patches/`) developed and verified against real CommonLibSSE-NG headers. A full-namespace coverage sweep now reports **2,092 classes byte-accurate** against the headers' own `static_assert`s (up from ~1,000), gated in CI so no change can silently regress a previously-correct class. A prioritized 39-class "hotspot" list of the most modder-relevant classes is fully closed: 37/39 byte-exact, and the remaining 2 (`BaseExtraList`/`ExtraDataList`, which the AE headers themselves compile empty via a runtime-relocated-member pattern) have real inferred sizes instead of silent 1-byte placeholders.

- **Primary approach:** libclang preprocessing → flattened C-compatible structs → Ghidra's Java type-manager API
- **Handles:** `BSTArray<T>`, `REL::Relocation`, `stl::enumeration`, multiple inheritance (including template-specialization base classes), MSVC bitfield packing, `std::`-qualified builtin types

**Status: working v0.1 MVP, verified against real headers — now with a full-namespace coverage sweep.** The `TESForm → TESObject → TESBoundObject → TESObjectREFR` hierarchy (AE 1.6.1170) resolves to byte-accurate layouts, cross-checked three independent ways: the headers' own `static_assert`s, hand-derived offset math, and real `clang-cl` compilation. Beyond that hierarchy, a coverage sweep (`type-importer/scripts/coverage_report.py`) checks every class in `RE/` against its own `static_assert` — as of the last full sweep, **2,092 of 3,146 checkable classes (66%) are byte-accurate**, with a CI regression gate (`.github/workflows/type-importer-coverage.yml`) ensuring future patches can't silently break a previously-correct class. The prioritized 39-class "hotspot" list of the most modder-relevant classes is now fully closed: 37/39 byte-exact, and the last 2 (`BaseExtraList`/`ExtraDataList`) have real inferred sizes (patch 0019, `REL::RelocateMember` offset inference) instead of silent 1-byte placeholders — see `type-importer/COVERAGE_SWEEP_PLAN.md`. Full investigation, root-causes, and verification methodology in `type-importer/DESIGN.md` and `type-importer/patches/*.md`. SE 1.5.97 and VR 1.4.15 layouts are now validated and CI-gated; AE 1.7.99 and GOG use the same header macro as 1.6.1170 and need no separate work. Not yet done: IDA `.til` output (blocked on IDA access for verification) and Address Library RVA-level cross-checks against real game binaries (out of scope per this project's ground rules against acquiring Bethesda binaries).

**Try it now:** see [Quick Start](#quick-start) below — `type-importer/scripts/generate_gdt.sh` runs the whole pipeline end to end in one command. See [`demo/`](demo/README.md) for a real Ghidra screenshot of the result — a real `SkyrimSE.exe`, not a mockup.

### 2. symbol-archive

**The problem:** Every time Bethesda ships a patch, class layouts shift, Address Library format changes (ask anyone who hit `Unsupported address library format: 5` on 1.7.99), and the community's accumulated Ghidra databases become stale. There is no canonical, versioned archive of pre-built type files.

**The solution (planned):** A CI-driven repository that publishes pre-built type archives for every supported Skyrim runtime — SE 1.5.97, AE 1.6.640/1.6.1170/1.7.99, VR 1.4.15, GOG 1.6.1179.

**Status: early scaffold, AE/SE/VR matrix live-verified.** A GitHub Actions workflow (`.github/workflows/symbol-archive-build.yml`, manual dispatch) wraps `type-importer/scripts/generate_gdt.sh` to build a full-namespace `.gdt` per runtime (AE, SE, VR) and publish each as a workflow artifact, with opt-in publishing to a versioned GitHub Release. All three matrix legs have completed a real run successfully. See `symbol-archive/README.md` for the accuracy caveat — 2,092 classes are byte-accurate today, so this is a real, traceable build artifact, with the rest of the long tail documented rather than silently wrong. See `demo/` for a worked before/after showing what the archive buys you in Ghidra.

### 3. runtime-harness

**The problem:** The Skyrim RE community has excellent static tooling (IDA, Ghidra, BinDiff) and excellent animation introspection (Open Animation Replacer). But the engine's **AI scheduler**, **Havok physics step**, and **savegame serializer** have zero purpose-built runtime visibility. Every finding about them arrives as static RE embedded in patch code.

**The solution:** SKSE plugins that hook into under-instrumented subsystems and log their internal state — e.g. an `AIProcessInspector` for package evaluation and scheduler decisions, a `HavokStepLogger` for collision/ragdoll state, a `SavegameTracer` for `BGSSaveLoadManager` serialization.

**Status: two of three inspectors verified in-game.** `AIProcessInspector` hooks `Actor::Update` (on both `RE::VTABLE_Actor` and `RE::VTABLE_Character`, since live NPCs are `Character` instances with their own vtable) and logs real package-evaluation transitions — confirmed against a live Skyrim AE 1.6.1170 process (SKSE64 2.2.6): a dozen-plus NPCs' packages changed and were logged during a fresh game's opening scene. `SavegameTracer` (hooks `BGSSaveLoadManager::ProcessEvent`) is also confirmed firing live with a real `saveGameList` query. `HavokStepLogger` (hooks `bhkCharacterState::Update` across all six concrete character-state vtables, index verified by hand) is deployed but produced zero log lines across 70+ minutes of real gameplay (Helgen intro, open-world Whiterun, combat-adjacent NPC activity) — long enough to rule out timing as the explanation. `PlayerCharacter`-specific-hierarchy was checked and ruled out too. Checked real prior art: [ersh1/Precision](https://github.com/ersh1/Precision) (GPL-3.0, the standard SKSE-community reference for Havok hooking) has zero references to `bhkCharacterState`/`hkpCharacterState` anywhere in its hooking code — it hooks `RE::bhkWorld`'s physics-step function directly via a mid-function Xbyak trampoline instead. No serious working Havok-hook plugin uses this project's vtable-hook approach. Scoped follow-on (not attempted): rebuild Precision-style, which needs Xbyak enabled in the build (currently `OFF`) plus a vcpkg dependency and re-verified offsets — a real feature task, not a quick fix. Builds happen on a dedicated Windows machine driven over SSH; this piece still cannot be built or tested on Linux (see `type-importer/DESIGN.md`'s platform-constraints note).

A fourth piece, `LayoutValidator`, closes the loop the other direction: it cross-checks `type-importer`'s static layouts against the *running* game instead of hooking a subsystem. Built, deployed, and live-verified 2026-08-26 — the first real compile found and fixed two genuine bugs (see `runtime-harness/docs/T3-3_LAYOUTVALIDATOR_REPORT.md`), and the resulting three-way diff against `coverage_baseline.json` shows 0 confirmed mismatches on the classes it can check live.

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
| JDK 22+ recommended | Panama FFI (used by the Ghidra extension) | JDK 21's preview FFM mode gives silently wrong struct sizes at full-sweep scale (fine for the small Quick Start example below, but not for a full coverage sweep) — see `generate_gdt.sh`'s own comments and `type-importer/patches/0010-jdk22-ffm-final-api.md`. Temurin works fine either way. |
| Ghidra 12+ | Provides the type-manager Java API this pipeline runs against headlessly | No GUI/project needed |
| A real `libclang.so`, Clang **19+** | MSVC STL's own headers reject older Clang versions | The `libclang-14` that ships with many Linux distros is **not** sufficient — grab a recent LLVM release tarball and point `LD_LIBRARY_PATH` at a directory containing a `libclang.so` symlink to it |
| Windows SDK + MSVC CRT/STL headers | CommonLibSSE-NG's headers need real `<cstdint>` etc. to lay out correctly | Acquire via [`xwin`](https://github.com/Jake-Shadle/xwin): `xwin --accept-license splat --output <dir>` (Microsoft's own license terms apply — don't commit or redistribute the output) |

### Generate a `.gdt` yourself

```bash
cd type-importer/scripts
JAVA_HOME=/path/to/jdk-22 \
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
| v0.1.1 — Extend to more of the class hierarchy | In progress | Full-namespace coverage sweep built and running (see `type-importer/scripts/coverage_report.py`); **2,092 classes byte-accurate**, 39-class hotspot list fully closed (37/39 exact, last 2 given real inferred sizes via patch 0019 rather than left as silent placeholders — `type-importer/COVERAGE_SWEEP_PLAN.md`) |
| v0.1.2 — IDA `.til` output | Not started | `.gdt` path is proven; `.til` export is a separate code path; blocked on IDA access for local verification |
| v0.2 — Other runtimes (SE 1.5.97, AE 1.7.99, VR, GOG) | In progress | SE 1.5.97 and VR 1.4.15 validated layout-wise against their own headers' `static_assert`s (see `type-importer/RUNTIME_SE_1_5_97.md`, `RUNTIME_VR_1_4_15.md`); both wired into CI as a matrix job. AE 1.7.99/GOG share AE 1.6.1170's macro and Address Library ID scheme with no compile-time layout distinction, so they're already covered by the existing AE baseline — no separate sweep needed. Address Library ID cross-check done for SE/AE (see `type-importer/ADDRESS_LIBRARY_VALIDATION.md`): 100% of CommonLibSSE-NG's declared IDs (8,379 SE + 8,702 AE) resolve in real Address Library databases. Remaining: confirming resolved RVAs against a real disassembled binary (needs real game binaries, out of scope per this project's ground rules) |
| v0.3 — CI auto-build on CommonLibSSE-NG releases | In progress | `type-importer` has a CI regression gate (`.github/workflows/type-importer-coverage.yml`, now an AE/SE/VR runtime matrix); `symbol-archive` has a manual-dispatch AE build (`.github/workflows/symbol-archive-build.yml`, with opt-in GitHub Release publishing). Both Linux-native GitHub Actions runners. Automatic rebuild on submodule bump: `.github/dependabot.yml` watches CommonLibSSE-NG weekly and opens a PR on a new upstream commit, which the existing coverage gate then regression-checks automatically (fails the PR check on any regression) — GhidraClangPoweredParse deliberately excluded (patches are pinned against it, needs manual review) |
| v0.4 — AIProcessInspector / runtime-harness plugin | ✅ **Two of three inspectors verified in-game** | Windows build machine online; CommonLibSSE-NG plugin **builds, loads, and runs in-game** against a live Skyrim AE 1.6.1170 process (SKSE64 2.2.6). `AIProcessInspector` hooks `Actor::Update` on both `RE::VTABLE_Actor` and `RE::VTABLE_Character` (live NPCs are `Character` instances with their own vtable) and logs package-evaluation transitions for high-process actors — confirmed against real gameplay — see the committed, lightly redacted log excerpt (`runtime-harness/examples/RuntimeHarness.log.excerpt`) showing a dozen+ distinct live NPCs' packages changing. `SavegameTracer` hooks `BGSSaveLoadManager::ProcessEvent(BSSaveDataEvent)` (a genuine singleton, no multi-vtable trap here) — deployed and confirmed firing live in-game with a real 220-entry `saveGameList`, plus a later quicksave/autosave firing with player name, race, and playtime populated (same excerpt). `HavokStepLogger` hooks `bhkCharacterState::Update` across all six concrete character-state vtables (OnGround/Jumping/InAir/Climbing/Flying/Swimming — none override the base's `Update`, so all six need the hook); vfunc index verified by hand-walking the full inheritance chain (`hkBaseObject`→`hkReferencedObject`→`hkpCharacterState`→`bhkCharacterState`→the six concrete classes). Deployed and installed cleanly, but **produced zero log lines across 70+ minutes of real gameplay** (Helgen intro through open-world Whiterun, including combat-adjacent NPC activity) — long enough to rule out timing. `PlayerCharacter` was checked and ruled out as a separate-hierarchy explanation too. Checked real prior art: `ersh1/Precision` (GPL-3.0, the standard SKSE-community reference for Havok hooking) has zero references to `bhkCharacterState`/`hkpCharacterState` anywhere in its ~2,200-line hooking code — it hooks `RE::bhkWorld`'s physics-step function directly via a mid-function Xbyak trampoline instead of vtable-hooking the state machine. No serious working plugin uses this project's approach. Scoped follow-on, not attempted: rebuild Precision-style (needs Xbyak enabled in the build, currently `OFF`, plus a vcpkg dependency and re-verified offsets). Open question, not confirmed working. |
| v1.0 — Stable release with full documentation | Not started | Community validation; maintainer feedback |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide (issue templates,
PR expectations, patch methodology). Short version: we are not looking for
novel research. We are looking for **reliable engineering**:

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

The goal is that the next person who needs a struct definition finds it in a versioned archive instead of a pinned Discord message.

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

# skyrim-re-toolkit

**Reverse-engineering infrastructure for Skyrim and the Creation Engine.**

[![coverage sweep](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/type-importer-coverage.yml/badge.svg)](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/type-importer-coverage.yml) [![symbol-archive build](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/symbol-archive-build.yml/badge.svg)](https://github.com/ByteBard97/skyrim-re-toolkit/actions/workflows/symbol-archive-build.yml)

Open Ghidra on a stripped `SkyrimSE.exe` and you get `FUN_1401e1270(longlong *param_1, undefined8 param_2)` -- raw offsets, no names. This toolkit turns fifteen years of community reverse-engineering ([CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG), [meh321's Address Library](https://github.com/meh321/AddressLibraryDatabase), SKSE) into **versioned, downloadable Ghidra/IDA type archives** -- so you get `FUN_1401e1270(TESObjectREFR *self)` with real field names instead.

**Who this is for:** RE researchers, SKSE plugin authors, engine-level patchers working in Ghidra or IDA.
**Who this isn't for:** gameplay mods, quests, asset packs -- this is infrastructure other tools build on.

**[→ Browse the docs site](https://bytebard97.github.io/skyrim-re-toolkit/)** for the screenshot-driven version of this page.

## Get the archive

**[→ Download the `gdt-2026-08-29` release](https://github.com/ByteBard97/skyrim-re-toolkit/releases/tag/gdt-2026-08-29)** -- AE/SE/VR `.gdt` files, no build required.

Import into Ghidra: **File → Add Archive** → select the `.gdt` → done.

## The numbers

- **39-class "hotspot list"** (the classes people actually mod against -- `TESForm` hierarchy, `Actor`/`Character`, inventory, quests, Havok): **37/39 exact**, 11 of them cross-checked live against a *running* game.
- **Full sweep, all classes**: AE 2,105/3,181, SE 2,123/3,200, VR 2,124/3,201 byte-accurate against the headers' own `static_assert`s (66% each). The rest is mostly obscure, rarely-modded classes -- tracked openly, not hidden. See [known limitations](https://bytebard97.github.io/skyrim-re-toolkit/known-limitations.html).
- **Every class's status ships inside the archive itself** -- VERIFIED / MISMATCH / EMPTY / UNRESOLVED / UNVERIFIED, stamped into each type's Ghidra description at build time. Confirmed-wrong classes are moved into their own `/NEEDS_VERIFICATION_MISMATCH` category so they're impossible to miss. No separate JSON file to cross-reference by hand.
- **~half of all classes have no `static_assert` to check against at all** (3,087 of 6,268 in the AE sweep) -- those are marked UNVERIFIED, not silently counted as correct.
- **"Byte-accurate" means `sizeof` matches** -- not that every field offset is independently verified. Treat the archive as a strong starting point you can cross-check, not proven ground truth for every struct.

Why this over a pinned Discord `types.h`: not because newer beats older -- a well-used stale file has real value from years of bug-finding. The case for this archive is that it's **versioned and CI-regression-gated**, so an update can't silently get worse, and its accuracy claims are checkable against a committed baseline instead of taken on faith.

## How this compares to BethesdaGhidraScripts

Two related projects deserve credit and an honest feature split:
[doodlum/BethesdaGhidraScripts](https://github.com/doodlum/BethesdaGhidraScripts), which proved the clang-to-Ghidra idea first, and [alandtse/BethesdaGhidraScripts](https://github.com/alandtse/BethesdaGhidraScripts), a heavily extended fork (Skyrim VR, Fallout 4 OG/NG/VR, Starfield, New Vegas, PDB-derived signatures). Their pipeline code is MIT-licensed per the fork's `NOTICE.md`.

**What they do that this project doesn't (yet):**

- **One-shot symbolled project**: named, typed functions at real addresses across the whole binary -- ~32k named functions and ~11k applied signatures on Skyrim AE 1.6.1170 (numbers verified locally on our own run of their fork; this project's own symbols pass covers the same ground at smaller scale so far -- see `type-importer/FUNCTION_SIGNATURE_DESIGN.md`)
- **More games**: Fallout 4 (OG/NG/AE/VR), Starfield, New Vegas pipelines
- **PDB-derived extras**: ~19k internal Bethesda struct layouts and ~19k function signatures mined from a user-supplied `SkyrimSE.pdb`
- **Cross-version machinery**: byte-signature porting between builds, GOG re-keying, VR vtable shift maps with hand-verified anchors
- **Enrichment passes**: string-anchored renaming, constructor mining, globals harvesting

**What this project does that they don't:**

- **Pre-built, versioned archives** -- download a `.gdt`, no toolchain, no build, no exe required for types-only work
- **Correctness gates, not just coverage**: full-sweep `static_assert` layout verification with committed baselines and a zero-regression CI gate; per-type VERIFIED/MISMATCH/EMPTY status stamped into the archive itself; confirmed-wrong types quarantined in `/NEEDS_VERIFICATION_MISMATCH`
- **Three independent verification layers**, including a live-game runtime harness -- theirs self-reports field *typedness* (~99.75%), which is not the same as layout *correctness* (a fully-typed field can still be at the wrong offset)
- **Linux-native end to end** -- their pipeline is Windows-oriented; this project's builds, verification, and demo all run on Linux
- **The rest of the toolkit**: symbol-archive explorer, IDA `.til` export design, docs site

The goal is parity-plus: everything they do, with verification gates on top. The gap list above is the roadmap -- see `type-importer/FUNCTION_SIGNATURE_DESIGN.md` for how the function-signature piece is being closed.

| | This project | BethesdaGhidraScripts (doodlum / alandtse fork) |
|---|---|---|
| Distribution | Pre-built, versioned `.gdt` you download | Run-it-yourself local pipeline |
| Runtimes | AE, SE, VR | Skyrim SE/AE/VR, F4 OG/NG/AE/VR, Starfield, FNV |
| Function signatures / address-library symbols | Yes (new, symbols pass verified locally; vtable-walk pass pending) | Yes (mature, incl. PDB-derived) |
| Accuracy tracking | CI-gated `static_assert` layout sweep, published per release | Self-reported field-typedness + vtable anchor checks |
| Parser patches | 28 fixes, public `.patch` + writeup, not yet upstreamed | N/A |
| Platform | Linux / Windows | Windows-oriented |

The two accuracy approaches aren't measuring the same thing: their percentage is how many struct fields got a concrete type instead of `void *` (typedness); this project's number is how many types pass a `static_assert`-gated check against the real compiled layout (correctness). A field can be fully typed and still be wrong if the layout's off -- different claims, not directly comparable.

The 28 patches aren't hidden -- every one is a `.patch` file plus a root-cause `.md` writeup in `type-importer/patches/`, free for anyone to cherry-pick. Opening them as upstream PRs is real follow-on work (several are invasive and pinned to a specific revision) -- tracked, not avoided on principle.

---

## What's in here

```
skyrim-re-toolkit/
├── type-importer/          # C++ headers → Ghidra / IDA type archives
├── symbol-archive/         # CI-built .gdt releases, AE/SE/VR
└── runtime-harness/        # SKSE plugins for live engine inspection
```

### 1. type-importer

Parses CommonLibSSE-NG headers and emits Ghidra `.gdt` archives (IDA `.til` planned), built on [`GhidraClangPoweredParse`](https://github.com/playday3008/GhidraClangPoweredParse), patched with 28 accepted fixes (see `type-importer/patches/`, full accounting in `COVERAGE_SWEEP_PLAN.md`).

- **Approach:** libclang preprocessing → flattened C-compatible structs → Ghidra's Java type-manager API
- **Handles:** `BSTArray<T>`, `REL::Relocation`, `stl::enumeration`, multiple inheritance, MSVC bitfield packing
- **Verified three independent ways:** the headers' own `static_assert`s, hand-derived offset math, real `clang-cl` compilation
- **CI-gated:** a regression check (`type-importer-coverage.yml`) blocks any patch that would break a previously-correct class
- **Not yet done:** IDA `.til` output (blocked on IDA access), Address Library RVA cross-checks against real binaries (out of scope by design -- no acquiring Bethesda binaries)

Full investigation and root-causes: `type-importer/DESIGN.md`. Try it: [Quick Start](#quick-start) below, or see [`demo/`](demo/README.md) for a real before/after Ghidra screenshot.

### 2. symbol-archive

CI builds pre-built `.gdt` archives per runtime so nobody has to run the pipeline themselves.

| Runtime | Status |
|---|---|
| AE 1.6.1170 | ✅ Built + validated |
| SE 1.5.97 | ✅ Built + validated |
| VR 1.4.15 | ✅ Built + validated |
| AE 1.7.99 / GOG 1.6.1179 | ⚪ Covered by the AE baseline -- verified identical macro/ID scheme, no separate build needed |

Manual-dispatch GitHub Actions workflow, opt-in Release publishing. See `symbol-archive/README.md` for the full accuracy caveat.

### 3. runtime-harness

SKSE plugins that hook under-instrumented engine subsystems and log their internal state live.

| Plugin | Status |
|---|---|
| `AIProcessInspector` | ✅ Verified live -- real package-evaluation transitions logged against a running AE 1.6.1170 process |
| `SavegameTracer` | ✅ Verified live -- fires on real `saveGameList` queries |
| `LayoutValidator` | ✅ Verified live -- cross-checks static layouts against the running game, 0 confirmed mismatches |
| `HavokStepLogger` | ⚪ Known non-working, off by default -- documented negative result, not a WIP feature (see [investigation](runtime-harness/docs/HAVOK_STEP_LOGGER_INVESTIGATION.md)) |

**Bus factor, stated plainly:** these are verified against one physical Windows machine with a live game session. Reproducing them needs a real Windows box, a legal Skyrim copy, and physical display/input hardware. Not yet independently reproduced by a second person -- if you can confirm a single `AIProcessInspector` log line on your own setup, open an issue.

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

**Design principle:** don't reverse-engineer the game from scratch -- instrument, package, and distribute the knowledge the community already produced.

---

## Quick Start

### Just want the `.gdt`? No build required.

1. [Download `gdt-2026-08-29`](https://github.com/ByteBard97/skyrim-re-toolkit/releases/tag/gdt-2026-08-29) (AE/SE/VR).
2. In Ghidra: **File → Import File** (your `SkyrimSE.exe`) → **Window → Data Type Manager → File → Add Archive** → select the `.gdt` → right-click → **Apply Function Data Types**.
3. See [`demo/`](demo/README.md) for a real before/after so you know what to expect.

*(This gives Ghidra the types -- full function-signature retyping across the binary needs RTTI-based class recovery too, out of scope here.)*

### Building the pipeline yourself

```bash
git clone --recurse-submodules https://github.com/ByteBard97/skyrim-re-toolkit.git
```

Requirements (none vendored -- see `type-importer/DESIGN.md`'s toolchain note):

| Requirement | Why |
|---|---|
| JDK 22+ | Panama FFI; JDK 21's preview mode silently mis-sizes structs at scale |
| Ghidra 12+ | Type-manager Java API, headless |
| libclang.so, Clang 19+ | Older versions (e.g. distro `libclang-14`) fail on MSVC STL headers |
| Windows SDK/CRT via [`xwin`](https://github.com/Jake-Shadle/xwin) | Real `<cstdint>` etc. for correct layout |

```bash
cd type-importer/scripts
JAVA_HOME=/path/to/jdk-22 \
GHIDRA_INSTALL_DIR=/path/to/ghidra_12 \
LD_LIBRARY_PATH=/path/to/dir-containing-libclang.so \
  ./generate_gdt.sh /path/to/xwin-splat-dir /tmp/CommonLibSSE_AE.gdt \
  RE/T/TESForm.h RE/T/TESObject.h RE/T/TESBoundObject.h RE/T/TESObjectREFR.h
```

Patches the vendored `GhidraClangPoweredParse` submodule, builds it, runs the parser, writes the `.gdt`, reverts the submodule. `symbol-archive` and `runtime-harness` -- see their sections above; `runtime-harness` requires Windows + Visual Studio + SKSE64 and can't be built on Linux.

---

## Roadmap

| Milestone | Status |
|-----------|--------|
| GDT for `TESForm`→`TESObjectREFR` chain (AE) | ✅ Done, verified |
| Full-namespace coverage sweep | ✅ 2,105 classes byte-accurate, hotspot list closed 37/39 |
| IDA `.til` output | Not started -- blocked on IDA access |
| SE / VR / GOG runtime coverage | ✅ Validated and CI-gated (SE, VR); AE 1.7.99/GOG covered by AE baseline |
| CI auto-build on CommonLibSSE-NG releases | ✅ Dependabot + regression gate wired |
| `runtime-harness` plugins | ✅ 3 verified live, 1 documented non-working |
| Function signatures + address-library symbols | ✅ symbols pass verified locally (phases 1-3, `type-importer/FUNCTION_SIGNATURE_DESIGN.md`); vtable-walk coverage pass next |
| BethesdaGhidraScripts parity (VR function DB, PDB-globals sigs as user-supplied input, enrichment passes, byte-sig porting) | Not started -- see comparison above |
| Stable v1.0 release | Not started -- pending community validation |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide. Short version -- not looking for novel research, looking for **reliable engineering**:

- **type-importer:** libclang, Ghidra's Java API, MSVC ABI quirks
- **symbol-archive:** GitHub Actions, struct-layout validation against live binaries
- **runtime-harness:** SKSE plugins, `AIProcess`, `hkpCharacterProxy`, `BGSSaveLoadManager`

**Ground rules:**
- No console exploits, no distributing DRM-circumvention tools or cracked binaries, no redistribution of game binaries. (Locally unpacking your own legally-purchased executable for static analysis -- see `demo/README.md` -- is standard RE practice and isn't what this targets.)
- All types and offsets must be derivable from public community sources (CommonLibSSE-NG, Address Library, RTTI).

---

## Acknowledgments

A packaging layer around fifteen years of community labor:

- **Ryan-rsm-McKenzie** -- CommonLibSSE (2018)
- **doodlum** -- [BethesdaGhidraScripts](https://github.com/doodlum/BethesdaGhidraScripts), which proved out the clang-to-Ghidra idea first
- **alandtse, 1001Bits** -- the [extended BethesdaGhidraScripts fork](https://github.com/alandtse/BethesdaGhidraScripts) (VR/F4/SF/FNV targets, PDB-derived signatures, vtable shift maps); its pipeline code is MIT-licensed per its `NOTICE.md` and is referenced here as prior art and local reference tooling
- **powerof3, CharmedBaryon, alandtse** -- CommonLibSSE-NG and multi-runtime maintenance
- **meh321** -- Address Library and IDADiffCalculator
- **ianpatt / behippo** -- SKSE
- **DaymareOn** -- SSE-Ghidra-Tutorial and the original "we need tooling" TODO
- **Nukem9, himika, aers, shad0wshayd3** -- engine-level patches and RE findings
- **The xSE RE Discord** -- the knowledge that had no other home until now

## License

MIT. Generated type archives derive from [CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG)'s MIT-licensed headers, attribution intact. The vendored [GhidraClangPoweredParse](https://github.com/playday3008/GhidraClangPoweredParse) extension is Apache-2.0. No BethesdaGhidraScripts code is redistributed here; where that pipeline (MIT per its `NOTICE.md`, copyright BethesdaGhidraScripts contributors) is ever vendored in the future, its copyright and permission notice will be included. No GPL-licensed components (e.g. CommonLibSF) are used.

> No game binaries, PDBs, or copyrighted assets are shipped -- only community-derived facts about memory layout (struct fields, enum values, function signatures).

## Contact

- Issues: [GitHub Issues](https://github.com/ByteBard97/skyrim-re-toolkit/issues)
- Discussion: [GitHub Discussions](https://github.com/ByteBard97/skyrim-re-toolkit/discussions)

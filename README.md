# skyrim-re-toolkit

**Reverse-engineering infrastructure for Skyrim and the Creation Engine.**

This is a collection of tools, type archives, and runtime instrumentation that lowers the friction of Skyrim binary reverse engineering. If you have ever opened Ghidra to a stripped `SkyrimSE.exe` and wondered why you were hand-typing struct definitions that the community already figured out five years ago, this toolkit is for you.

> The Skyrim modding ecosystem has spent fifteen years mapping the Creation Engine. The accumulated knowledge lives in [CommonLibSSE-NG](https://github.com/CharmedBaryon/CommonLibSSE-NG), [meh321's Address Library](https://github.com/meh321/AddressLibraryDatabase), and a handful of pinned Discord attachments. Our goal is to turn that knowledge into versioned, reproducible, public infrastructure.

---

## What's in here

```
skyrim-re-toolkit/
├── type-importer/      # C++ headers → Ghidra / IDA type archives
├── symbol-archive/     # Pre-built .gdt / .til files per game version
└── runtime-harness/    # SKSE plugins for live engine inspection
```

### 1. type-importer

**The problem:** CommonLibSSE-NG contains thousands of reverse-engineered C++ class definitions, struct layouts, vtables, and bitfields. Getting them into Ghidra currently means either (a) hunting for a floating `types.h` file in a Discord server, or (b) manually recreating every struct by hand.

**The solution:** A parser pipeline that reads CommonLibSSE-NG headers and emits Ghidra Data Type Archives (`.gdt`) and IDA Type Libraries (`.til`).

- **Primary approach:** libclang / CastXML preprocessing → flattened C-compatible structs → Ghidra API
- **Fallback approach:** MSVC debug PDB import (when you need the compiler's exact layout)
- **Handles:** `BSTArray<T>`, `REL::Relocation`, `stl::enumeration`, multiple inheritance, MSVC bitfield packing

**Status:** MVP in development. See `type-importer/README.md` for the current parser matrix and known limitations.

### 2. symbol-archive

**The problem:** Every time Bethesda ships a patch, class layouts shift, Address Library format changes (ask anyone who hit `Unsupported address library format: 5` on 1.7.99), and the community's accumulated Ghidra databases become stale. There is no canonical, versioned archive of pre-built type files.

**The solution:** A CI-driven repository that publishes pre-built type archives for every supported Skyrim runtime:

| Game Version | SKSE | Address Library | GDT | TIL |
|-------------|------|----------------|-----|-----|
| SE 1.5.97 | 2.0.20 | v1 | ✅ | ✅ |
| AE 1.6.640 | 2.2.0 | v1 | ✅ | ✅ |
| AE 1.6.1170 | 2.2.6 | v1 | ✅ | ✅ |
| AE 1.7.99 | 2.3.0 | v2 (format 5) | ✅ | ✅ |
| VR 1.4.15 | 2.0.12 | VR | ✅ | ✅ |
| GOG 1.6.1179 | 2.2.6 | v1 | ✅ | ✅ |

**Status:** Automated builds via GitHub Actions. See `symbol-archive/README.md` for download links and load instructions.

### 3. runtime-harness

**The problem:** The Skyrim RE community has excellent static tooling (IDA, Ghidra, BinDiff) and excellent animation introspection (Open Animation Replacer). But the engine's **AI scheduler**, **Havok physics step**, and **savegame serializer** have zero purpose-built runtime visibility. Every finding about them arrives as static RE embedded in patch code.

**The solution:** SKSE plugins that hook into under-instrumented subsystems and log their internal state:

- `AIProcessInspector` — logs package evaluation, reference-handle allocation, and scheduler decisions
- `HavokStepLogger` — captures collision callbacks, ragdoll state transitions, and character proxy data
- `SavegameTracer` — traces `BGSSaveLoadManager` serialization to diagnose bloat and corruption

**Status:** Early prototypes. Windows + MSVC required. See `runtime-harness/README.md` for build instructions.

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

### I just want the pre-built Ghidra types

```bash
# Download the latest GDT for your game version
# See symbol-archive/releases for per-version assets

# In Ghidra:
# File → Import File → (select SkyrimSE.exe)
# Window → Data Type Manager → File → Add Archive
# Select: CommonLibSSE_AE_1.7.99.gdt
# Right-click → Apply Function Data Types
```

### I want to generate types from CommonLibSSE-NG myself

```bash
cd type-importer
pip install -r requirements.txt
python generate_gdt.py   --commonlib /path/to/CommonLibSSE-NG   --runtime AE_1.7.99   --output CommonLibSSE_AE_1.7.99.gdt
```

See `type-importer/docs/PARSER_MATRIX.md` for which constructs are supported and which need manual fixup.

### I want to build the runtime inspection plugins

**Requires:** Windows, Visual Studio 2022, SKSE64 2.3.0, CommonLibSSE-NG

```powershell
cd runtime-harness
# Edit xmake.lua or CMakePresets.json to point at your SKSE + CommonLib paths
xmake f -m release
xmake
# Copy build/*.dll to Data/SKSE/Plugins/
```

---

## Roadmap

| Milestone | Target | Blockers |
|-----------|--------|----------|
| v0.1 — GDT for AE 1.7.99 | 2 weeks | Template flattening for `BSTArray` / `REL::Relocation` |
| v0.2 — CI auto-build on CommonLibSSE-NG releases | 4 weeks | GitHub Actions Windows runner for MSVC debug builds |
| v0.3 — AIProcessInspector plugin | 6 weeks | Validation against live game behavior |
| v0.4 — Cross-game type propagation (Skyrim → Fallout 4 → Starfield) | 3 months | `libxse/commonlib-shared` header unification |
| v1.0 — Stable release with full documentation | 6 months | Community validation; maintainer feedback |

---

## Contributing

We are not looking for novel research. We are looking for **reliable engineering**:

- **Type importer:** If you know libclang, Ghidra's Java API, or MSVC ABI quirks, we need you.
- **Symbol archive:** If you can write GitHub Actions workflows or validate struct layouts against live binaries, we need you.
- **Runtime harness:** If you have built SKSE plugins and know your way around `AIProcess`, `hkpCharacterProxy`, or `BGSSaveLoadManager`, we need you.

See `CONTRIBUTING.md` for the development setup, coding style, and how to submit a PR.

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

Type archives generated from CommonLibSSE-NG inherit the GPL-3.0 license of their source headers. See `symbol-archive/LICENSE-GPL3` for the terms under which pre-built `.gdt` files are distributed.

> **Note:** We do not ship game binaries, PDBs, or copyrighted assets. The symbol archive contains only community-derived type definitions (struct layouts, enum values, function signatures) which are facts about the game's memory layout, not copies of Bethesda's code.

---

## Contact

- Issues: [GitHub Issues](https://github.com/YOURNAME/skyrim-re-toolkit/issues)
- Discussion: [GitHub Discussions](https://github.com/YOURNAME/skyrim-re-toolkit/discussions)
- Real-time: We monitor the Skyrim SE RE and xSE Discord servers (same handles as GitHub)

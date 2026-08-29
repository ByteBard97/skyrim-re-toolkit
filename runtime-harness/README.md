# runtime-harness

**SKSE plugins for live Creation Engine state inspection — the toolkit's
third pillar.**

## Status: three verified live inspectors, one open investigation

The directory contains a real SKSE plugin (`RuntimeHarness`) that builds
against CommonLibSSE-NG, sets up file logging, logs the plugin + running
game version at load, and logs `kDataLoaded`/`kNewGame`/`kPreLoadGame`/
`kPostLoadGame` from the messaging interface. Confirmed running against a
live Skyrim AE 1.6.1170 process (SKSE64 2.2.6).

`AIProcessInspector` and `SavegameTracer` are both confirmed working
against real gameplay. `HavokStepLogger` is a known non-working
investigation, compiled out of the default build — see its entry below.

- `AIProcessInspector` — package evaluation and AI scheduler decisions.
  Hooks `Actor::Update` via vtable (on both `RE::VTABLE_Actor` and
  `RE::VTABLE_Character` — live NPCs are `Character` instances, which
  carry their own vtable array) and logs package-evaluation transitions
  for high-process actors. `RE::PlayerCharacter` has yet another vtable
  and is not covered by design (NPC-only inspector).
- `HavokStepLogger` — **known non-working, off by default.** Attempts to
  hook `bhkCharacterState::Update` for collision/ragdoll state; builds and
  installs cleanly but produced zero log lines across 70+ minutes of real
  gameplay. Compiled out of the default build behind the
  `RTK_ENABLE_HAVOK_STEP_LOGGER` CMake option — a documented negative
  result, not a work-in-progress feature. Full investigation, root-cause
  hypothesis (the standard community reference, `ersh1/Precision`, hooks
  physics differently), and the scoped follow-on path:
  [`docs/HAVOK_STEP_LOGGER_INVESTIGATION.md`](docs/HAVOK_STEP_LOGGER_INVESTIGATION.md).
- `SavegameTracer` — `BGSSaveLoadManager` serialization. Hooks
  `BGSSaveLoadManager::ProcessEvent(const BSSaveDataEvent*)` via vtable
  (index 1 on `RE::VTABLE_BGSSaveLoadManager[0]`) — unlike the other two
  inspectors, `BGSSaveLoadManager` is a genuine singleton
  (`GetSingleton()`), so there's exactly one concrete vtable, no
  Actor/Character-style multi-instance trap here. `BSSaveDataEvent` and
  `BGSSaveLoadManagerEvent` are both only ever forward-declared in the
  vendored tree (never defined), so their payloads can't be read; this
  inspector instead dumps `BGSSaveLoadManager::saveGameList`
  (`BSTArray<BGSSaveLoadFileEntry*>`, which IS fully defined) on every
  `ProcessEvent` firing — filename, player name, race, location, and
  playtime for every known save. Deployed and confirmed firing live
  in-game: `ProcessEvent` fired for real with a real `saveGameList`
  query (list was empty at that moment since no save existed yet in
  that session — itself correct live data, not a bug).

A further idea unlocked by the rest of this repo: a struct-layout
validator that checks `type-importer`'s generated layouts against the
*running* game — stronger ground truth than static_asserts. Built as
`LayoutValidator` (no hooks — a compile-time `sizeof`/`offsetof`
report at plugin load plus live-instance field checks on `kDataLoaded`
and `kNewGame`/`kPostLoadGame`); design and honest limitations in
[`docs/LAYOUT_VALIDATOR.md`](docs/LAYOUT_VALIDATOR.md). **Built,
deployed, and live-verified 2026-08-26** — first real compile found and
fixed two genuine bugs (a wrong build-config assumption in the original
design doc, and a `SKSE::MessagingInterface` listener conflict); the
resulting three-way diff against `coverage_baseline.json` shows 0
confirmed mismatches on the 5 runtime-unguarded classes it can check.
A later pass the same day loaded a real save and closed out
`PlayerCharacter`, `Actor::ACTOR_RUNTIME_DATA`, and `ExtraDataList` live
checks too — all clean on real game state.
Full report: [`docs/T3-3_LAYOUTVALIDATOR_REPORT.md`](docs/T3-3_LAYOUTVALIDATOR_REPORT.md).

## DevBench integration

Instead of building a competing live-control server from scratch (v0.1/v0.2 of
`docs/MCP_SERVER_DESIGN.md`), `RuntimeHarness` exposes its inspector data as
tools on [`alandtse/devbench`](https://github.com/alandtse/devbench) — a
real, actively-maintained SKSE plugin that already hosts an MCP+REST server
with live state reads, save/load, console execution, and a scenario runner.
See `docs/MCP_SERVER_DESIGN.md` v0.3 for the full design decision.

Integration is via devbench's separately MIT-licensed cross-plugin API
(`vendor/devbench/DevBenchAPI.h`/`.cpp`, `DevBenchAPI.LICENSE.txt`) —
devbench's own plugin code is GPL-3.0, never linked; only the MIT glue is
vendored. `src/DevBenchIntegration.cpp` calls `DevBenchAPI::GetDevBenchInterface001()`
on `kPostLoad` (no-ops cleanly if devbench isn't installed) and registers
`runtimeharness.ai_package`, a read-only tool that returns
`AIProcessInspector`'s live formID→package-formID map. **Confirmed compiling
cleanly through MSVC** (VS2022 Build Tools, MSVC 14.44) as part of the
default build — not yet exercised live in-game with devbench actually
installed (that's the remaining, still-open verification step).

## Why this builds against the vendored CommonLibSSE-NG

The plugin compiles against `type-importer/vendor/CommonLibSSE-NG`
(v3.7.0) via `add_subdirectory` — **the exact headers the `.gdt` type
archives are generated from**, so the runtime harness and the type
archives can never disagree about a struct layout.

This is also the pragmatic route: the Color-Glass vcpkg registry that
hosts the `commonlibsse-ng` port is abandoned (last commit 2023-05), and
its port no longer configures against a current vcpkg tree (the first
Windows build attempt failed there). vcpkg is still used, classic-mode,
for the vendored tree's own dependencies (`rapidcsv`, `spdlog` — see
`vcpkg.json`).

## Platform (binding, from the root README)

Windows + MSVC only. SKSE plugins are Windows DLLs against Skyrim's PE
ABI; do not attempt to build or run this on Linux/Proton. Builds happen
on the project's Windows build machine (driven over SSH from the Linux
dev box).

## Building (on Windows)

Prerequisites:

- Visual Studio 2022 Build Tools, "Desktop development with C++" workload
  (v143 toolset; CommonLibSSE-NG needs C++23)
- CMake 3.21+
- [vcpkg](https://github.com/microsoft/vcpkg) at `C:\vcpkg` (or pass
  `-VcpkgRoot`)
- **A full clone of this repo with submodules**
  (`git clone --recursive ...`) — the build references
  `../type-importer/vendor/CommonLibSSE-NG` relative to this directory,
  so a copied-out `runtime-harness/` folder alone will not configure
  (override with `-DRUNTIME_HARNESS_COMMONLIB_PATH=...` if you must).

```powershell
cd runtime-harness
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The first configure builds CommonLibSSE-NG itself plus its vcpkg
dependencies (expect several minutes). The plugin DLL lands under
`build\Release\`.

### How the SKSE plugin declaration works (no registry helper)

The vcpkg port's `add_commonlibsse_plugin()` CMake helper isn't available
when building the library by `add_subdirectory`, so the plugin exports
its version data from source instead: the `SKSEPluginInfo(...)` block in
`src/main.cpp` expands (per the vendored `SKSE/Interfaces.h:685`) to an
exported `SKSEPlugin_Version` — the `PluginDeclaration`/version-data
block AE-era SKSE loads plugins by — plus an `SKSEPlugin_Query` for
pre-AE runtimes. See the citations in `src/main.cpp`.

## Testing

Requires a Skyrim AE install with SKSE64 on the Windows machine: copy
`RuntimeHarness.dll` into `Data/SKSE/Plugins/`, launch via `skse64_loader`,
then check `Documents/My Games/Skyrim Special Edition/SKSE/RuntimeHarness.log`.
Also requires an Address Library `.bin` file matching the exact game
build (`Data/SKSE/Plugins/versionlib-<version>.bin`) — SKSE64 silently
disables plugins declaring `VersionIndependence::AddressLibrary` without
one ("address library needs to be updated" in `skse64.log`).

Confirmed working end to end against a live Skyrim AE 1.6.1170 install
with SKSE64 2.2.6: `AIProcessInspector` logged real, changing
package-evaluation data for a dozen-plus NPCs, and `SavegameTracer`
logged a real `ProcessEvent(BSSaveDataEvent)` firing with a live
`saveGameList` query. See
[`examples/RuntimeHarness.log.excerpt`](examples/RuntimeHarness.log.excerpt)
for real (lightly redacted) log output backing both claims, not just a
description of what they do. Getting there required starting a **new game**,
not loading one of the pre-existing saves on that box — those are
several years old and reference mod plugins not present on this
vanilla-plus-SKSE install, and crash on load with missing masters.

This box has no monitor/keyboard/mouse attached by default, so the game
window doesn't render or accept input at all until real display/input
hardware is physically connected — confirmed both ways: with nothing
attached, the game window stays solid black and doesn't respond to any
synthetic input (`SendInput`/`keybd_event`) sent over SSH regardless of
window-focus state; once real hardware was physically connected, the
exact same synthetic-input approach started working correctly (focus
verified before/after each keystroke, menu navigation succeeded). If
retesting on this box, confirm a display/keyboard/mouse are physically
attached first.

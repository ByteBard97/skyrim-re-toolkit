# runtime-harness

**SKSE plugins for live Creation Engine state inspection — the toolkit's
third pillar.**

## Status: two of three inspectors verified in-game

The directory contains a real SKSE plugin (`RuntimeHarness`) that builds
against CommonLibSSE-NG, sets up file logging, logs the plugin + running
game version at load, and logs `kDataLoaded`/`kNewGame`/`kPreLoadGame`/
`kPostLoadGame` from the messaging interface. Confirmed running against a
live Skyrim AE 1.6.1170 process (SKSE64 2.2.6).

`AIProcessInspector` and `SavegameTracer` are both confirmed working
against real gameplay. `HavokStepLogger` is deployed but has not yet
produced any log output — see its entry below.

- `AIProcessInspector` — package evaluation and AI scheduler decisions.
  Hooks `Actor::Update` via vtable (on both `RE::VTABLE_Actor` and
  `RE::VTABLE_Character` — live NPCs are `Character` instances, which
  carry their own vtable array) and logs package-evaluation transitions
  for high-process actors. `RE::PlayerCharacter` has yet another vtable
  and is not covered by design (NPC-only inspector).
- `HavokStepLogger` — collision/ragdoll state per physics step. Hooks
  `bhkCharacterState::Update` (vfunc index 6) on all six concrete
  character-state vtables (`OnGround`/`Jumping`/`InAir`/`Climbing`/
  `Flying`/`Swimming` — the abstract `bhkCharacterState`/
  `hkpCharacterState` bases are never instantiated and none of the six
  override `Update`, so every one needs the hook) and logs physics-state
  transitions with velocity magnitude. Not yet actor-attributed: this
  hook's signature carries no direct pointer back to the owning `Actor`
  or `bhkCharacterController`, so log lines are keyed by the
  `hkpCharacterContext` instance address rather than a form ID. The
  vfunc index (6) was verified by hand-walking the full inheritance
  chain (`hkBaseObject`→`hkReferencedObject`→`hkpCharacterState`→
  `bhkCharacterState`→the six concrete classes), so it's very unlikely
  to be an indexing bug. Deployed and installed cleanly in-game, but
  **produced zero log lines across 70+ minutes of real gameplay**
  spanning the Helgen opening, open-world Whiterun, and combat-adjacent
  NPC activity — long enough that "still in the scripted intro" no
  longer explains it. `PlayerCharacter` was checked and ruled out as a
  separate-hierarchy explanation (its header has no character-controller
  references at all, and `AIProcess::GetCharController()`'s actual
  implementation returns a plain `bhkCharacterController*` with no
  player/NPC branching). Checked real prior art: [ersh1/Precision](https://github.com/ersh1/Precision)
  (GPL-3.0), the standard reference for Havok hooking in the SKSE
  community (melee/projectile collision, hundreds of thousands of
  downloads, built on CommonLibSSE-NG), has **zero references to
  `bhkCharacterState`/`hkpCharacterState`/`CharacterState` anywhere** in
  its ~2,200-line hooking code. It doesn't vtable-hook the state
  machine's `Update` at all -- it hooks `RE::bhkWorld`'s physics-step
  function directly, via a genuine mid-function trampoline (Xbyak-built
  code cave, `SKSE::Trampoline::write_branch<6>` patched at a specific
  byte offset *inside* a larger function, at a `RELOCATION_ID` +
  disassembly-derived offset that mod's author published). No serious
  working Havok-hook plugin uses this project's vtable-hook approach on
  `bhkCharacterState`, which is a much sharper finding than "unverified."
  **Scoped follow-on path, not attempted here:** rebuild
  `HavokStepLogger` Precision-style -- hook `bhkWorld`'s step function
  instead, which needs Xbyak enabled in this project's build (currently
  `OFF` in `type-importer/vendor/CommonLibSSE-NG/CMakeLists.txt`, plus a
  vcpkg dependency), and Precision's published offsets re-verified
  against this project's exact 1.6.1170 build before trusting them. This
  is a real, deliberate feature task, not a quick fix. **Current vtable
  hook: open question, not a known-good hook.**
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
*running* game — stronger ground truth than static_asserts. Skeletoned
as `LayoutValidator` (no hooks — a compile-time `sizeof`/`offsetof`
report at plugin load plus a live-instance field check on
`kDataLoaded`); design and honest limitations in
[`docs/LAYOUT_VALIDATOR.md`](docs/LAYOUT_VALIDATOR.md). **Not yet built
or run.**

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

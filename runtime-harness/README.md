# runtime-harness

**SKSE plugins for live Creation Engine state inspection — the toolkit's
third pillar.**

## Status: first inspector working, verified in-game

The directory contains a real SKSE plugin (`RuntimeHarness`) that builds
against CommonLibSSE-NG, sets up file logging, logs the plugin + running
game version at load, and logs `kDataLoaded`/`kNewGame`/`kPreLoadGame`/
`kPostLoadGame` from the messaging interface. Confirmed running against a
live Skyrim AE 1.6.1170 process (SKSE64 2.2.6).

`AIProcessInspector` (below) is confirmed working against real gameplay:
`RuntimeHarness.log` shows a dozen-plus live NPCs' package-evaluation
transitions during a fresh game's opening scene, changing over time as
expected. `HavokStepLogger` is written and compile-verified but not yet
deployed/verified in-game. `SavegameTracer` is still unstarted:

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
  `hkpCharacterContext` instance address rather than a form ID. Written
  and compile-verified, **not yet deployed or run in-game**.
- `SavegameTracer` — `BGSSaveLoadManager` serialization

A further idea unlocked by the rest of this repo: a struct-layout
validator that checks `type-importer`'s generated layouts against the
*running* game — stronger ground truth than static_asserts.

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
package-evaluation data for a dozen-plus NPCs during a fresh game's
opening cart scene. Getting there required starting a **new game**, not
loading one of the pre-existing saves on that box — those are several
years old and reference mod plugins not present on this vanilla-plus-SKSE
install, and crash on load with missing masters.

Also note: this box has no monitor/keyboard/mouse attached by default, so
the game window doesn't render or accept input until real display/input
hardware is physically connected — synthetic input (SendInput/keybd_event)
into the game window over SSH does not work and was abandoned as both
ineffective and risky to attempt on a box in active use.

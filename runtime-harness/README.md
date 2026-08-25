# runtime-harness

**SKSE plugins for live Creation Engine state inspection — the toolkit's
third pillar.**

## Status: skeleton, first Windows build in progress

The directory contains a minimal, real SKSE plugin (`RuntimeHarness`)
that builds against CommonLibSSE-NG and does exactly three things: sets up
file logging, logs the plugin + running game version at load, and logs
`kDataLoaded` from the messaging interface. Its only purpose is to prove
the Windows/MSVC toolchain end to end before any real inspector is
written on top.

Nothing here hooks anything yet. The planned inspectors (unchanged):

- `AIProcessInspector` — package evaluation and AI scheduler decisions
- `HavokStepLogger` — collision/ragdoll state per physics step
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
Not yet exercised — the Windows box currently has no Skyrim install.

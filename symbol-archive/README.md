# symbol-archive

**CI-driven builds of `.gdt` type archives for Skyrim runtimes, generated
from `type-importer`'s pipeline.**

## Status: early scaffold, AE only

This subproject wraps `type-importer/scripts/generate_gdt.sh` in a GitHub
Actions workflow (`.github/workflows/symbol-archive-build.yml`) that runs
a full sweep of `CommonLibSSE-NG/include/RE/` and publishes the resulting
`.gdt` as a workflow build artifact.

- **Runtime coverage**: this workflow builds AE only (`ENABLE_SKYRIM_AE=1`).
  `type-importer` itself has since validated SE 1.5.97 and VR 1.4.15
  layouts too (CI-gated there); wiring SE/VR builds into this workflow is
  still not started. AE 1.7.99/GOG need no separate build — they share AE
  1.6.1170's macro and Address Library ID scheme.
- **Distribution**: a workflow artifact attached to each run by default;
  the workflow now also supports opt-in publishing to a versioned GitHub
  Release (see `.github/workflows/symbol-archive-build.yml`'s
  `publish_release` input) — not yet exercised for a real public release.
- **Accuracy**: **not every class in this archive is byte-accurate.**
  `type-importer`'s own coverage sweep (see
  `../type-importer/COVERAGE_SWEEP_PLAN.md` and
  `../type-importer/coverage_baseline.json`) tracks this precisely — as
  of the last full sweep, 1,934 of 3,019 checkable classes (64%) resolve
  byte-accurate; the rest are either a wrong size or resolve empty.
  A curated **hotspot list** of 39 commonly-modded classes (`TESForm`
  hierarchy, `Actor`/`Character`/`PlayerCharacter`, inventory, item
  types, quests/packages, Havok, etc.) is tracked separately in
  `../type-importer/COVERAGE_SWEEP_PLAN.md` and is a much stronger
  accuracy signal than the archive's raw class count — 37/39 are exact,
  with the remaining 2 root-caused and documented rather than silently
  wrong. **Still don't treat every struct in this archive as trustworthy
  without cross-checking against a real `static_assert` or independent
  verification** outside the hotspot list — that remains true until
  `type-importer`'s overall pass rate is much higher.

## How the build works

1. `scripts/list_re_headers.sh` (from `type-importer`) enumerates every
   `RE/*.h` header (minus `RE/Skyrim.h`, CommonLibSSE-NG's own umbrella
   header, which pulls a real SKSE PCH that collides with
   `type-importer`'s layout-only stub — see `type-importer/DESIGN.md`).
2. `type-importer/scripts/generate_gdt.sh` patches the vendored
   `GhidraClangPoweredParse` extension (patches 0001-0006, see
   `type-importer/patches/`), builds it, and runs the patched parser
   against that full header list with `ENABLE_SKYRIM_AE=1`.
3. The resulting `.gdt` is uploaded as a build artifact, named
   `CommonLibSSE_AE_<commonlibssng-commit-sha>.gdt` so it's traceable
   back to the exact CommonLibSSE-NG submodule revision it was built
   from.

## Triggers

- Manual dispatch (`workflow_dispatch`) — the only way to build one right
  now. Push-triggered builds tied to CommonLibSSE-NG submodule updates
  are natural future work once `type-importer`'s pass rate is higher
  (rebuilding on every submodule bump isn't worth the CI minutes yet
  given how much of the sweep is still wrong).

## Using the archive

Same as `type-importer`'s own Quick Start: **File → Import File** your
target `SkyrimSE.exe` in Ghidra, then **Window → Data Type Manager →
File → Add Archive** and select the downloaded `.gdt`, then right-click →
**Apply Function Data Types**.

## Roadmap

| Milestone | Status |
|---|---|
| AE `.gdt` build artifact via manual CI dispatch | Done |
| Hotspot-list accuracy verified | 37/39 exact — see `type-importer/COVERAGE_SWEEP_PLAN.md` |
| Versioned GitHub Release publishing | Wired (opt-in `publish_release` input); not yet exercised for a real release |
| SE / VR / GOG runtime coverage | Layouts validated in `type-importer` (SE, VR) and confirmed unnecessary (AE 1.7.99, GOG); wiring SE/VR builds into this workflow not started |
| Automatic rebuild on CommonLibSSE-NG submodule bump | Not started — blocked on higher sweep pass rate |

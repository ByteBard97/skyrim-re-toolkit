# symbol-archive

**CI-driven builds of `.gdt` type archives for Skyrim runtimes, generated
from `type-importer`'s pipeline.**

## Status: early scaffold, AE only

This subproject wraps `type-importer/scripts/generate_gdt.sh` in a GitHub
Actions workflow (`.github/workflows/symbol-archive-build.yml`) that runs
a full sweep of `CommonLibSSE-NG/include/RE/` and publishes the resulting
`.gdt` as a workflow build artifact.

- **Runtime coverage**: AE only (`ENABLE_SKYRIM_AE=1`), matching
  everything else built so far. SE, VR, and GOG are explicit future work
  — not started.
- **Distribution**: a workflow artifact attached to each run, not yet a
  versioned GitHub Release. See `type-importer/LOOP_GOAL.md` — a release
  process was explicitly scoped as a stretch goal, not required for this
  round.
- **Accuracy**: **not every class in this archive is byte-accurate.**
  `type-importer`'s own coverage sweep (see
  `../type-importer/COVERAGE_SWEEP_PLAN.md`) tracks this precisely — as
  of the last full sweep, roughly 44% of classes with a known-correct
  size (`static_assert`-verified against real CommonLibSSE-NG source)
  resolve correctly; the rest are either a wrong size or resolve empty.
  A curated **hotspot list** of commonly-modded classes (`TESForm`
  hierarchy, `Actor`/`Character`/`PlayerCharacter`, inventory, item
  types, quests/packages, etc. — see `LOOP_GOAL.md` for the full list) is
  tracked separately and is a much stronger accuracy signal than the
  archive's raw class count. **Do not treat every struct in this archive
  as trustworthy without cross-checking against a real `static_assert`
  or independent verification** — this is true of any single sweep of a
  parser this young, and will remain true until `type-importer`'s
  coverage sweep shows a much higher pass rate.

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
| AE `.gdt` build artifact via manual CI dispatch | Done (this round) |
| Hotspot-list accuracy verified | See `type-importer/COVERAGE_SWEEP_PLAN.md` |
| Versioned GitHub Release publishing | Not started (stretch goal) |
| SE / VR / GOG runtime coverage | Not started |
| Automatic rebuild on CommonLibSSE-NG submodule bump | Not started — blocked on higher sweep pass rate |

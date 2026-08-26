# symbol-archive

**CI-driven builds of `.gdt` type archives for Skyrim runtimes, generated
from `type-importer`'s pipeline.**

## Status: early scaffold, AE/SE/VR matrix live-verified

This subproject wraps `type-importer/scripts/generate_gdt.sh` in a GitHub
Actions workflow (`.github/workflows/symbol-archive-build.yml`) that runs
a full sweep of `CommonLibSSE-NG/include/RE/` per runtime and publishes
each resulting `.gdt` as a workflow build artifact.

- **Runtime coverage**: the workflow matrix-builds **AE, SE, and VR**
  (`ENABLE_SKYRIM_AE`/`ENABLE_SKYRIM_SE`/`ENABLE_SKYRIM_VR`), mirroring
  `type-importer-coverage.yml`'s own runtime matrix now that Track 1 has
  validated SE 1.5.97 and VR 1.4.15 layouts. AE 1.7.99/GOG need no
  separate build entry — they share AE 1.6.1170's macro and Address
  Library ID scheme. **Confirmed with a real `workflow_dispatch` run**
  (all three matrix legs completed successfully, real `.gdt` artifacts
  produced — ~3.7MB each, traceable to CommonLibSSE-NG commit `b93280e`)
  — no longer just YAML-validated.
- **Distribution**: a workflow artifact attached to each run by default;
  the workflow now also supports opt-in publishing to a single versioned
  GitHub Release carrying all three runtimes (see
  `.github/workflows/symbol-archive-build.yml`'s
  `publish_release`/`release_version` inputs, e.g. version `v1` produces
  tag `gdt-v1` with the AE/SE/VR `.gdt` files attached as assets) —
  never yet published.
- **Accuracy**: **not every class in this archive is byte-accurate.**
  `type-importer`'s own coverage sweep (see
  `../type-importer/COVERAGE_SWEEP_PLAN.md` and
  `../type-importer/coverage_baseline.json`) tracks this precisely — as
  of the last full sweep, 2,064 of 3,017 checkable classes (68%) resolve
  byte-accurate; the rest are either a wrong size or resolve empty.
  A curated **hotspot list** of 39 commonly-modded classes (`TESForm`
  hierarchy, `Actor`/`Character`/`PlayerCharacter`, inventory, item
  types, quests/packages, Havok, etc.) is tracked separately in
  `../type-importer/COVERAGE_SWEEP_PLAN.md` and is a much stronger
  accuracy signal than the archive's raw class count — the list is now
  fully closed: 37/39 are exact, and the remaining 2 have real inferred
  sizes (patch 0019) rather than silent 1-byte placeholders. **Still
  don't treat every struct in this archive as trustworthy
  without cross-checking against a real `static_assert` or independent
  verification** outside the hotspot list — that remains true until
  `type-importer`'s overall pass rate is much higher.

**What this buys you, visually**: see [`../demo/screenshots/ghidra_typed_decompile.png`](../demo/README.md) — a real screenshot of a `.gdt` from this same pipeline applied to a real `SkyrimSE.exe` in Ghidra, showing typed field access (`self->super_TESForm.formFlags`) instead of raw offsets.

## How the build works

1. `scripts/list_re_headers.sh` (from `type-importer`) enumerates every
   `RE/*.h` header (minus `RE/Skyrim.h`, CommonLibSSE-NG's own umbrella
   header, which pulls a real SKSE PCH that collides with
   `type-importer`'s layout-only stub — see `type-importer/DESIGN.md`).
2. `type-importer/scripts/generate_gdt.sh` patches the vendored
   `GhidraClangPoweredParse` extension (patches 0001-0019, 0021-0024, see
   `type-importer/patches/`), builds it, and runs the patched parser
   against that full header list once per matrix runtime (currently
   `ENABLE_SKYRIM_AE`, `ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_VR`).
3. Each resulting `.gdt` is uploaded as a build artifact, named
   `CommonLibSSE_<runtime>_<commonlibssng-commit-sha>.gdt` so it's
   traceable back to the exact CommonLibSSE-NG submodule revision it was
   built from.

## Triggers

- Manual dispatch (`workflow_dispatch`) — the only way to build (any
  runtime in the matrix) right now. Push-triggered builds tied to
  CommonLibSSE-NG submodule updates are natural future work once
  `type-importer`'s pass rate is higher (rebuilding on every submodule
  bump isn't worth the CI minutes yet given how much of the sweep is
  still wrong) — note this is distinct from `.github/dependabot.yml`,
  which already automatically opens a PR and regression-checks
  `type-importer`'s own coverage on a CommonLibSSE-NG bump; it does not
  trigger this workflow's `.gdt` rebuild.

## Using the archive

Same as `type-importer`'s own Quick Start: **File → Import File** your
target `SkyrimSE.exe` in Ghidra, then **Window → Data Type Manager →
File → Add Archive** and select the downloaded `.gdt`, then right-click →
**Apply Function Data Types**.

## Roadmap

| Milestone | Status |
|---|---|
| AE `.gdt` build artifact via manual CI dispatch | Done — real run confirmed (see Status above) |
| Hotspot-list accuracy verified | Fully closed — 37/39 exact, last 2 given real inferred sizes via patch 0019 — see `type-importer/COVERAGE_SWEEP_PLAN.md` |
| Versioned GitHub Release publishing | Wired, gated behind the `publish_release` dispatch input (single `gdt-<release_version>` release carrying all three AE/SE/VR `.gdt` assets); never yet published |
| SE / VR / GOG runtime coverage | Layouts validated in `type-importer` (SE, VR) and confirmed unnecessary (AE 1.7.99, GOG); SE/VR wired into this workflow's build matrix and confirmed with a real run — see Status above |
| Automatic *validation* on CommonLibSSE-NG submodule bump | Done — `.github/dependabot.yml` watches CommonLibSSE-NG weekly and opens a PR on a new upstream commit, which `type-importer`'s existing coverage gate then regression-checks automatically. This subproject's own `.gdt` rebuild is still manual-dispatch only (see Triggers below) — Dependabot doesn't push a new `.gdt` build artifact, only a reviewed, regression-checked PR bumping the pin |

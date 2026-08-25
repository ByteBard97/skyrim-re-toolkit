# v0.2 — Skyrim SE 1.5.97 runtime validation

First runtime beyond AE 1.6.1170 validated end-to-end, following the same
self-checking methodology as the AE coverage sweep (headers' own
`static_assert`s as ground truth — no Address Library data needed for this
first pass, since CommonLibSSE-NG's SE-guarded `static_assert`s are
sufficient to confirm the parser resolves the SE-specific layout branches
correctly).

## What changed

The pipeline was already runtime-agnostic in principle (`tools/GenerateGdt.java`
took `--runtime <MACRO>=1` as a CLI arg from day one) but two pieces were
hardcoded to AE:

- `scripts/generate_gdt.sh` always passed `--runtime ENABLE_SKYRIM_AE=1` to
  `GenerateGdt`. Now reads `RUNTIME_DEFINE` (default unchanged:
  `ENABLE_SKYRIM_AE=1`).
- `scripts/mine_static_asserts.py` (the ground-truth miner) hardcoded
  `TARGET_DEFINED = {"ENABLE_SKYRIM_AE"}`. Now takes `--runtime
  ENABLE_SKYRIM_AE|ENABLE_SKYRIM_SE|ENABLE_SKYRIM_VR` (default unchanged: AE).

No changes to the vendored `GhidraClangPoweredParse` patches or `stubs/` were
needed — the existing stub's `RelocateMember` hardcoding the AE offset is
still correct for SE (it's a reference into existing storage, adds no bytes
regardless of runtime; see the comment in `stubs/layout_pch.h`).

## Verification: full 1630-header sweep, `RUNTIME_DEFINE=ENABLE_SKYRIM_SE=1`

Ground truth: `mine_static_asserts.py --runtime ENABLE_SKYRIM_SE` finds 2168
SE-applicable `static_assert(sizeof(...))`s. Diffing against the AE-applicable
set (2149 entries): **all 2149 AE-applicable asserts have an identical-value
SE-applicable counterpart** (the vast majority of layouts are
runtime-invariant, and no class asserts a *different* size under the two
runtimes); the other **19 SE-applicable asserts have no AE-applicable
counterpart at all** (AE simply has no `static_assert` for these classes —
their layout depends on `REL::RelocateMember`/`#ifndef ENABLE_SKYRIM_AE`
branches that are compiled out, not compared, under AE:
`TESObjectREFR`, `Actor`, `Character`, `PlayerCharacter`, `Projectile` and its
subclasses, `TESObjectCELL`, `Explosion`, `Hazard`, `BSAnimationGraphManager`,
`BSAnimationGraphVariableCache`, `Inventory3DManager`). That 19 is the honest
scope of "SE-specific" in this codebase; the bucket totals below cover the
full sweep (mostly re-confirming runtime-invariant classes, which is
expected and still real signal that the SE `-D` reaches the parse correctly
end-to-end).

Confirmed the runtime switch actually reaches libclang's layout (not just a
relabeled AE run): `TESObjectREFR` resolves to `0x98` (152) under
`ENABLE_SKYRIM_SE=1`, matching its `#ifndef ENABLE_SKYRIM_AE` static_assert
exactly, vs. `0x70` (112) resolved under the AE run.

Bucket totals (3817 tracked classes, same scale as the committed AE
`coverage_baseline.json` for comparison):

| Status | AE (committed baseline) | SE (this sweep) |
|---|---|---|
| OK | 1934 | 1951 |
| EMPTY | 880 | 878 |
| NO_GROUND_TRUTH | 798 | 781 |
| MISMATCH | 178 | 180 |
| UNRESOLVED | 27 | 27 |

Of the 19 SE-only-asserted classes: **16 resolve byte-accurate
under SE** (all the `Actor`/`Character`/`Projectile`-family and
`TESObjectREFR`/`TESObjectCELL`/`Explosion`/`Hazard`/
`BSAnimationGraphVariableCache` classes), 2 `MISMATCH`
(`BSAnimationGraphManager`, `Inventory3DManager` — pre-existing parser gaps,
not SE-specific regressions), and 1 `NO_GROUND_TRUTH`
(`ExtraDataList` — no SE-applicable assert exists for it either).

**Bonus finding:** `BaseExtraList` — one of the two classes permanently
deferred for AE (`COVERAGE_SWEEP_PLAN.md`'s "BaseExtraList / ExtraDataList"
section; AE's real members are accessed via a `REL::RelocateMember`-style
runtime trick, not compiled struct members, so AE has no
`static_assert` for it and the parser correctly emits `sizeof==1`) —
resolves **byte-accurate under SE** (`sizeof(BaseExtraList) == 16`, matching
SE's own `static_assert`). This confirms DESIGN.md's diagnosis that the
AE gap is a genuine AE-only accessor-pattern limitation, not a general
parser bug: under SE, `BaseExtraList`'s real members are compiled directly
(no runtime accessor trick), so the existing parser handles them with zero
SE-specific work.

Output artifacts: `/tmp/CommonLibSSE_SE.gdt` (2,892,611 bytes, 25743 types
committed, 0 failed), full snapshot saved as `coverage_baseline_se.json`
(same schema as `coverage_baseline.json`, not yet wired into CI — see
"Not done" below).

## Not done (follow-up, not blocking this milestone)

- No CI job for the SE runtime yet (`.github/workflows/type-importer-coverage.yml`
  still gates AE only). `check_regression.py` works unmodified against
  `coverage_baseline_se.json` for local verification of future SE-targeted
  patches; wiring a second CI job is a small follow-up, not attempted here.
- No cross-check against real SE 1.5.97 Address Library offsets — this pass
  validates class *layout* (sizes/fields) against the headers' own
  static_asserts, not runtime *addresses*. Address Library cross-checking
  (per the original v0.2 milestone description) is future work.
- AE 1.7.99, VR, and GOG runtimes not attempted — same mechanism
  (`RUNTIME_DEFINE=ENABLE_SKYRIM_VR=1` / a version-specific header set)
  should apply, not verified here.

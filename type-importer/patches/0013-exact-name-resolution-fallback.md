# Patch 0013: exact-name DTM resolution fallback with category preference

## The problem (continuation of 0012's runner-only investigation)

Patch 0012's tolerance fix did not cure the runner-only
`BGSDirectionalAmbientLightingColors` cascade. The runner clang probe
(`scripts/nested_probe.c`, run 32790925908) then EXONERATED libclang on
the runner: identical decl kinds, visitFields results, sizes, and
diagnostics as locally under the deterministic C-order umbrella. So the
divergence is in the Java layer on the runner only.

A dependency-blocker trace on the runner (`GCPP_DEBUG_DEPS=Directional`
via the coverage workflow's new dispatch input, run 32791338691) named
the actual blocker:

    [DEPS] 'BGSDirectionalAmbientLightingColors' blocked by 'Color'

`Color` — a plain, top-level RE class — fails to resolve on the runner.
`resolveType` had exactly one lookup path for plain names: Ghidra's
`DataTypeParser.parse(name)`, which can fail or go ambiguous when
multiple same-named types exist across DTM categories (the WinSDK splat
contributes same-named types, and the runner's DTM population can differ
from a dev machine's). Everything embedding `Color` then cascaded:
`Directional`'s MaxMin embeds composed empty -> EMPTY(1) -> parent
MISMATCH -> `BGSLightingTemplate`/`INTERIOR_DATA`/`TESWeather` wrong.

## The fix

`resolveType` gains an exact-name fallback for ALL names (extending
0011's `::`-only fallback): `dtm.findDataTypes(name)` and, when several
categories collide, prefer the candidate whose CategoryPath matches the
pool's own parsed entry for that name (e.g. RE::Color's category beats a
Windows-SDK type of the same name). Also upgrades the `GCPP_DEBUG_DEPS`
trace to print exact-name candidate counts/categories and the parsed
entry, so any future divergence self-diagnoses in one CI dispatch.

## Verification

- Local full sweep: byte-identical to the committed baseline
  (0 regressions, 0 improvements) — pure robustness, no value change
  where resolution already worked.
- Runner validation: see the CI run for the commit adding this patch.

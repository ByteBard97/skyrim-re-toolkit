# Patch 0012: tolerate a missing declaration cursor for template-specialization fields

## The problem (GitHub-runner-only divergence)

The first two hosted runs of the coverage workflow disagreed with local
runs on exactly one cascade: `BGSDirectionalAmbientLightingColors::
Directional` came back EMPTY on the runner (OK locally), dragging
`BGSDirectionalAmbientLightingColors`, `BGSLightingTemplate`,
`INTERIOR_DATA`, and `TESWeather` with it.

Systematically ruled out with byte-identical inputs (CI's uploaded
snapshot diffed against local runs):

- **Header order**: `list_re_headers.sh` sorted with the machine locale
  (`en_US.UTF-8` desktop vs `C` runner produce different orders) — fixed
  to `LC_ALL=C sort` in this patch's commit; a local sweep under the
  runner's exact order still did NOT reproduce the divergence.
- **Locale**: a full local sweep with `LC_ALL=C LANG=C` for the whole
  pipeline — no change.
- **Same-machine nondeterminism**: two identical local sweeps are
  byte-identical (so not ASLR/hash-order flakiness).
- **The parse itself**: identical clang diagnostics (1142 errors /
  1158 diagnostics) on both machines — same AST inputs.

What actually differs on the runner: `clang_getTypeDeclaration` does not
return a record cursor for a member template of a nested class
(`Directional`'s `MaxMin<Color>`), so `parseStruct`/`parseUnion`'s
inline-embed gate (`declKind == STRUCT_DECL || CLASS_DECL`) falls
through, the field becomes a named dependency (`MaxMin<Color>`) that can
never resolve, and the whole enclosing struct zeroes out. Suspected
glibc/allocator-sensitive iteration inside libclang itself (Pop!_OS
22.04 / glibc 2.35 vs ubuntu-latest's newer glibc); not reproducible
locally by any controllable variable.

## The fix

`parseFieldsFromType` never needed the declaration cursor — it works off
the TYPE (`clang_Type_visitFields` + `clang_Type_getSizeOf` opaque
fallback). When the decl-kind gate fails for a `<`-spelled RECORD/
UNEXPOSED field, attempt the type-based embed anyway and use it if it
recovered anything; keep the legacy named-dependency path only when the
attempt comes back truly empty. Applied to both `parseStruct` and
`parseUnion` branches.

## Verification

- Local full sweep: zero regressions, one improvement
  (`hkpConstraintInstance` MISMATCH -> OK, an effect of the now-
  deterministic C-locale header order that CI had already seen) — locked
  into the baseline with this patch.
- The runner-side effect can only be validated on the runner itself: see
  the CI run for the commit that added this patch.

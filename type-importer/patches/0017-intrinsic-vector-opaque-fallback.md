# Patch 0017 — opaque fallback for SSE/AVX intrinsic vector types

## Root cause

Follow-up to patch 0016's own "new deferred finding": `RE::hkVector4`
(`RE/H/hkVector4.h`) is a real, non-template class whose one member is
`hkQuadReal quad;`, where `hkQuadReal` is `using hkQuadReal = __m128;`
(`RE/H/hkSseMathTypes.h`) — a compiler-builtin SSE vector type.

Clang parses `__m128` (and its `__m128i`/`__m128d`/`__m128h`/`__m128bh`/
`__m256*`/`__m512*` siblings) as a genuine `TYPEDEF_DECL`/
`TYPE_ALIAS_DECL` cursor, so `SourceParser.parseTypedef` registers it in
`TypePool` like any other typedef (`ParsedTypedef("__m128", <underlying
spelling>, ...)`). But `__m128`'s own underlying spelling (an
attribute-vector-typed builtin, e.g. `float
__attribute__((__vector_size__(16)))`) never resolves through
`pool.getType()` either — so `ParsedTypedef.createDataType()` returns
`null`, and the typedef "materializes" as an effectively-empty 1-byte
placeholder wherever Ghidra's own type resolution happens to leave it.
Every field of type `hkVector4` (or any type embedding `hkQuadReal`
directly) silently dropped, shrinking the whole enclosing struct — the
exact same shape of bug as patch 0015/0016's inline-embed cases, but
with an unrelated root cause (an unresolvable compiler intrinsic, not a
template specialization).

This was the entire explanation for `bhkCharacterController`'s residual
200-byte gap after patch 0016 (9 `hkVector4` fields) and
`hkpCharacterProxy`'s entire previously-unexplained -56 MISMATCH (3
`hkVector4` fields) — confirmed via `InspectGdt.java` component dumps
showing every `hkVector4` field at `len=0`.

## Fix

`TypePool.getType()` gained a new check for intrinsic-vector type names
(`__m128`/`__m128i`/`__m128d`/`__m128h`/`__m128bh`/`__m256*`/`__m512*`,
with optional `const`/`volatile`/elaborated `struct`/`union`/`class`
prefixes), matched **by name only** — a tightly-scoped regex
(`^(?:const |volatile |struct |union |class )*__m(128|256|512)[a-z]*\s*$`)
against the literal SSE/AVX/AVX512 intrinsic family, never a blanket
"this resolved to 1 byte" heuristic (a broad condition-based guard would
risk silently padding a genuinely correct 1-2 byte struct or empty-base
type to the wrong size). A match resolves straight to a same-sized
opaque `char[16]`/`char[32]`/`char[64]` (reusing the existing opaque-
padding mechanism from `SourceParser`'s C_X_X_BASE_SPECIFIER handling,
same fix shape).

This check runs **before** `resolveType()`/`materializeParsed()` at the
top of `getType()`, not after (where the original attempt at this fix
placed it) — the wrong 1-byte `TypedefDataType` that `materializeParsed`
would otherwise produce for e.g. `"__m128"` wins first if the check runs
later, and the fallback is never reached. Confirmed empirically: placing
the check after the existing resolution attempts left `hkVector4` at
`size=1`; moving it to the top fixed it.

## Verification

Full 1630-header sweep via the committed `generate_gdt.sh` pipeline:

- `check_regression.py`: **0 regressions** (all 3814 baseline-tracked
  classes), 57 improvements.
- `hkVector4`: EMPTY → **OK, exact** (16/16 = 0x10) — confirmed against
  the actual snapshot JSON, not eyeballed.
- All 57 improvements are Havok physics/math classes (`hkAabb`,
  `hkMatrix3`, `hkQuaternion`, `hkRotation`, `hkTransform`,
  `hkpRigidBody`, `hkpEntity`, `hkpMotion`, `bhkWorld`, etc.) — a
  coherent cluster matching exactly the family that embeds
  `hkVector4`/`hkQuadReal`, not scattered/unrelated noise. This is
  consistent with a tightly name-scoped fix and inconsistent with a
  guard that's silently corrupting unrelated small structs (a
  mis-scoped guard would show up as previously-correct 1-2 byte structs
  regressing to a wrong 16-byte size — the regression check would have
  caught that as `OK -> MISMATCH` or an actual-size mismatch; it did
  not, for any of the 3814 tracked classes).
- `bhkCharacterController`: MISMATCH (616/816) → MISMATCH (**808/816**)
  — much closer, not yet exact. Residual 8-byte gap not chased further
  (likely trailing struct padding/alignment); still MISMATCH, not
  regressed.
- `hkpCharacterProxy`: MISMATCH (184/240) → MISMATCH (**232/240**) —
  same story, 8 bytes short, not chased further.
- `TESQuest`: unaffected by this patch (already exact from patch 0016).

`coverage_baseline.json` updated.

# Patch 0018 — align the SSE/AVX intrinsic-vector opaque fallback

## Root cause

Patch 0017 fixed `hkVector4`/`hkQuadReal`/`__m128` resolution by
falling back to an opaque `char[N]` byte array. That fixed the FIELD
DROP, but `char[N]` (a plain `ArrayDataType` of `char`) carries only
1-byte alignment, while real SSE/AVX hardware requires
16/32/64-byte alignment for `__m128`/`__m256`/`__m512` respectively.
Any struct with a trailing (or, in general, any) intrinsic-vector
member needs its OWN overall size to round up to that alignment,
matching the real compiler's layout — with only 1-byte alignment, the
emitted struct came up short by however many trailing bytes the real
alignment padding would have added.

Confirmed empirically: after patch 0017, `bhkCharacterController` and
`hkpCharacterProxy` both landed *exactly* 8 bytes short of their real,
16-byte-aligned sizes (808/816, 232/240) — not a missing field (every
field the parser attempts resolves and lines up at the correct offset,
confirmed via `InspectGdt.java`), but missing tail padding.

## Fix

`TypePool`'s new `intrinsicVectorType(int size)` helper replaces the
bare `getType("char[" + size + "]")` opaque fallback with a packed,
explicitly-aligned single-member `StructureDataType` wrapping the same
opaque byte array (`setPackingEnabled(true)` +
`setExplicitMinimumAlignment(size)`), so Ghidra's own struct-layout
engine now accounts for the intrinsic's real alignment requirement when
computing any enclosing struct's size and member offsets.

## Verification

Full 1630-header sweep via the committed `generate_gdt.sh` pipeline:

- `check_regression.py`: **0 regressions** across all 3814
  baseline-tracked classes, 14 improvements, 3 newly-seen entries.
- Per the coordinator's specific caution before this patch landed — an
  alignment change shifts every member that follows an intrinsic-vector
  member mid-struct, and can add tail padding to ANY struct embedding a
  Havok-math member anywhere, cascading further to anything embedding
  those — the full improvements list was read by hand, not just the
  count: all 14 are Havok physics/constraint classes
  (`hkpCharacterProxy`, `bhkCharacterController`, `bhkPickData`,
  `hkpCharacterInput`, `hkpLimitedHingeConstraintData` (+ its nested
  `Atoms`), `hkpListShape`, `hkpRagdollConstraintData` (+ its nested
  `Atoms`), `hkpRagdollMotorConstraintAtom`,
  `hkpSetLocalTransformsConstraintAtom`, `hkpWorldLinearCaster`,
  `hkpWorldRayCastInput`), every one MISMATCH → OK (an existing,
  partially-correct resolution becoming exact) — no `OK -> MISMATCH`
  anywhere, which is exactly what a mis-scoped alignment bump
  over-padding a previously-correct struct would have produced. Zero
  such cases across the full 3814-class tracked set.
- `bhkCharacterController`: MISMATCH (808/816) → **OK, exact**
  (816/816).
- `hkpCharacterProxy`: MISMATCH (232/240) → **OK, exact** (240/240).
- `hkVector4`: unaffected, still exact (16/16, unchanged from patch
  0017).
- `TESQuest`: unaffected (already exact from patch 0016).

This closes out the Havok cluster — the last item in `LOOP_GOAL.md`'s
priority order. `coverage_baseline.json` updated.

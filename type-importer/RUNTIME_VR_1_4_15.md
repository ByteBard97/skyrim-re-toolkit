# v0.2 — Skyrim VR 1.4.15 runtime validation

Second runtime beyond AE 1.6.1170 validated layout-wise, same mechanism as
`RUNTIME_SE_1_5_97.md`: `RUNTIME_DEFINE=ENABLE_SKYRIM_VR=1` +
`mine_static_asserts.py --runtime ENABLE_SKYRIM_VR`, headers' own
`static_assert`s as ground truth, no code changes to the parser or stubs
needed.

## Ground truth scope

Unlike SE (0 classes assert a *different* value than AE — only 19 classes
assert where AE has none), VR has real value divergence:

- 64 classes have both an AE-applicable and a VR-applicable
  `static_assert`, and the two **assert different sizes** (VR's
  `NiNode`/`NiAVObject`-derived classes are consistently larger than AE's,
  e.g. `BSGeometry` 344 (AE) vs. 416 (VR) — expected, VR's rendering/node
  classes carry extra per-eye/VR-tracking state).
- 22 classes have a VR-applicable assert with no AE counterpart at all
  (same "only guarded for this runtime" pattern as SE's 19).

## Full 1630-header sweep results

Bucket totals (3818 tracked classes — one more than AE/SE's 3817, from a
VR-only class picked up by ground-truth mining):

| Status | AE (committed baseline) | VR (this sweep) |
|---|---|---|
| OK | 1934 | 1951 |
| EMPTY | 880 | 878 |
| NO_GROUND_TRUTH | 798 | 781 |
| MISMATCH | 178 | 180 |
| UNRESOLVED | 27 | 28 |

Same overall profile as AE/SE on the runtime-invariant majority (expected,
same ground truth for those classes). Of the 86 classes with genuine VR
divergence (64 differing-value + 22 VR-only): **47 resolve byte-accurate,
38 `MISMATCH`, 1 `UNRESOLVED`.** The `MISMATCH` cluster is concentrated in
`Ni`/`BS*Node`/`BS*TriShape` classes — not investigated further here (out
of scope for this validation pass; a root-cause pass on the VR-specific
`MISMATCH` cluster is a natural follow-up patch, not attempted in this
commit per the "validate first, patch separately" split used for SE).

Output artifacts: `/tmp/CommonLibSSE_VR.gdt` (2,899,708 bytes, 25725 types
committed, 0 failed), snapshot saved as `coverage_baseline_vr.json`.

## Not done

Same caveats as the SE writeup: no Address Library address cross-check, no
root-cause investigation of the 38 VR-specific `MISMATCH`es (candidate
follow-up work, not this milestone), AE 1.7.99/GOG not attempted.

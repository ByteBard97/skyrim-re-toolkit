# Patch 0019 -- RelocateMember tail-padding for BaseExtraList / ExtraDataList (ACCEPTED)

**No `.patch` file for this one** -- unlike patches 0001-0018, this fix
lives entirely in this repo's own `tools/GenerateGdt.java` and new
`scripts/`, not in the vendored `GhidraClangPoweredParse` submodule.

## Background

`BaseExtraList`/`ExtraDataList` were the two permanently-deferred hotspot
classes (`COVERAGE_SWEEP_PLAN.md`, this investigation's internal working notes): under
`ENABLE_SKYRIM_AE`, `BaseExtraList`'s real `data`/`presence` pointer
members are declared only `#ifndef ENABLE_SKYRIM_AE` -- a real, genuinely
empty class per the actual header source (confirmed by a real `clang-cl`
compile, see DESIGN.md). The fields are accessed at runtime via
`REL::RelocateMemberIfNewer<T>(this, seOffset, aeOffset)` instead of being
compiled struct members. This isn't a parser bug (our tool's `sizeof==1`
output is objectively correct for the header as written) -- representing
the true in-memory layout requires a new feature: detect the accessor
pattern and infer the real tail size from it.

## Root cause / investigation

Confirmed via minimal `.cpp`-source reading (not a clang probe this time --
the relevant code lives in `src/RE/E/ExtraDataList.cpp`, never parsed by
the layout-only header sweep):

- `BaseExtraList::GetData()`/`GetPresence()` use
  `REL::RelocateMemberIfNewer<T>(SKSE::RUNTIME_SSE_1_6_629, this, seOffset, aeOffset)`
  with AE offsets `0x8` (data) and `0x10` (presence) -- leaving exactly 8
  bytes of room at offset 0 for a vtable pointer, corroborated
  independently by the header's own comment
  (`~BaseExtraList(); // 00, virtual on AE 1.6.629 and later.`) and a
  community wiki confirmation that AE 1.6.629 broke `ExtraDataList`'s ABI.
  Inferred true AE size: **0x18 (24 bytes)**.
- `ExtraDataList::GetLock()` uses a *different* pattern -- a raw
  `reinterpret_cast<BSReadWriteLock*>(this + offset)`, not
  `RelocateMember` -- placing `_lock` (real, unconditional size `0x8` per
  its own `static_assert`) at offset `0x18` for AE ≥ 1.6.629. Inferred
  true AE size: **0x20 (32 bytes)**, matching the mutual-corroboration
  prediction (`BaseExtraList`'s new `0x18` + `ExtraDataList`'s own `0x8`
  lock = `0x20`) before any code was run.

## Design (per DESIGN.md's options (a) *and* (b), not just (a))

- `scripts/mine_relocate_member_offsets.py`: a new, narrowly-scoped
  miner (sibling to `mine_static_asserts.py`) that regexes
  `REL::RelocateMember[IfNewer]<T>(this, seOffset, aeOffset)` call sites
  out of `CommonLibSSE-NG/src/**/*.cpp`, computes
  `max(aeOffset + sizeof(T))` per class (pointer types only -- the only
  case needed here), and reports non-pointer-typed or unattributed call
  sites as explicitly skipped rather than silently dropped. Found 3
  candidate classes; only `BaseExtraList` was applied here after a
  blast-radius check (see below) -- `NiAVObject`'s candidate offset turned
  out to already be within its existing, correctly-resolved size (not a
  real gap), and one candidate was a misattribution artifact
  (`std` -- the miner's crude "nearest `ClassName::Method(`" heuristic can
  mis-attribute near an unrelated `std::`-qualified line; documented as a
  known limitation, not fixed here since it wasn't needed for this task).
  `ExtraDataList`'s own gap (the `reinterpret_cast` pattern) isn't
  regex-matched by this miner at all -- found and verified by hand, not
  automated.
- `tail_padding_hints.csv`: the actual applied hints -- just
  `BaseExtraList,24` and `ExtraDataList,32` -- reviewed and hand-verified,
  not auto-applied from the miner's raw output.
- `tools/GenerateGdt.java`'s new `--tail-padding-hints <csv>` /
  `applyTailPaddingHints(...)`: post-commit step (after the normal
  clang-parsed types are already in the `.gdt`, matching the file's own
  documented lesson that a `Structure`'s length isn't final until
  committed) that widens a named class's `Structure` with a trailing
  opaque `char[N]` field sized to close the gap, **and** sets the
  struct's `setDescription(...)` to explicitly say the size is an
  inferred lower bound mined from `RelocateMember` call sites, not a
  proven exact size -- satisfying DESIGN.md's option (b) alongside (a)
  rather than silently picking one.
- `scripts/generate_gdt.sh`: `TAIL_PADDING_HINTS` env var (default: the
  committed `tail_padding_hints.csv`, **AE runtime only** -- SE/VR already
  resolve these two classes correctly without padding per
  `RUNTIME_SE_1_5_97.md`, so applying this AE-mined hint file to a
  non-AE runtime would wrongly inflate an already-correct struct; the
  script checks `RUNTIME_DEFINE` and only defaults the hints file in for
  `ENABLE_SKYRIM_AE`). Set `TAIL_PADDING_HINTS=""` to opt out entirely.

## Off-by-one bug found and fixed during verification

First attempt widened `BaseExtraList` to 23 bytes, not the intended 24:
Ghidra reports `getLength() == 1` for a genuinely empty `Structure` (its
own "empty struct" convention, not a real occupied byte), and appending a
field to such a struct **replaces** that phantom byte rather than
appending after it. Fixed by checking `struct.getNumComponents() == 0`
and treating the starting size as `0`, not `1`, in that case. Caught by
inspecting the actual `.gdt` output with a throwaway `InspectGdt`-style
component dump before trusting the reported size -- the same
"minimal reproduction, verify against real output" discipline used
throughout this project.

## Blast-radius check (before writing any code)

`BaseExtraList`/`ExtraDataList` are embedded (by value or via
inheritance) in `TESObjectREFR`, `TESObjectCELL`, `Inventory3DManager`,
and (transitively, via `TESObjectREFR`) `Actor`/`Character`/
`PlayerCharacter`/`Hazard`/`Projectile` and its subclasses. Checked every
one of these against the committed AE `coverage_baseline.json` before
writing code: **all were already `EMPTY` or `NO_GROUND_TRUTH`, none were
`OK`** -- so widening the embedded classes could not regress a
previously-correct class (the zero-regressions rule couldn't be
violated even in principle by this change, confirmed empirically before
implementing, not just assumed).

## Verification

Full 1630-header AE sweep via the committed `generate_gdt.sh` pipeline
(now defaulting `TAIL_PADDING_HINTS` on for AE):

- `check_regression.py` against the pre-existing `coverage_baseline.json`:
  **0 regressions**, 2 improvements (`BaseExtraList` and `ExtraDataList`,
  both `EMPTY -> NO_GROUND_TRUTH`).
- Downstream propagation confirmed as expected: `TESObjectREFR`,
  `TESObjectCELL`, `Inventory3DManager`, `Actor`, `Character`,
  `PlayerCharacter` all grew by the same delta (their `NO_GROUND_TRUTH`
  status is unchanged -- there's still no AE-applicable `static_assert`
  for any of them, so this can't be confirmed byte-exact, only that it's
  no longer silently missing an entire known 24/32-byte block).
- SE/VR sweeps unaffected (hints don't apply outside AE) -- not re-run for
  this patch since the code path is provably untouched for those
  runtimes (the `RUNTIME_DEFINE` guard in `generate_gdt.sh`), but worth a
  fresh full sweep before the next SE/VR-targeted patch just to be safe.
- `coverage_baseline.json` updated to the new 2-improvement snapshot.

## Honesty about what this does and doesn't prove

Per DESIGN.md's own caution: **there is no static_assert or binary
ground truth to confirm `0x18`/`0x20` are the exact real sizes** -- this
is a well-corroborated (3 independent signals for `BaseExtraList`, a
matching predicted value for `ExtraDataList`) but still heuristic lower
bound, not a proven exact size. The emitted `.gdt` struct's own
description field says so explicitly, so a Ghidra user inspecting the
type isn't misled into treating it as asserted fact.

This closes the `BaseExtraList`/`ExtraDataList` gap as far as it can be
closed without real binary/Address-Library ground truth (see
`ADDRESS_LIBRARY_VALIDATION.md` for why that's out of reach here) --
37/39 -> effectively 39/39 of the original hotspot list has either an
exact resolution or the best-achievable heuristic one, per
this investigation's internal working notes' stop condition.

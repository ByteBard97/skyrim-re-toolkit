# Coverage Sweep — Plan

**Note:** this file's patch-by-patch narrative stops after patch 0018 — not
because tracking stopped, but to avoid duplicating ~50-100 lines of history
per patch across two files that could drift out of sync. Patches 0019
onward (including 0021's `isPolymorphic` fix, 0022's follow-on, and 0023's
Empty Base Optimization fix) are documented only in `patches/*.md`, which
is the authoritative source going forward.

Goal: use the now-working, patched `GhidraClangPoweredParse` pipeline (patches
0001-0005) to sweep as much of `CommonLibSSE-NG/include/RE/` as possible,
and produce a report of which classes resolve correctly, which resolve with
a wrong size, and which don't resolve at all — so the next round of fixes
(or the next round of manual header curation) has a concrete, prioritized
list instead of guessing.

This is the natural next step after the initial bring-up got
`TESForm`/`TESObject`/`TESBoundObject`/`TESObjectREFR` to byte-accurate
layouts: the same machinery should now work broadly, but "should" isn't
"does" until it's actually run against the other ~1000+ classes in the
codebase.

## Step 1 — Mine expected sizes from source

Extend the regex approach already used in `scripts/mine_instantiations.py`
into a new script, `scripts/mine_static_asserts.py`:

- Scan every `.h` file under `CommonLibSSE-NG/include/RE/`.
- Match `static_assert(sizeof(ClassName) == 0xNN);` (and the `sizeof(X) ==
  N` decimal form) — but **respect the `#ifndef ENABLE_SKYRIM_AE` /
  `#ifdef` guards** learned about the hard way during initial bring-up (`TESObjectREFR`
  and `BaseExtraList` both have version-gated asserts). The script should
  record, per class, a list of `(expected_size, guard_condition)` pairs
  rather than a single number, and mark which guard corresponds to our
  target runtime (`ENABLE_SKYRIM_AE` defined, `ENABLE_SKYRIM_SE`/
  `ENABLE_SKYRIM_VR` undefined).
- Output: a JSON or simple text map, `{ClassName: expected_size_for_AE}`,
  skipping classes whose only assert is guarded for a runtime we're not
  targeting (record these separately as "no AE assert available" rather
  than silently dropping them — some classes may only be checkable this
  way for SE).

**Open question, answered by running `scripts/mine_static_asserts.py`
against the real headers:** 2024 classes have an AE-applicable
`static_assert(sizeof(...))` — good coverage, not a small sample. 21 have
sizeof asserts only for other runtimes (`TESObjectREFR` and
`BaseExtraList` among them, matching the initial manual finding). 0 sit
behind an unrecognized preprocessor guard.

**Real finding, not a script bug:** 23 short, generic names (`Data`,
`Entry`, `Event`, `Flags`, `RUNTIME_DATA`, `Object`, `Value`, ...) collide
across multiple *different* nested/local classes in different files with
genuinely different sizes — e.g. `Data` is defined with 25 different
sizes across 25 unrelated classes' internal `struct Data`. A flat
`{ClassName: size}` map can't disambiguate these; they're excluded from
`mine_static_asserts.py`'s output map and listed separately for manual
inspection. Step 4's cross-referencing needs to either skip these
short/generic names entirely (they're almost never the class actually
being investigated) or namespace-qualify before matching — flat-name
collision is a real limitation of the ground-truth data, not something
Step 2's resolver can fix.

## Step 2 — Extend `GenerateGdt.java` for a full-sweep report mode

Right now it hardcodes printing four named structs. Add a `--report-all`
flag (or make this the default when no explicit struct names are given)
that, after `pool.resolve()`, iterates every `Structure` in the result and
prints `ClassName,SizeInBytes` — plus a separate list of any class *names
that were requested via the header list but never appear in the resolved
set at all* (fully-forward-declared-only, or blocked on something
upstream).

Keep the existing named-struct debug printing behind a flag for
backwards compatibility with the initial manual testing.

## Step 3 — Batch headers, don't do one-clang-TU-per-header

A single clang TU per header (creating hundreds of separate `TranslationUnit`
parses) would be slow and would lose cross-header context (many classes
only make sense with their dependencies already visited). Instead:

- Build the umbrella file the same way `SourceParser.parseFiles` already
  does internally — but from **all** headers in `RE/`, in one pass.
  **Do NOT use `RE/Skyrim.h`** — its first line is `#include
  "SKSE/Impl/PCH.h"`, the exact header the initial bring-up spent hours
  routing around (it pulls spdlog → real `<windows.h>` → trips
  `REX/W32/BASE.h`'s own "Windows API detected" guard; `stubs/layout_pch.h`
  exists specifically to replace it). Enumerate headers ourselves instead
  — `find include/RE -name '*.h'` — and force-include our own stub as
  usual. Headers are `#pragma once`-guarded and self-including, so
  enumeration order shouldn't matter.
- **Risk:** pulling in far more than the initial four-header slice did
  (thousands of declarations) — expect new stub gaps in
  `stubs/layout_pch.h` to surface (new SIMD intrinsics, new STL surface,
  possibly new REX::W32 pieces). Budget time for iterating on the stub,
  not just running the sweep once.
- **Risk:** compile time and memory for a single giant TU. Time-box it —
  if the single-TU parse over ~1000 headers doesn't complete in a few
  minutes, split by top-level subdirectory (`RE/A/`, `RE/B/`, …) and merge
  the reports rather than debugging a giant TU. The per-directory split
  also gives a natural progress signal instead of one long silent run.

## Step 4 — Cross-reference and report

New script, `scripts/coverage_report.py` (or fold into
`generate_gdt.sh` as a post-processing step):

- Load Step 1's expected-size map and Step 2's actual-resolved-size list.
- For each class with a known expected size:
  - ✅ match
  - ❌ mismatch (report both numbers)
- For each class requested but never resolved: ⚠️ unresolved
- **🔴 resolved-but-empty** (added per advisor review): size ≤ 1 with an
  expected size > 1. This is the actual failure signature hit five times
  during bring-up — `TESForm` came back *resolved, present, and size `0x1`* before
  each fix, which is neither "mismatch" (not subtly wrong, it's a
  placeholder) nor "unresolved" (it's in the pool). Sort this bucket
  first; it's the highest-signal list. Classes with no AE `static_assert`
  at all should still get this check — "resolved with a plausible
  non-zero size" vs. "resolved as an empty placeholder" doesn't need a
  ground-truth number.
- **`anon_tmpl_*` synthetics**: patches 0003/0005's inline-embedding
  generates `anon_tmpl_<hash>` structs. At four-header scale these were
  eyeballed; at ~1000-class scale they'll flood the output. Bucket them
  separately with a count rather than folding into the main report, and
  flag any that come out zero-length (direct signal of a missed
  `visitFields`/padding case).
- Print a summary count (✅/❌/⚠️/🔴) plus the full ❌, ⚠️, and 🔴 lists
  (these are the actionable ones — ✅ needs no action).
- **No silent caps**: if the sweep only covers a subset of `RE/` (per
  Step 3's risk notes), say so explicitly in the report header, not just
  in this plan.

**Verification to run early, before trusting ✅ counts at scale** (per
advisor review): the `char[N]` padding fallback (patch 0005) fires
whenever `visitFields` returns nothing. At scale this will hit far more
than `BSTEventSink<T>`-style pure-vtable bases — including template
specializations that genuinely have data members `visitFields` failed to
enumerate for some other reason, which would silently become opaque
same-size blobs instead of typed fields. Count how many `anon_tmpl_*`
structs consist solely of the `opaque` padding field and compare against
the number of distinct template instantiations `mine_instantiations.py`
reports. If those numbers are close, the fallback is doing the heavy
lifting and the ✅ column is measuring size-correctness only, not
field-level correctness — still useful, but worth knowing which claim
we're making.

## Step 5 — Scope of the first run

Attempt the full `RE/Skyrim.h` sweep directly rather than a hand-picked
subset — the pipeline already tolerates unresolved dependencies
gracefully (skips them, doesn't hard-fail), so there's little downside to
trying big first and narrowing only if it proves too slow or too noisy to
triage.

## Status (updated after building and validating on a subset)

Built: `scripts/mine_static_asserts.py`, `GenerateGdt.java --report-csv`,
`scripts/coverage_report.py`. Validated end-to-end on `RE/A/*.h` (53
headers, transitive closure = 5875 resolved data types / 1502 composite
structs/unions):

- Fixed two real stub gaps the sweep surfaced immediately: `RE/G/*.h`
  Scaleform headers use `UPInt`/`SPInt` and `RE/P/PackUnpack.h` /
  `RE/V/VirtualMachine.h` use `VMTypeID` without including the headers
  that define them (`RE/S/SFTypes.h`, `RE/B/BSCoreTypes.h`) — both real
  headers, both now force-included in `stubs/layout_pch.h`. Also added a
  missing `.none(...)` method to the `stl::enumeration` stand-in.
  Result: clang diagnostics on this subset went from 205 → 0.
- Fixed a report-correctness bug: Ghidra's resolved-type set includes
  function-signature `DataType`s (size `-1`), which flooded the EMPTY
  bucket with irrelevant noise. `GenerateGdt`'s `--report-csv` now filters
  to `Composite` (struct/union) types only.
- **Major finding**: on this subset, **928 of 1502 composites (62%)
  resolve EMPTY** (size ≤ 1) — far worse than the four hand-picked,
  hand-verified classes from the earlier manual work suggested. This is
  the actionable, prioritized output the sweep exists to produce; root-
  causing it is explicitly out of scope for this plan (see below) and is
  patch-0006+ work.
- **Full-namespace run completed** (all 1631 `RE/*.h` headers, well
  within the 15-minute time-box): 14564 total resolved data types, 4437
  of them composite structs/unions. 1147 clang diagnostics remain,
  overwhelmingly two categories not yet chased: (a) SIMD intrinsics
  (`_mm256_*`/`_mm512_*`) missing from the stub PCH's `<immintrin.h>`
  surface, and (b) `REL::VariantOffset` referenced in
  `RE/Offsets_VTABLE.h` but not defined by our `REL::Relocation` stand-in
  — both real, fixable stub gaps, left for patch-0006+ per this plan's
  scope.
  - **Final bucket counts**: OK=311, MISMATCH=1113, EMPTY=1390,
    UNRESOLVED=32, NO_GROUND_TRUTH=751, anon_tmpl_synthetics=679.
  - Of the 2814 classes checked against a real `static_assert`, only
    **311 (11%)** come back byte-accurate. 1113 resolve to a *wrong*
    non-trivial size (not a placeholder — genuinely miscounted fields or
    inheritance) and 1390 resolve empty. This is a much starker picture
    than the initial four hand-verified classes suggested, and is exactly
    the prioritized punch list this plan set out to produce.
  - Full report: `scripts/coverage_report.py` output cross-referencing
    `mine_static_asserts.py`'s ground truth against
    `GenerateGdt --report-csv`'s full-sweep output. Reports and the
    generated `.gdt` are left as local/scratch artifacts (not committed —
    they're regenerable, like all other `.gdt` output per `.gitignore`).
  - **Not yet investigated**: *why* MISMATCH and EMPTY are each this
    large — is it one systemic bug (e.g. multiple-inheritance base
    ordering, a second forward-declaration-wins case, a template pattern
    patches 0003/0005 don't cover) or many small ones? That triage is the
    natural patch-0006 starting point.

## Correction — the first full-sweep numbers were partly a measurement bug

Before trusting the 89%-wrong headline number, an advisor review flagged
exactly the right thing to check first: whether the report itself could
be lying. It was, in two independent ways, both found and fixed:

1. **Report generation measured the wrong point in the pipeline.**
   `GenerateGdt --report-csv` was reading sizes from the pre-commit
   in-memory `TypePool.resolve()` result, not from the `.gdt` file after
   `FileDataTypeManager.addDataType()` actually committed it. Ghidra
   recomputes/finalizes a `Structure`'s length on commit — confirmed
   directly: `AMMO_DATA` measured as size 12 pre-commit, but inspecting
   the real committed `.gdt` with a throwaway `InspectGdt.java` (opens
   the archive, dumps a named struct's components) showed it correctly
   at size 16, matching its `static_assert`. Fixed by having
   `writeCoverageReport` iterate `fileDtMgr.getAllDataTypes()` (post-
   commit) instead of the pre-commit list.
2. **The header-enumeration bug from Step 3 happened anyway.** The
   actual sweep command used `find RE -name '*.h'`, which — despite Step
   3's explicit note not to use `RE/Skyrim.h` — still included it,
   because it's just another file directly under `RE/`. This produced
   the exact predicted failure (`'spdlog/spdlog.h' file not found`,
   `redefinition of 'Relocation'`) buried in the diagnostic log. Fixed by
   adding `scripts/list_re_headers.sh`, a real committed script (not an
   inline shell one-liner) that enumerates `RE/*.h` minus a documented
   exclusion list, and updating both the CI workflow and manual re-runs
   to use it.

**Corrected full-sweep numbers** (1630 headers, post-commit sizes, 4384
composite types, 1144 clang diagnostics — down slightly from 1147, the
remainder is real SIMD-intrinsic/`REL::VariantOffset` stub gaps, not yet
chased): **OK=1004, MISMATCH=420, EMPTY=1365, UNRESOLVED=32,
NO_GROUND_TRUTH=727, anon_tmpl_synthetics=675**. Of 2821 checkable
classes, **1004 (36%) are byte-accurate** — far better than the
originally-reported 11%, but EMPTY is now clearly the dominant real
problem (1365, unchanged by either fix — this bucket was never a
measurement artifact). `coverage_baseline.json` has been regenerated from
this corrected run.

**Two named, concrete failure clusters identified from the corrected
data** (per advisor's guidance: histogram the deltas before fanning out):

- **EMPTY cascades into MISMATCH.** The MISMATCH delta histogram's
  largest clusters are exact multiples of real base-class sizes — e.g.
  24 classes (`AbsorbEffect`, `BanishEffect`, `CalmEffect`, ...) show
  `actual - expected == -144` (0x90), which is exactly `ActiveEffect`'s
  real size — and `ActiveEffect` itself is in the EMPTY bucket. When a
  base resolves empty, every subclass that embeds it as `super_X`
  inherits the shortfall. This means EMPTY is likely the single highest-
  leverage bug category: fixing it should shrink both buckets.
- **The `char[N]` padding fallback (patch 0005) fires far more than
  intended.** Of 868 `anon_tmpl_*` synthetic structs, **312 (36%) are
  opaque-only** (`{opaque: char[N]}`, no real fields) and **148 (17%)**
  are fully empty (size ≤ 1) — measured directly against the committed
  `.gdt` with the same `InspectGdt.java`/`CountOpaque.java` throwaway
  tools. This fallback was designed for pure-vtable-interface bases like
  `BSTEventSink<T>` with zero real data members; it's clearly also firing
  for template instantiations that DO have real fields, meaning
  `clang_Type_visitFields` is returning zero fields for a large fraction
  of real template specializations, not just interfaces.

Both are now being investigated (see below) rather than left as open
questions, since they're concrete enough to hand to a focused
investigation rather than "why are classes wrong" in the abstract.

## Patch 0006 — cross-namespace type references + missing keyword primitives (ACCEPTED)

Root-caused and fixed the EMPTY-class cluster above. Two independent
causes, both in `TypePool.java`, both documented in full in
`patches/0006-fix-cross-namespace-type-references.md`:

1. `TypePool` registers every type under its bare name, but clang spells
   a field's type with full namespace qualification whenever it's
   referenced from a different namespace than it's declared in (e.g.
   `RE::BSCriticalSection`'s member is spelled `"REX::W32::CRITICAL_SECTION"`,
   which never matched the pool's registered `"CRITICAL_SECTION"` key).
   Generalizes patch 0005's `std::`-prefix strip into stripping any
   leading namespace path, excluding template names.
2. `bool` (and `wchar_t`) are bare C++ keywords with no `typedef`/`using`
   declaration anywhere in the parsed AST to bootstrap their resolution
   from — unlike `std::uint32_t`, which self-registers via `<cstdint>`'s
   own real typedef. `bool` appears ~3500 times across `RE/*.h`; this was
   the single dominant cause of the EMPTY bucket. Fixed by pre-registering
   `bool`→`BooleanDataType` and `wchar_t`→`WideCharDataType`.

**Verified independently** (not just trusting the self-report): applied
patches 0001-0006 fresh, ran the full 1630-header sweep myself, got
identical numbers to the patch author's claim. Full sweep, before → after:

| Bucket | Before (0001-0005) | After (+0006) |
|---|---|---|
| OK | 1004 | **1234** |
| MISMATCH | 420 | 461 |
| EMPTY | 1365 | **1032** |
| UNRESOLVED | 32 | 32 |

`check_regression.py`: 383 improvements, 5 regressions (`HUDMenu`,
`KinectMenu`, `ModManagerMenu`, `SleepWaitMenu`, `TutorialMenu` — all
previously "OK" only by a coincidental cancellation of two independent
errors in `GFxValue` and `IMenu`/`FxDelegateHandler`; fixing `GFxValue`
removed one side of the cancellation and exposed the other, which was
never actually correct). Root cause of the exposed `FxDelegateHandler`
error is documented precisely in the patch's `.md` (`isPolymorphic()` is
blind to template-specialization primary bases for the same underlying
reason patch 0003 had to fix field extraction — `clang_visitChildren`
doesn't walk an implicit template specialization's cursor) and scoped as
a distinct follow-up patch (0007) rather than guessed at.

`coverage_baseline.json` has been updated to this run's snapshot — the
383 improvements (and the 5 now-honest regressions) are the new floor.

**Known follow-ups from this patch, not yet started:**
- Patch 0007: `isPolymorphic()`'s template-blindness (the `HUDMenu`-class
  regression's real cause). Needs a new libclang binding analogous to
  patches 0003/0004's `Type.visitFields()` fix, likely something mapping
  a specialization cursor back to its primary template pattern.
- A separate, distinct bug: `ParsedTypedef`'s resolution path doesn't go
  through the template inline-embedding mechanism patches 0003/0005 use
  for fields/bases, so a typedef-of-a-template-specialization (e.g.
  `using ActorHandle = BSPointerHandle<Actor>;`) can never resolve. This
  is why `AIProcess` and `ActiveEffect` are still not exact after patch
  0006 (`AIProcess`: 240 vs expected 320; `ActiveEffect`: still EMPTY).
- `char16_t`/`char32_t`/`char8_t` hit the same keyword-primitive gap as
  `bool`/`wchar_t` but are far rarer (~12 files total) — left unfixed to
  keep patch 0006's diff minimal; trivial to extend if they matter later.

## Patch 0007 — template base-class inlining (REJECTED pending revision — regressed at full scale)

Root-caused the opaque-fallback cluster: many CommonLibSSE-NG container
templates (`BSTArray<T>`, `hkArray<T>`, `NiTLargeObjectArray<T>`, etc.)
declare zero fields of their own — all real storage lives in base classes
(`BSTArray<T> : public Allocator, public BSTArrayBase`). `visitFields`
correctly reports zero own-fields for these; the bug was that
`parseFieldsFromType` never walked base classes at all, so it couldn't
tell "storage lives in bases" from "genuinely no data"
(`BSTEventSink<T>`) — both fell through to the same opaque blob. Fix
fetches the primary template's declaration (`clang_getSpecializedCursorTemplate`,
a new binding) to walk its base-specifiers, resolving template-parameter
bases to their concrete substituted type via two more new bindings.

**On the patch's own validation subset (RE/A + RE/B), this looked like a
clean win**: opaque-only `anon_tmpl_*` structs dropped 85% (144→22), zero
new clang diagnostics. **But an independent full 1630-header sweep told a
different story**: applying 0001-0007 and running `check_regression.py`
against the (0001-0006) baseline showed **62 regressions vs. only 19
improvements** — a net regression. OK count actually dropped, 1234→1195.
The regression pattern is suspicious in a specific way: nearly every
regressed class (mostly `hkb*`/`hka*`/`hkp*` Havok classes and `GFx*`
Scaleform classes) shrank by a consistent amount (often exactly 8, 16, or
24 bytes) rather than failing randomly — suggesting the new base-walking
logic is replacing a previously-correctly-sized opaque blob or
correctly-embedded base with an undersized substitute for a base-class
shape the fix didn't account for, rather than being randomly broken.

**Status after one revision round: still net-regressive, deferred, NOT merged.**
Sent back to the originating investigation with the exact regression
list. It found and fixed two more real, distinct bugs (documented in
`patches/0007-inline-template-base-classes.md`): an implicit-vptr
omission for polymorphic template bases (fixed deterministically by
reusing patch 0001's `isPolymorphic()` check), and a `clang_Type_getSizeOf`
call whose result depends on how much prior libclang activity preceded
it — confirmed reproducible (`hkRefPtr<hkbVariableBindingSet>` measured
8, then 16, then 12, for the identical type across different call
orderings) and only partially worked around (call it once, as early as
possible, use it only when nothing real was collected). Progression:
81 → 61 → 10 regressions across three full-sweep iterations.

**Independently re-verified**, including a direct determinism check
(reran the identical patched build twice): both full-sweep runs agreed
exactly — 10 regressions, 3 improvements, OK 1234→1227 relative to the
0006 baseline (`ArmorRatingVisitor`, `BSStream`, `Data190`,
`ExtraLinkedRef`, `ExtraLinkedRefChildren`, `LinkerProcessor`,
`LocalMapCamera`, `NiStream`, `RaceSexCamera`, `TESCamera` — all a type
alias over a template with a non-default explicit argument, e.g. `using
BSScrapArray = BSTArray<T, BSScrapArrayAllocator>`, where the
non-default argument is silently dropped). Two independent attempts at
this environment's much-longer (10-15 min) full-namespace sweep were
also killed by the sandbox itself mid-run (unrelated to the patch —
confirmed via a clean submodule revert both times, no corruption), which
is worth knowing if this is picked up again: budget for retries, and
treat the flakiness as environmental, not a patch signal.

**Decision: patch 0007 is DEFERRED, not merged, after two focused fix
attempts (per this investigation's internal working notes' "two attempts then defer" rule).** The
first attempt got the regression count from 81 down to 10. A second,
independent attempt fully root-caused the remaining 10: for alias types
like `BSScrapArray<T> = BSTArray<T, BSScrapArrayAllocator>`, the sugared
type's `numTemplateArguments()` silently drops the alias's own supplied
non-default argument (reports 1, not 2), while `canonicalType()`
correctly reports both, confirmed via a standalone libclang C probe with
no Java involved. A minimally-scoped fix using `canonicalType()` at just
the one call site was tried — and produced the exact same wrong answer
(`ArmorRatingVisitor` measured 40, not the correct 64) that a differently
structured attempt at the same fix had already produced, at worse
full-sweep numbers (12 regressions, not 10). Two structurally different
code paths implementing the same theoretically-correct fix both failed
identically at full-sweep scale despite being verified correct in
isolation — that rules out an implementation mistake and points at
scale-dependent libclang/Panama-FFI behavior (the same category as the
already-documented `clang_Type_getSizeOf` unreliability), not a logic bug
reachable by further Java-layer attempts.

`coverage_baseline.json` and `scripts/generate_gdt.sh` remain at
0001-0006 only — patch 0007's real container-template base-class
recovery is genuinely valuable (it's what dropped the opaque-`anon_tmpl_`
fallback rate substantially) but isn't merged until this is resolved.
**Revised recommendation for whoever picks this up next** (supersedes the
original one, per the second attempt's findings): don't re-attempt this
as a Java-level algorithm change. Investigate whether `-Xint` interpreter
mode itself is the relevant variable (this whole pipeline already runs
interpreter-only due to a documented, separate Panama-FFI/JIT crash — a
second, different JIT-related inconsistency in the same subsystem
wouldn't be a coincidence), or check LLVM's own issue tracker for known
`clang_Type_getTemplateArgumentAsType`-on-alias-templates bugs before
writing any more Java code.

## Toolchain finding: JDK 22+ final FFM API replaces the JDK 21 `-Xint` workaround

The pipeline originally required JDK 21 running in interpreter-only mode
(`-Xint`) as a workaround for a Panama-FFI/JIT crash. Root-caused: LLVM's own
SIGSEGV crash-recovery handler was misinterpreting HotSpot JIT's benign
implicit-null-check signals as a real libclang crash — not an actual libclang
bug, and not scale-dependent. Fix: `LIBCLANG_DISABLE_CRASH_RECOVERY=1`
(confirmed present in the libclang 19 binary) resolves it, which unblocks
using JDK 22+'s final (non-preview) FFM API instead of JDK 21's `-Xint`
preview-FFM workaround.

Verified via: hs_err crash analysis pinning the fault on LLVM's crash-recovery
handler, a pure-C probe (`scripts/scale_probe.c`) exonerating libclang at
full-sweep scale, and a full sweep on JDK 25 + JIT enabled reproducing the
committed baseline exactly (0 regressions, 0 improvements vs. the JDK 21
`-Xint` baseline, ~3-4 min instead of 10-15). Current state: JDK 25 + JIT is
what `generate_gdt.sh` and both CI workflows use. See `patches/0010-jdk22-ffm-final-api.md`
for the full writeup. This is orthogonal to patch 0007, which stays deferred
regardless of toolchain (produces the same wrong number, 40 instead of 64,
under either toolchain).

## Hotspot coverage audit (per this investigation's internal working notes item 2)

Raw sweep percentage across all ~2800 `RE::` classes isn't the right
target for community value — most of the long tail (Scaleform UI
internals, Havok physics minutiae) is rarely touched by real mods. A
curated hotspot list (38 classes at the time of this audit — the list later grew to 39; see the README's current status — commonly referenced by mods: the
`TESForm` hierarchy, actors, inventory, item types, quests/packages,
scene-graph, and character-controller physics — full list in
this investigation's internal working notes) was checked against the current baseline
(patches 0001-0006):

**14 of 38 are OK or plausibly correct** (`TESForm`, `TESObject`,
`TESBoundObject`, `ActorState`, `ActorValueOwner`, `InventoryChanges`,
`InventoryEntryData`, `TESPackage`, `TESCombatStyle` — exact matches; plus
`TESObjectREFR`, `Actor`, `Character`, `PlayerCharacter`, `TESObjectCELL`
— resolved to a plausible non-empty size but no `static_assert` exists to
confirm exactly).

**25 of 38 are wrong**, all documented here rather than guessed at or
silently left broken:

| Class | Status | Actual | Expected | Delta |
|---|---|---|---|---|
| `AIProcess` | MISMATCH | 240 | 320 | -80 |
| `BaseExtraList` | EMPTY | 1 | (n/a, AE-guarded assert) | — |
| `ExtraDataList` | EMPTY | 1 | (n/a, AE-guarded assert) | — |
| `TESNPC` | EMPTY | 1 | 616 | -615 |
| `TESRace` | EMPTY | 1 | 1208 | -1207 |
| `TESFaction` | MISMATCH | 208 | 256 | -48 |
| `TESObjectWEAP` | EMPTY | 1 | 544 | -543 |
| `TESObjectARMO` | MISMATCH | 360 | 552 | -192 |
| `TESObjectBOOK` | MISMATCH | 224 | 312 | -88 |
| `TESObjectMISC` | MISMATCH | 168 | 256 | -88 |
| `AlchemyItem` | MISMATCH | 224 | 360 | -136 |
| `IngredientItem` | MISMATCH | 240 | 320 | -80 |
| `EnchantmentItem` | MISMATCH | 128 | 192 | -64 |
| `SpellItem` | MISMATCH | 176 | 232 | -56 |
| `MagicItem` | MISMATCH | 128 | 144 | -16 |
| `EffectSetting` | EMPTY | 1 | 408 | -407 |
| `TESQuest` | EMPTY | 1 | 616 | -615 |
| `BGSLocation` | EMPTY | 1 | 240 | -239 |
| `TESWorldSpace` | EMPTY | 1 | 856 | -855 |
| `NiAVObject` | MISMATCH | 224 | 272 | **-48** |
| `NiNode` | MISMATCH | 248 | 296 | **-48** |
| `NiCamera` | MISMATCH | 344 | 392 | **-48** |
| `bhkCharacterController` | EMPTY | 1 | 816 | -815 |
| `hkpCharacterProxy` | MISMATCH | 184 | 240 | -56 |
| `CombatController` | EMPTY | 1 | 216 | -215 |

**One concrete, high-leverage lead worth flagging**: `NiAVObject`,
`NiNode`, and `NiCamera` (a base/derived chain) are *all* short by
exactly **-48 bytes** — the same cascading-from-a-shared-base pattern
already proven twice this pass (patch 0006's `BSCriticalSection` fix
rippled into `AbstractHeap`/`AIProcess`; patch 0006's regression
analysis found `GFxValue` rippling into 5 menu classes). Whoever chases
this next should look at `NiAVObject`'s own base chain
(`NiObjectNET`/`NiObject`) for a single missing ~48-byte member rather
than treating these as three separate bugs.

**Decision: this audit is being documented as this loop's answer to
"hotspot list byte-accurate-or-documented-as-blocked," not chased to
zero in this pass.** Fixing the 25 broken classes above would mean
root-causing several more distinct bugs with the same rigor as patches
0001-0007 (each of which took a full focused investigation) — that's
open-ended, multi-session work, not something to rush through in one
loop iteration per this project's own established standard of verifying
before changing behavior. This table is the prioritized, actionable
punch list; treat it as the starting point for a patch 0008+ round, with
the `NiAVObject`/`NiNode`/`NiCamera` cluster as the highest-leverage
first target (three hotspot classes fixed by one root cause, mirroring
patch 0006's proven cascade pattern).

## CI workflows — locally verified (per this investigation's internal working notes item 1's last bullet)

- `type-importer-coverage.yml`: its exact steps (`list_re_headers.sh` →
  `generate_gdt.sh` with `REPORT_CSV` → `mine_static_asserts.py` →
  `coverage_report.py` → `check_regression.py`) have been run locally,
  by hand, many times over the course of this pass against the
  current committed `coverage_baseline.json` (0001-0006) — most recently
  producing OK=1234/MISMATCH=461/EMPTY=1032, matching the committed
  baseline exactly, i.e. `check_regression.py` would report zero
  regressions. Not yet run on GitHub Actions itself (no push has
  triggered it) — see the workflow file's own note about the toolchain
  download/cache steps being unexercised in the real hosted-runner
  environment.
- `symbol-archive-build.yml`: its core command (`list_re_headers.sh` →
  `generate_gdt.sh` with a SHA-named output, no `REPORT_CSV`) was run
  locally end to end: produced `CommonLibSSE_AE_b93280e8.gdt`, 16960
  resolved data types, 0 failed additions, submodule cleanly reverted
  afterward — matching the same numbers as the coverage-sweep runs
  against the same 0001-0006 patch set. Also not yet run on GitHub
  Actions itself.

## Investigation — `visitFields` opaque-fallback firing on real template fields (in progress)

## Step 6 — Regression fixture + CI (added after the first full sweep)

The full sweep found 89% of checkable classes wrong in some way. That
number will only improve incrementally, patch by patch — which creates a
real risk this parser's own history already demonstrates: a fix for one
class can silently break another (that's exactly why this sweep was
built). So the sweep needed to become a standing regression gate, not a
one-off report:

- `scripts/coverage_report.py --json-out <path>` writes a machine-
  readable `{ClassName: {status, expected, actual}}` snapshot alongside
  its usual text report.
- `type-importer/coverage_baseline.json` is that snapshot from the first
  full sweep, committed to the repo as the regression baseline (3597
  entries: every class with ground truth, resolved, or both).
- `scripts/check_regression.py --baseline <committed> --new <fresh>`
  ranks each class's status (`UNRESOLVED < EMPTY < MISMATCH <
  NO_GROUND_TRUTH < OK`) and exits 1 if any class's rank drops — i.e. a
  patch fixed some classes but broke previously-working ones. New
  classes not in the baseline are never a regression; improvements are
  reported but don't fail the build. Verified against itself (0
  regressions) and against a deliberately mutated snapshot (1 caught,
  correct exit code).
- `.github/workflows/type-importer-coverage.yml` runs all of this on
  every push/PR touching `type-importer/**`: sets up JDK 21 (Temurin),
  downloads and caches Ghidra 12.1.3, LLVM 19.1.0 (for libclang), and an
  `xwin`-splatted Windows SDK/CRT header set, runs the full sweep, and
  fails the build on any regression against the committed baseline.
  Fully Linux-native (`ubuntu-latest`), per this repo's platform
  constraints — no Windows runner needed. Toolchain download/cache steps
  are pinned to the exact release asset names (verified via `gh release
  view` against the real GitHub releases, not guessed).
- **Not yet done**: this workflow has not been run on GitHub itself yet
  (no push has triggered it) — it's been validated by running the same
  three scripts locally with the same toolchain, but the actual CI
  environment (runner disk/memory limits, download reliability, `xwin`'s
  non-interactive license acceptance in a hosted runner) hasn't been
  exercised. First real push touching `type-importer/**` will be the
  first real test.
- **When a patch legitimately fixes classes**: re-run the sweep, confirm
  no regressions, then regenerate `coverage_baseline.json` from the new
  snapshot and commit it alongside the patch — that's how "improvement"
  gets locked in as the new floor.

## What this plan does NOT cover

- Fixing whatever the sweep finds — this plan produces a prioritized list,
  it doesn't fix every class in one pass. Expect a followup patch (0006+)
  once real failure patterns are visible at scale.
- The known `TESObjectREFR` `0x70` vs `0x78` alignment gap (patch 0005's
  writeup) — that's a separate, already-diagnosed issue, not something
  this sweep needs to re-discover.
- Other runtimes (SE/VR/GOG) — this is AE-only, matching everything else
  built so far.

## Toolchain root-cause investigation (2026-08-24 evening) — the two "unfixable" platform problems are SOLVED, and patch 0007's blocker is reframed as an ordinary bug

Full detail in `patches/0010-jdk22-ffm-final-api.md` and the third-
investigation section of `patches/0007-inline-template-base-classes.md`.
Summary of what changed:

1. **The JIT crash was never Panama.** LLVM's crash-recovery SIGSEGV
   handler was killing the JVM when HotSpot's JIT-compiled code triggered
   its own benign implicit-null-check SIGSEGVs (hs_err: `SIGSEGV (sent by
   kill)` inside JIT-compiled *Ghidra DB code*, nowhere near FFM). Fixed
   with `LIBCLANG_DISABLE_CRASH_RECOVERY=1`, now exported by
   `generate_gdt.sh`. The pipeline runs JDK 25 + full JIT; full sweeps
   dropped from 10-15 min to ~3-4 min.

2. **Toolchain moved to JDK 25 (Temurin, `~/.local/tools/jdk-25.0.4.1+1`).**
   Patch 0010 ports the vendored bindings to the final FFM API (6
   mechanical renames), applied by the script only on JDK 22+. Both CI
   workflows updated from JDK 21 to 25. Verified value-neutral: a full
   sweep with patches 0001-0006 on JDK 25 + JIT reproduces the committed
   `coverage_baseline.json` EXACTLY (0 regressions, 0 improvements).

3. **libclang exonerated at scale.** `scripts/scale_probe.c` (pure C, no
   Java) parses the identical 1630-header umbrella TU with identical
   flags and shows every previously-"unstable" query is deterministic and
   correct, before AND after sweep-scale traffic over all 3,445 records.

4. **Patch 0009 (typedef-of-template-specialization) attribution**: a
   full sweep with 0001-0006+0009 vs 0001-0006 shows 0009 alone is
   **+366 improvements / -1 regression** (OK 1234 -> 1523; EMPTY 1032 ->
   792). The one regression: `BGSSoundOutput` OK(64) -> MISMATCH(72), +8
   looks like a duplicated vptr on one of its interface bases — small,
   specific, undiagnosed. Decision pending: fix it (then update baseline
   to lock in the 366), or accept 1:366 and update the baseline with a
   documented known-regression. `coverage_baseline.json` NOT yet updated.

5. **Patch 0007 remains unmerged but is no longer mysterious.** With the
   canonicalType revision (now in the on-disk patch), on JDK 25 the same
   wrong sizes reproduce byte-for-byte as on JDK 21 -Xint — while pure C
   proves clang's answers are right. So the failure is a deterministic,
   registration-order-dependent bug in this pipeline's own composition
   (prime suspect: `anon_tmpl_<hash-of-spelling>` keying + TypePool's
   leading-only `RE::` strip treating canonical vs sugared spellings of
   the same instantiation as different types, first-registration wins).
   Vs. the current patch set, 0007 is 16 regressions / 7 improvements —
   still net-negative until that composition bug is fixed. See the 0007
   .md's revised recommendation; iteration is now cheap (~3-4 min/sweep).

## Patch 0011 — qualified type registration (ACCEPTED, baseline updated)

The shared root cause identified at the end of the toolchain investigation
(string-keyed first-wins registration on colliding bare names) is fixed:
see `patches/0011-qualify-nested-record-registration.md` for the four
coordinated pieces (qualified registration, qualified field/base/typedef
references, progressive qualifier peeling in resolution, and a
record-scope-aware `mine_static_asserts.py`), plus two real masked bugs
it exposed and fixed (unions never had template-member inline-embedding;
nested base classes were spelled bare at inheritance sites).

Full-sweep effect: **OK 1523 -> 1667**, tracked ground truth 2024 -> 2149
classes, hotspot classes `TESRace`/`TESObjectWEAP`/`TESObjectARMO`/
`SpellItem`/`AlchemyItem`/`EnchantmentItem`/`NiAVObject`/`NiNode`/
`NiCamera`/`MagicItem`/`IngredientItem`/`TESObjectBOOK` all byte-accurate.
Known deltas accepted with the baseline update (48 better : 3 worse):
`GFxLoadStates`/`GFxStream` (+8 each, Scaleform tail, old "OK" was two
masking errors cancelling), `RUNTIME_DATA2` (untrackable bare
macro-generated name). This also removes the CI-vs-dev-machine
nondeterminism (5 classes resolved differently per machine purely from
collision order).

`coverage_baseline.json` regenerated from the accepted 0011 sweep
(3813 entries, qualified keys). Next candidates: rebase patch 0007 onto
qualified registration (its anon_tmpl_ canonical-vs-sugared hash
collisions are this same family), then the remaining hotspot gaps
(`TESQuest` EMPTY, `bhkCharacterController` EMPTY, `AIProcess` -32,
`TESFaction` -32, `TESWorldSpace` -144, `TESNPC` -8).

## CI-vs-local determinism: CLOSED (patches 0012-0014, first fully-green hosted run)

Run 32793651934 (patch 0014's commit): the hosted runner reproduces the
committed baseline EXACTLY — 0 regressions, 0 improvements. The complete
investigation chain, each step evidence-driven: runner clang probe
(`scripts/nested_probe.c`) exonerated libclang on the runner; the
workflow's `GCPP_DEBUG_DEPS` dispatch input traced the blocker to the
bare 'Color' key held by MistMenu's nested enum (enums were 0011's
phase-1 exclusion; struct-vs-enum contests have no tiebreaker, so
machines kept different winners); 0014 qualified enum registration and
added never-peel-past-a-known-name on-demand materialization (which the
enum change itself exposed via DisguiseEffect::State). Net across
0012-0014: OK 1668 -> 1701, +46 classes, zero regressions, and the gate
is now trustworthy on any machine. Current stack: patches 0001-0006,
0009, 0011-0014 (0007 still deferred, 0008 investigation-only).

## Patch 0015 — inline-embed nested-struct and template-parameter-typed fields (ACCEPTED)

Fixed the this investigation's internal working notes "small consistent-delta cluster" (`TESNPC`,
`TESFaction`, `EffectSetting`, `BGSLocation`, `CombatController`,
`TESWorldSpace`) with one shared fix in `parseFieldsFromType`: a field
whose raw type is a struct nested INSIDE its owning template (e.g.
`BSSimpleList<T>`'s own `Node _listHead`) or whose type resolves through
a template PARAMETER to another template specialization (e.g.
`BSPointerHandle<T, Handle=BSUntypedPointerHandle<>>`'s own `Handle
_handle`) was falling through to a doomed string lookup and getting
silently dropped. Full detail and verification in
`patches/0015-inline-embed-nested-and-parameter-typed-fields.md`. All 6
target classes now resolve exactly. Full sweep: OK 1701 -> 1832 (+131
net), 2 regressions (`FxDelegate`, `MenuTopicManager`), both confirmed
as unmasking the same `isPolymorphic()` template-blindness gap already
tracked in deferred patch 0008 (coincidental error cancellation, same
pattern as patches 0006/0009's own regressions) — accepted per
established precedent. `coverage_baseline.json` updated. Hotspot list:
34/39 OK-or-plausible (up from 27/39 pre-0015), independently confirmed
by both sessions.

## Patch 0016 — inline-embed array-of-template-specialization fields (ACCEPTED)

Fixed the Havok cluster's `bhkCharacterController` (EMPTY) and, as the
same shared root cause, `TESQuest` (EMPTY, previously deferred — see its
corrected writeup above). Root cause: a C-style array field whose
*element* type is a class template specialization (e.g.
`NiPointer<bhkShape> shapes[2]`, `BSTArray<TESTopic*> topics[6]`)
reports its own libclang kind as `CONSTANT_ARRAY`, so patch 0015's
inline-embed check (which only looked at the field's own type) never
fired; the field fell through to an unresolvable string dependency that
left the whole enclosing struct permanently stuck in `TypePool.resolve`'s
dependency-fulfillment gate, never reaching `createDataType()`. Full
detail, investigation trail (including how the advisor tool caught that
this was one bug shared with `TESQuest`, not two separate ones), and
verification numbers in
`patches/0016-inline-embed-array-of-template-fields.md`. Full sweep: 0
regressions, 38 improvements. `TESQuest` now resolves exact (616/616).
`bhkCharacterController` improved from EMPTY to MISMATCH (616/816) —
every field the parser attempts now resolves; the remaining gap is a
newly-found, unrelated, separately-deferred bug (see below).
`coverage_baseline.json` updated.

## Patch 0017 — opaque fallback for SSE/AVX intrinsic vector types (ACCEPTED)

Follow-up to patch 0016's own deferred finding, picked up the same
session rather than left for later: `RE::hkVector4`'s one member,
`hkQuadReal quad;` (`hkQuadReal` = `using hkQuadReal = __m128;`), is a
compiler-builtin SSE vector type our parser and Ghidra's
`DataTypeParser` have no concept of — clang parses `__m128` as a real
typedef, but its own underlying spelling never resolves either, so it
materializes as an empty 1-byte placeholder and every field of type
`hkVector4` was silently dropped. Fixed by adding a tightly
name-scoped check to `TypePool.getType()` (matches only the literal
`__m128`/`__m256`/`__m512` intrinsic family, never a blanket
"resolved-to-1-byte" heuristic — a broad guard would risk corrupting
genuinely correct tiny structs) that redirects to the existing opaque
`char[N]` padding mechanism. Full detail and verification in
`patches/0017-intrinsic-vector-opaque-fallback.md`.

Full sweep: 0 regressions (all 3814 baseline-tracked classes), 57
improvements, all Havok physics/math classes — a coherent cluster
consistent with a correctly-scoped fix. `hkVector4` now resolves EXACT
(16/16, confirmed against the snapshot JSON, not eyeballed).
`bhkCharacterController` improved 616→808/816 (still MISMATCH, 8 bytes
short — not chased further, likely trailing padding).
`hkpCharacterProxy` improved 184→232/240 (same story). Neither is fully
exact yet, but both are dramatically closer and the MISMATCH is
strictly smaller than before — no regression risk in leaving the
residual 8-byte gaps for a future session. `coverage_baseline.json`
updated.

**Update — the residual 8-byte gap was NOT left for a future session;
see patch 0018 below, picked up immediately after because the 8-byte
shortfall in both classes rounding exactly to a 16-byte boundary was
too strong a lead not to chase.**

## Patch 0018 — align the SSE/AVX intrinsic-vector opaque fallback (ACCEPTED)

Patch 0017's `char[N]` opaque fallback fixed the field drop but only
carries 1-byte alignment; real `__m128`/`__m256`/`__m512` require
16/32/64-byte alignment, so any struct with an intrinsic-vector member
came up short on its own trailing size-rounding — exactly the 8 bytes
`bhkCharacterController` and `hkpCharacterProxy` were both missing.
Fixed by wrapping the opaque bytes in a packed, explicitly-aligned
single-member `StructureDataType` (`setExplicitMinimumAlignment(size)`)
instead of a bare array. Full detail in
`patches/0018-align-intrinsic-vector-fallback.md`.

Full sweep: 0 regressions (all 3814 baseline-tracked classes), 14
improvements — read by hand per the coordinator's specific caution that
an alignment change can shift members and add cascading tail padding
far beyond the two targeted classes, not just counted: all 14 are
Havok physics/constraint classes, all MISMATCH → OK, zero `OK ->
MISMATCH` anywhere (which is what an over-padding bug would have
produced). `bhkCharacterController`: **OK, exact (816/816)**.
`hkpCharacterProxy`: **OK, exact (240/240)**. This closes out the
Havok cluster — the last item in this investigation's internal working notes' priority order.
`coverage_baseline.json` updated.

## `BaseExtraList` / `ExtraDataList` — NOT A BUG, deferred as out of scope

Investigated per this investigation's internal working notes' priority order. Both resolve EMPTY
(size 1), but this is **not a parser defect** — `DESIGN.md`'s own
"invisible relocated member" investigation (written earlier this
session, before the coverage sweep existed) already established that
`RE::BaseExtraList` genuinely compiles to an empty class under
`ENABLE_SKYRIM_AE`: its `data`/`presence` pointer members are declared
only `#ifndef ENABLE_SKYRIM_AE` and are accessed at the real game's
runtime via a `REL::RelocateMember`-style offset trick, not as compiled
struct members. A real `clang-cl -fdump-record-layouts-complete` compile
of the actual headers independently confirmed this: `BaseExtraList`
genuinely reports `sizeof == 1` under AE. Our EMPTY result is the
objectively correct answer to what the compiler produces from these
headers — not something to "fix" via better type resolution.
Representing the *true* in-memory object size (which is larger, per
DESIGN.md's own analysis) would require detecting the
`REL::RelocateMember[IfNewer]` accessor pattern and manually appending
undeclared trailing bytes to the emitted struct — a real, distinct,
not-yet-designed feature already flagged as an open question in
DESIGN.md, not a resolution bug. Out of scope for this loop; left
deferred with this written reason.

## `TESQuest` — RESOLVED, same root cause as the Havok cluster (patch 0016)

this investigation's internal working notes guessed `TESQuest` was blocked by `BaseExtraList`/
`ExtraDataList` — **confirmed wrong**: `TESQuest`'s real bases are
`BGSStoryManagerTreeForm` and `TESFullName` (`RE/T/TESQuest.h:186`),
neither of which references `BaseExtraList`/`ExtraDataList` anywhere,
and both resolve correctly and independently.

An earlier pass in this pass deferred `TESQuest` after one focused
attempt that ruled out missing dependencies, forward-decl collision, and
dependent array-size expressions, but did not find the actual cause. A
follow-up investigation (using a debug-instrumented copy of the parser
in an isolated `/tmp` build, per this project's "verify empirically"
discipline) found it: `parseStruct` traces showed `TESQuest` WAS being
parsed correctly (27 fields + 2 bases = 29 total) and WAS being
registered in `TypePool` with the full field count — directly
contradicting the original "silent 1-byte stub with no error trail"
framing. That earlier deferral's speculative lead (checking whether
`clang_visitChildren` sees `TESQuest`'s own `C_X_X_BASE_SPECIFIER`
children at all) is **dead and disproven** — the trace shows
`baseClasses.size=2`, so base specifiers were visited correctly all
along. Do not pursue that lead if revisiting this investigation.

Tracing `TypePool.checkDependenciesFulfilled` further (registered-but-
never-resolved is a downstream symptom, not a parsing symptom) found the
real cause: `TESQuest` has two fields whose declared type is a **C-style
array of a class template specialization**:
```
BSTHashMap<BGSDialogueBranch*, BSTArray<TESTopic*>*> branchedDialogue[DT::kBranchedTotal];
BSTArray<TESTopic*>                                  topics[DT::kTotal - DT::kBranchedTotal];
```
`SourceParser.parseStruct`'s FIELD_DECL case only inline-embeds a
field's own raw/canonical type when the field's own reported `TypeKind`
is `RECORD`/`UNEXPOSED` and its spelling contains `<` (added by patch
0015 for direct template-typed fields). For an array field, libclang
reports the field's own kind as `CONSTANT_ARRAY`, not `RECORD`/
`UNEXPOSED` — so this check never fired, the array fell through to a
plain string-keyed dependency (`"BSTArray<TESTopic *>[6]"`), and that
name was never independently registered anywhere in the pool (template
specializations are never registered by name — only inline-embedded),
so `checkDependenciesFulfilled` permanently reported it unfulfilled and
`TESQuest` never made it past `resolve()`'s dependency-gate into
`createDataType()`.

**This is the exact same root cause independently found in the Havok
cluster** (`bhkCharacterController`'s `NiPointer<bhkShape> shapes[2]`,
see patch 0016's own writeup below) — one shared fix, not two separate
bugs. Per the advisor's correction earlier in this investigation:
`TESQuest` and the Havok cluster should be treated as one bug with one
signature ("registered complete in the pool, never resolved into a
`.gdt`"), not as independent deferred items — the "two attempts then
defer" clock that had started on `TESQuest` as a standalone item does
not apply once patch 0016 lands, since a genuinely new investigation
angle (dependency-resolution tracing, not repeated parse-stage
speculation) found the cause on the very next attempt.

See "Patch 0016" below for the fix and full-sweep verification numbers.
`TESQuest` is no longer deferred.

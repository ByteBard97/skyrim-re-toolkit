# Patch 0007: inline base classes of class-template-specialization fields/bases

**SUPERSEDED (2026-08-26, patch 0025).** Reopened per the user's direct
go-ahead. First finding: the architecture this doc describes no longer
exists -- patches 0011-0018 reworked template-field/base handling into a
purely recursive inline-embed-by-value scheme, and `anon_tmpl_*` is now
just a cosmetic debug name, never a `TypePool` lookup key -- so the
"first-registration-wins keying bug" this doc's THIRD investigation
diagnosed is moot; there was nothing left to fix along that path. All 10
classes this doc lists under "Known remaining regressions" are already
`OK` in the current baseline, closed independently by those later
patches. A fresh full-sweep review (same problem area -- template
specializations used as fields/bases -- but a different, currently-live
bug) found and fixed a real remaining gap: `parseFieldsFromType` silently
dropped a template specialization's own base-contributed content (e.g.
`hkInplaceArray<T,N>`'s real storage living in `hkArrayBase<T>`,
`BSTObjectDictionary<...>`'s two policy-base vptrs) whenever it also had
real fields of its own. See `patches/0025-inline-embed-base-contributed-
prefix.md` for the fix and verification (0 regressions / 19 improvements
across AE/SE/VR). This file is kept for its historical investigation
record, not as an active TODO.

**Status: DEFERRED after two focused fix attempts. Written, iterated
through an independent full-sweep regression review, and substantially
improved -- but NOT a zero-regression patch. 10 known regressions remain
against `coverage_baseline.json` (down from an initial 81 found by
full-sweep verification). A second, targeted attempt at the remaining 10
(see "Second attempt" below) reproduced the same failure mode via a
different code path, confirming this is scale-dependent libclang
behavior rather than a fixable logic bug in this codebase's Java layer.
Per this project's own "two focused attempts, then defer" rule
(this investigation's internal working notes), this patch stays unmerged.
`coverage_baseline.json` and `scripts/generate_gdt.sh` remain at
0001-0006 only. See "Known remaining regressions" below for the
technical detail, and "Second attempt" for why a further attempt isn't
recommended without new tooling (e.g. instrumenting libclang itself, or
switching off Panama FFI) to actually see what's different about
identical calls at small vs. full scale.**

## The problem this addresses

The coverage sweep found that of 868 `anon_tmpl_*` synthetic structs
(patch 0003/0005's inline-embedding mechanism for class-template
specializations used as fields or base classes), **312 (36%) were
opaque-only** (`{opaque: char[N]}`, no real fields) and 148 (17%) were
fully empty (size <= 1). The opaque fallback in patch 0005 was designed
for pure-vtable-interface bases like `BSTEventSink<T>` (zero data
members, genuinely nothing to model besides the vptr). It was firing far
more broadly than that.

## Root cause, confirmed empirically

The overwhelming majority of failing instantiations are container/
wrapper templates -- `BSTArray<T>`, `hkArray<T>`, `NiTLargeObjectArray<T>`,
`GAtomicInt<T>`, `BSTSmallArray<T>` -- **not** pure interfaces. Looking at
the real source (`RE/B/BSTArray.h`):

```cpp
template <class T, class Allocator = BSTArrayHeapAllocator>
class BSTArray :
    public Allocator,
    public BSTArrayBase
{
    // ... methods only, ZERO data members of its own ...
};
```

`BSTArray<T>` declares **no fields of its own** -- all its real storage
lives in its **base classes**. `clang_Type_visitFields` correctly reports
zero fields for it (it only walks *own* fields, by design). Before this
patch, `parseFieldsFromType` had no way to distinguish "no fields because
everything is inherited" from "no fields, genuinely nothing, pure
interface" -- both fell through to the same opaque padding.

**The fix**: fetch the cursor for the **primary (uninstantiated)
template** declaration via a new `clang_getSpecializedCursorTemplate`
binding. Unlike the instantiated specialization (whose own declaration
cursor `clang_visitChildren` finds zero children for -- the same quirk
patch 0003 established for fields), the primary template is real written
source, so `clang_visitChildren` walks it normally, including its
`C_X_X_BASE_SPECIFIER` children. A base written in terms of a template
parameter (e.g. `BSTArray`'s `Allocator`, defaulting to
`BSTArrayHeapAllocator`) is resolved back to the concrete substituted
type for this instantiation via two more new bindings
(`clang_Type_getNumTemplateArguments`/`clang_Type_getTemplateArgumentAsType`),
matched positionally against the primary template's own
`TEMPLATE_TYPE_PARAMETER` order -- falling back to the parameter's own
default type (read from a `TYPE_REF` child of the parameter cursor) when
the instantiation didn't supply an explicit argument.

## Independent full-sweep verification found regressions -- three rounds of fixes

An initial version of this patch was validated only on a small `RE/A/`+
`RE/B/` subset and looked clean. An **independent full 1630-header sweep
review by the coordinator** found this was a **net regression**: 62
regressions vs. 19 improvements against `coverage_baseline.json`
(patches 0001-0006). Investigating this rigorously (isolated in a
temporary clone, comparing before/after field-by-field via a throwaway
Ghidra-API inspection tool) found three distinct, real bugs:

### Bug 1: `GenerateGdt`'s report measured the wrong point in the pipeline
(Not part of this patch -- see the coordinator's parallel fix, now
patch 0006. Mentioned here because it inflated the *apparent* regression
count before the real ones were isolated.)

### Bug 2: implicit vptr contributions were never modeled
`GFxLogBase<T> : public GFxLogConstants` has a virtual destructor (an
implicit vptr, 8 bytes) plus an empty base (`GFxLogConstants`, correctly
0 bytes via empty-base-optimization, real
`static_assert(sizeof(GFxLogBase<void*>) == 0x8)`). Base-walking recovers
the empty base correctly but never accounted for the specialization's
*own* vptr. **Fix**: reuse the exact same `isPolymorphic()` cursor-based
check patch 0001 already uses for ordinary (non-template) structs --
deterministic, no `sizeOf()` involved -- applied to the primary template.
A new vptr is added only if the type is polymorphic and its first base
isn't already.

### Bug 3: `clang_Type_getSizeOf` is unreliable depending on WHEN and how much libclang traffic precedes it
Confirmed reproducibly: `hkRefPtr<hkbVariableBindingSet>` (real
`static_assert(sizeof(hkRefPtr<void*>) == 0x8)`, a single pointer field,
zero base classes) measured **8** when `sizeOf()` was called as the very
first libclang operation on the type, but **16**, then **12**, on
different code revisions that all called it *after* this patch's own
base-walking/template-introspection activity had run -- with nothing
about the type itself different between measurements. This was not fully
root-caused (a Panama-FFI/libclang interaction is suspected) but is real
and reproducible. **Fix, in two parts**:
- Always compute `realSize = type.sizeOf()` **once**, as early as
  possible (before any base-walking/template-introspection), matching
  the placement patches 0001-0006 always used. Never call it a second
  time later in the same invocation.
- Only *use* that value (as opaque-fallback padding, or as the
  `expectedSize` top-up threaded into a new `ParsedStructure` constructor
  overload) when nothing genuinely real was already collected. This
  needed its own fix: a recursively-embedded template base can add an
  *entry* to the field list that wraps a completely empty inner result
  (e.g. `BSTSingletonSDM<T>`'s entire base chain is unresolvable nested
  templates -- `BSTSingletonSDMBase<BSTSDMTraits<T, Singleton<T>>>`),
  which made a naive `fields.isEmpty()` check say "something was found"
  when nothing real was. Tracked precisely instead via an
  `addedRealContent` flag, set only by: a real own field (`visitFields`),
  a real named base, a real *non-empty* recursive base, or a
  deterministically-added vptr.

This progression was verified via three full 1630-header sweeps:
**81 regressions → 61 (vptr fix alone) → 10 (addedRealContent fix)**,
each independently re-confirmed reproducible (re-ran the same code twice
before each fix, got identical regression lists both times).

## Known remaining regressions (10, not fixed)

All 10 share one identified pattern: a **type alias over a template with
a non-default explicit argument**, e.g.
`using BSScrapArray = BSTArray<T, BSScrapArrayAllocator>;`
(`RE/B/BSTArray.h`). For `ArmorRatingVisitor::armors`
(`BSScrapArray<TESObjectARMO*>`), the `Allocator` base is dropped
entirely (measured 56 instead of the real 64) -- `numTemplateArguments()`
on the alias-sugared type appears to only report the user-visible `T`,
not the alias's own supplied `BSScrapArrayAllocator`.

**A targeted fix was attempted and rejected**: using
`type.canonicalType()` consistently for both `numTemplateArguments()` and
`templateArgumentType()` fixed `ArmorRatingVisitor` in an isolated
single-header test (64, correct) -- but a full-sweep re-run showed it
made the *overall* regression count **worse** (10 -> 12), including
making `ArmorRatingVisitor` itself *more* wrong (40, not 56) at full
scale despite being fixed in isolation. This reproduces the same
scale-dependent unreliability pattern as Bug 3 above: a fix verified
correct on a small input can behave differently once far more libclang
traffic has accumulated over a full 1630-header sweep. The
`canonicalType()` change was reverted; this patch ships with the 10
known regressions rather than the demonstrated-worse alternative.

The 10 affected classes: `ArmorRatingVisitor`, `BSStream`, `Data190`,
`ExtraLinkedRef`, `ExtraLinkedRefChildren`, `LinkerProcessor`,
`LocalMapCamera`, `NiStream`, `RaceSexCamera`, `TESCamera` -- all measure
smaller than their real `static_assert`, all involving a `BSScrapArray<T>`
or similarly-aliased field.

## Net effect

Measured via `scripts/check_regression.py` against `coverage_baseline.json`
(patches 0001-0006) on a full 1630-header sweep:
- **10 regressions** (down from 81 in the first full-sweep review).
- **3 improvements** (`BGSPackageDataBool`, `BSShaderPropertyLightData`,
  `CombatEquipment`: MISMATCH -> OK).
- Overall OK count: 1164 -> 1227 (before any of this patch's fixes were
  applied at all, the coverage sweep's original full run showed OK=1004;
  the 1164/1227 baseline referenced here already includes patch 0006).
- The large, positive, well-verified effect described in the sections
  above (BSTArray/hkArray/GFxLogBase-family real field recovery) is real
  and validated; it is not undone by the 10 residual regressions, which
  are a narrower, separately-caused issue.

## Second attempt (this session, attempt 2 of 2 per internal working notes' rule) -- confirms this is NOT a fixable code bug at the Java layer

Followed this file's own recommendation above: wrote a minimal, isolated
libclang C program (no Java/Panama FFI involved at all -- links directly
against `libclang.so`) against the real
`RE::ArmorRatingVisitor::armors` field
(`BSScrapArray<TESObjectARMO*>` = `BSTArray<TESObjectARMO*,
BSScrapArrayAllocator>`), printing every template-argument index for
both the sugared type and `clang_getCanonicalType()`'s result. Result,
100% reproducible in isolation:

```
sugared numTemplateArguments = 1
  sugared arg[0] = TESObjectARMO *
canonical numTemplateArguments = 2
  canonical arg[0] = RE::TESObjectARMO *
  canonical arg[1] = RE::BSScrapArrayAllocator
```

Confirmed this is NOT an index-offset problem (the recommendation
above's hypothesis) -- it's genuinely a *count* difference: the sugared
(alias) type simply doesn't expose the alias's own supplied second
argument at all, while the canonical type correctly reports both,
positionally matching the primary template's parameter order. Also
confirmed with a second probe (`RE::AIProcess::actorValueCache`, a plain
`BSTArray<CachedValueData>` relying on the *default* allocator) that
canonical correctly fills in the true default (`BSTArrayHeapAllocator`)
there too -- so canonical is strictly more complete than sugared for
this purpose, in both the aliased-non-default and genuinely-defaulted
cases.

Given that, hypothesized that the ORIGINAL `canonicalType()` fix
attempt's full-sweep regression (10 -> 12) was caused by changing
`Type.numTemplateArguments()`/`Type.templateArgumentType()` themselves
to always operate on `canonicalType()` internally -- a change with global
blast radius, affecting every caller of those two shared wrapper methods
anywhere in the codebase, not just this one base-resolution call site.

**Tested that hypothesis directly**: reapplied 0001-0007, then made a
*minimally scoped* fix -- computing `type.canonicalType()` as a single
local variable inside `SourceParser.parseFieldsFromType`'s base-walking
loop only, and using it just for the `numTemplateArguments()`/
`templateArgumentType()` calls at that one call site. `Type.java` and
every other call site were left completely untouched.

**Result: identical failure, reproduced via a structurally different
code path.** A full 1630-header sweep with this scoped fix gave **12
regressions, 3 improvements** -- worse than the unscoped attempt, not
better, and `ArmorRatingVisitor` itself measured **40** (not the correct
64, and not even the pre-fix 56) -- the *exact* wrong number the
original unscoped attempt's writeup reported for the same class. Since
this fix touched nothing shared, "global blast radius" is now ruled out
as the explanation.

**Conclusion**: the discrepancy between "verified correct in an isolated
single-header libclang probe" and "wrong at full-1630-header-sweep
scale" is not explained by anything in this codebase's Java layer -- two
structurally different attempts at using `canonicalType()` for this
exact purpose both worked in isolation and both failed the same way at
scale. This is the same category of unresolved scale-dependent
libclang/Panama-FFI behavior as "Bug 3" above
(`clang_Type_getSizeOf` giving different answers depending on prior call
volume) -- not yet root-caused, and two independent attempts strongly
suggest it won't be fixable by adjusting which Java-level API calls are
made, since the identical API call (`clang_getCanonicalType` +
`clang_Type_getTemplateArgumentAsType`) behaves correctly in isolation
and incorrectly at scale regardless of which code path invokes it.

## THIRD investigation (2026-08-24, after the JDK/toolchain fix): the "scale-dependent libclang/Panama behavior" theory is DISPROVEN — this is a deterministic pipeline logic bug

Two platform-level root causes were found and fixed (see
`patches/0010-jdk22-ffm-final-api.md` for the full story):

1. **The "-Xint requirement" was never a Panama bug.** LLVM's crash-recovery
   SIGSEGV handler was intercepting HotSpot's benign implicit-null-check
   SIGSEGVs in JIT-compiled code and killing the JVM. Fixed with
   `LIBCLANG_DISABLE_CRASH_RECOVERY=1`; the pipeline now runs JDK 25 +
   full JIT, ~3-4x faster per sweep.

2. **libclang is deterministic and correct at full-sweep scale.** A pure-C
   probe (no Java) parsing the identical 1630-header umbrella TU with
   identical flags queried all 10 regressed classes and template-arg
   introspection before and after sweep-scale traffic over all 3,445
   record definitions: every answer stable and correct
   (sizeof(ArmorRatingVisitor)=64; canonical BSTArray reports both args
   including the 24-byte BSScrapArrayAllocator).

Then the critical experiment: the minimally-scoped canonicalType fix was
re-applied and full-swept **on JDK 25 + JIT + final FFM**. Result:
`ArmorRatingVisitor` measures **40 — the exact same wrong number as on
JDK 21 -Xint preview FFM.** Two completely different JVM/FFM
implementations produce identical wrong output, and pure C proves the
clang answers feeding it are right. Conclusion: **this was never
nondeterminism and never libclang — it is a deterministic, scale-dependent
logic bug in this pipeline's own composition step** (the reported sizes
are Ghidra-composed struct sizes, not clang sizeof values; "isolated
test" vs "full sweep" differ in header/type registration order, not in
clang behavior).

Where to look (unverified but specific): 40 = 64 - 24 = exactly
sizeof(BSScrapArrayAllocator) — the canonical fix correctly *finds* the
allocator base, but its embedded contribution resolves to nothing at full
scale. Canonical spellings are fully qualified
(`RE::BSTArray<RE::TESObjectARMO *, RE::BSScrapArrayAllocator>`) while
sugared spellings are not; the `anon_tmpl_<hash-of-spelling>` synthetic
naming and TypePool's string-keyed dedup/normalization (which only strips
a *leading* `RE::`, not the ones inside template argument lists) treat
these as different types, so first-registration-wins caching can pin an
empty/opaque variant registered earlier in the sweep. In isolation the
target header parses first and the good variant registers first — exactly
the observed isolation-vs-scale asymmetry, with no nondeterminism needed.

The current `0007-*.patch` on disk includes the canonicalType revision
(correct per the C probe); full-sweep numbers for it on JDK 25:
16 regressions / 7 improvements vs. the same patch-set-without-0007 —
still net-negative, still NOT merged, but now for a debuggable reason.

## Recommendation for whoever picks this up next (revised again — supersedes both earlier recommendations)

Do NOT investigate JVM modes, libclang versions, or FFI bindings — that
avenue is closed (see above). Instead debug the composition path:
instrument `TypePool`'s registration/normalization for the
`anon_tmpl_*` synthetics and the plain-named-base path with both sugared
and canonical spellings of the same instantiation, and check what the
full sweep registers first for `BSScrapArrayAllocator`-embedding
synthetics. Normalizing ALL `RE::` qualifiers (not just leading) out of
spellings before hashing/keying — or keying synthetics on canonical
spellings exclusively — are the obvious candidate fixes. Sweeps now take
~3-4 minutes, so iteration is cheap.

## Original (obsolete) recommendation, kept for the record

Per this investigation's internal working notes' "two focused attempts, then defer"
rule, this patch is now deferred rather than attempted a third time in
this session. Whoever picks it up next should NOT re-attempt another
Java-level algorithmic variation on `canonicalType()` -- that avenue has
now failed twice, via two structurally different code paths, both
verified correct in isolation. Instead:

- Investigate whether this is a `-Xint` interpreter-mode-specific
  artifact (this whole pipeline runs interpreted because Panama FFI
  upcalls crash under JIT -- see `DESIGN.md`'s toolchain note) -- e.g.
  does the same full-sweep discrepancy reproduce if the *isolated probe*
  is instead run against the SAME translation unit as the full 1630-
  header sweep (all headers in one TU), rather than a single-header TU?
  That would distinguish "wrong due to TU size/complexity" from "wrong
  due to JVM interpreter mode" as the actual variable.
- Consider whether the underlying libclang C API itself has known
  correctness issues with `clang_Type_getTemplateArgumentAsType` on
  alias-sugared specializations at all (search LLVM's own issue tracker
  for `clang_Type_getTemplateArgumentAsType` + alias template bugs)
  rather than assuming this pipeline's own code is at fault.
- If chasing this further, budget for the same full-sweep verification
  cost every attempt has needed here (10-15 min per iteration, this
  sandbox's background tasks have also been intermittently killed
  mid-run for unrelated reasons in about half of attempts this session).

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006 are already applied:

```bash
patch -p1 < ../../patches/0007-inline-template-base-classes.patch
```

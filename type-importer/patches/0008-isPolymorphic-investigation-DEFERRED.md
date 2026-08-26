# Bug 1 investigation: `isPolymorphic()`'s template-blindness — DEFERRED

**Status: investigated, root-caused, NOT fixed. No patch file — this is
a note, not a diff. Nothing in the vendored submodule was changed;
the working copy used for this investigation was reverted.**

## Background

From patch 0006's writeup ("Root cause #3"): `SourceParser.isPolymorphic()`
walks a base class's own declaration cursor via `clang_visitChildren` to
check for a virtual method, used to decide whether a redundant vptr
should be added on top of an already-embedded base vtable (patch 0001's
original fix). For a base that's a class-template specialization (e.g.
`FxDelegateHandler : public GRefCountBase<FxDelegateHandler,
GStatGroups::kGStat_Default_Mem>`), the specialization's own declaration
cursor gives zero children to `clang_visitChildren` (the same quirk
patch 0003 established for field extraction), so `isPolymorphic()`
incorrectly returns `false`, and a redundant vptr gets added — confirmed
to affect 5 classes across the full sweep (`HUDMenu`, `KinectMenu`,
`ModManagerMenu`, `SleepWaitMenu`, `TutorialMenu`, all via
`IMenu`/`FxDelegateHandler`).

## What was tried

Following the pattern already proven for fields/bases in patches
0003/0005/0007: fetch the PRIMARY (uninstantiated) template's declaration
via `clang_getSpecializedCursorTemplate` (added as a new binding,
mirroring patch 0007's exact usage) when `classDecl` is a specialization,
and walk that instead — real written source, so `clang_visitChildren`
works normally on it.

This got partway there. Confirmed via direct debug instrumentation
(temporary `System.err.println` of `classDecl.kind()`/`spelling()` and
the primary-template lookup result at every `isPolymorphic()` call, plus
a child-count/found/bases-found summary after each walk): for
`FxDelegateHandler`'s primary base `GRefCountBase<FxDelegateHandler,
GStatGroups::kGStat_Default_Mem>`, the primary-template fallback
correctly kicks in (`primaryTemplate.kind()=CLASS_TEMPLATE`), and its own
base-specifier (`GRefCountBaseStatImpl<Base, StatType>`, itself
dependent on `GRefCountBase`'s own template parameters) is found and
recursed into.

## Where it actually breaks

`GRefCountBaseStatImpl`'s real source (`RE/G/GRefCountBaseStatImpl.h`):

```cpp
template <class Base, class StatType>
class GRefCountBaseStatImpl : public Base
{ ... };
```

Its base is written as a **bare, unresolved template parameter** (`Base`),
not a further class-template-specialization name. Inside
`GRefCountBaseStatImpl`'s own PRIMARY template body (the only thing
`clang_visitChildren` can actually walk, per the fix above), `Base` is
not bound to anything concrete — there is no real declaration to point
`.type().declaration()` at from this vantage point. The concrete
substitution (`Base` → `GRefCountImpl<FxDelegateHandler, ...>` for this
specific instantiation) only exists on the INSTANTIATED specialization,
whose own cursor is exactly the thing that gives zero children to
`clang_visitChildren` in the first place — the fix's fallback and the
original problem collide at this second level.

Confirmed via the same debug instrumentation: the recursive
`isPolymorphic(base)` call for `GRefCountBaseStatImpl`'s "base" (`Base`)
is never actually reached with a meaningful cursor — `bases.add(...)` on
a bare template-parameter reference doesn't produce a walkable class
declaration, so the recursion silently dead-ends there rather than
reaching `GRefCountImpl`/`GRefCountImplCore` (where the real virtual
destructor lives).

## Why this is deferred, not fixed here

Resolving this properly requires positional template-argument
substitution — knowing that, for THIS specific instantiation chain,
`Base` resolves to `GRefCountImpl<FxDelegateHandler, GStatGroups::kGStat_Default_Mem>`
— which means threading through exactly the kind of
argument-substitution machinery patch 0007 built for the analogous
field/base-embedding problem. Patch 0007 got that machinery working for
its own use case only after a long, two-round investigation, and even
then hit an unresolved scale-dependent libclang/Panama-FFI reliability
issue on a narrower case (alias-over-non-default-argument) that caused
it to be deferred rather than merged. Building a second, independent
copy of that same substitution logic for `isPolymorphic()` — without
first knowing whether patch 0007's own scale-dependent issue would
resurface here too — is a genuinely separate, comparably-sized
investigation, not a small follow-on fix.

Per this investigation's internal working notes' scope discipline ("one focused attempt... defer
rather than iterate multiple rounds"), this is being left as a precisely
root-caused, actionable note rather than pursued into a second
investigation cycle right now.

## Recommendation for whoever picks this up next

Don't attempt a second isPolymorphic()-specific substitution
implementation until patch 0007's own deferred `canonicalType()`/
`clang_Type_getTemplateArgumentAsType` reliability question is resolved
(see `patches/0007-inline-template-base-classes.md`'s final
recommendation — investigating `-Xint` interpreter mode as the likely
variable, or checking LLVM's own issue tracker). If that unblocks patch
0007, its argument-substitution helper should be directly reusable here
too, since it's solving the same underlying problem (resolving a
dependent base/parameter to its concrete instantiated type). Fixing
patch 0007 first and reusing its machinery is very likely cheaper than
solving this independently.

Affected classes remain as documented in `COVERAGE_SWEEP_PLAN.md`:
`HUDMenu`, `KinectMenu`, `ModManagerMenu`, `SleepWaitMenu`,
`TutorialMenu` (each 8 bytes oversized from the redundant vptr).

## Update (v0.2 SE/VR runtime validation): real blast radius is much wider

The SE/VR runtime coverage sweeps (`RUNTIME_SE_1_5_97.md`,
`RUNTIME_VR_1_4_15.md`) re-confirmed this same bug hits every
`IMenu`-derived class, not just the 5 above — `IMenu` itself and ~34 of
its subclasses (`BarterMenu`, `BookMenu`, `ContainerMenu`, `DialogueMenu`,
`InventoryMenu`, `JournalMenu`, `MagicMenu`, `RaceSexMenu`, `StatsMenu`,
etc. — every `IMenu` subclass tracked by the sweep) are each exactly 8
bytes oversized (a couple with one additional independent +8 or +24 on
top, from their own separate issues), traced via a throwaway
`InspectGdt`-style component dump to the same root cause: `FxDelegateHandler`
resolves to 24 bytes instead of its real, `static_assert`-confirmed 16
(`vptr` field duplicated on top of the fully-embedded
`GRefCountBase<...>` base, which already contains its own inherited
vptr from `GRefCountImplCore`).

Also confirmed: **this is not VR- or SE-specific** — `FxDelegateHandler`
and `IMenu` are already `MISMATCH` in the committed AE
`coverage_baseline.json` (`actual=24/expected=16` and
`actual=56/expected=48` respectively) with the exact same off-by-8
signature. This bug is fully runtime-independent; it was just never
part of the original 39-class hotspot list, so the earlier investigation
undercounted its reach. No new root cause found here, no fix attempted
(per the recommendation above — still blocked on patch 0007's deferred
substitution-machinery reliability question); this is a scope update
only.

## Second update: full coverage-sweep MISMATCH audit — this is the single
## biggest remaining gap in the whole codebase

Grouping the AE `coverage_baseline.json`'s 178 `MISMATCH` classes (post
patch 0019) by `actual - expected` delta found one dominant cluster:
**122 of 178 (68.5%) are off by exactly +8 bytes.** Sampling confirms
this is overwhelmingly the *same* bug, not 122 independent ones — every
class checked (`GFxState`, `GWaitable`, `GFxResourceLib` directly;
`IMenu`/`FxDelegateHandler` already confirmed above; most of the
remaining `GFx*`/`GAS*`/`G*` Scaleform-UI family transitively, via
chains like `GFxMovieDef → ... → GRefCountBase<T, StatType>` or
`GFxStream : public GFxLogBase<GFxStream>`) ultimately derives, directly
or transitively, from a class-template-specialization base with virtual
methods — exactly `isPolymorphic()`'s known blind spot. A shallow
direct-base-only check (no transitive closure, given the size of this
investigation) only confirmed 48/122 directly; the other 74 need a
transitive base walk to individually confirm, but every manually-checked
sample matches, and no counter-example (a +8 class with a demonstrably
different cause) was found.

**Two small, deliberately unverified exceptions worth flagging** for
whoever picks this up next: `Archive` and `BGSDefaultObjectManager` use
*multiple* inheritance where a template-specialization base is the
*second*, non-primary base (`BGSDefaultObjectManager : public TESForm,
public BSTSingletonImplicit<BGSDefaultObjectManager>`) — a genuinely
different shape than the single/primary-inheritance case this
investigation root-caused, and worth checking separately before
assuming they're the same bug (they might be a distinct, possibly more
tractable, MI-specific instance).

**No fix attempted here either** — this is a scope-quantification pass,
not a third attempt at the underlying bug (still blocked on the same
patch 0007 dependency as above). The practical upshot: **this one
already-diagnosed, already-deferred issue is very likely the single
highest-leverage remaining gap in the entire coverage sweep** — fixing
it (once patch 0007's blocker clears) would likely resolve on the order
of 100+ classes in one patch, more than all other remaining `MISMATCH`
clusters combined. Worth prioritizing patch 0007's libclang/JIT
reliability investigation specifically because of this, not just for
its own sake.

## Correction: patch 0007 is NOT a prerequisite — it's obsolete and regressive

The "blocked on patch 0007" framing above (both updates) was tested
directly and found wrong. Re-applying patch 0007 as-is on top of current
mainline (patches 0001-0018) **regresses an already-`OK` class**:
`ArmorRatingVisitor` measures 64/64 (`OK`) in the current baseline, and
40 (missing exactly `sizeof(BSScrapArrayAllocator)`) with 0007 applied.
0007 predates patches 0009/0015/0016, whose more general field-embedding
mechanism has since superseded 0007's own approach for this class's shape
(`BSTArray<T, Allocator>`-style container embedding) — 0007 should not be
revived for any purpose, including "just for its bindings/investigation
machinery." It has been reverted from the working tree.

**This class of bug's actual prerequisite was only three self-contained
libclang bindings 0007 introduced** (`Cursor.specializedTemplate()`,
`Type.numTemplateArguments()`, `Type.templateArgumentType()`) — pure
additions to `Cursor.java`/`LibClang.java`/`Type.java` with no interaction
with 0007's `ParsedStructure`/`TypePool`/`SourceParser` field-embedding
changes. Patch 0021 cherry-picks exactly those three bindings and adds a
new, self-contained `isPolymorphic(Type)` overload that reuses them for
this bug specifically — fixing one level of the substitution chain (10-11
of the 122 classes). See `patches/0021-fix-ispolymorphic-template-specialization.md`
for the fix, its `GCPP_DEBUG_POLY` trace confirming exactly where the
substitution wall still is for the remaining classes (`FxDelegateHandler`/
`IMenu` included), and why that remaining wall needs textual/structural
substitution into a nested template-id — a comparably-sized follow-on
investigation, not a small extension.

## Second correction: the remaining wall was a one-line gating bug, not a second substitution engine

0021's writeup (and the paragraph directly above) concluded the remaining
wall needed "textual/structural substitution into a nested template-id" --
rewriting `STAT` to its concrete value inside `GRefCountBaseStatImpl<GRefCountImpl, STAT>`
to derive a genuine instantiation. **This was wrong.** Patch 0022 found the
actual cause: `clang_Type_getNumTemplateArguments`/`getTemplateArgumentAsType`
already work correctly on a type like `GRefCountBaseStatImpl<GRefCountImpl, STAT>`
even though it's only partially dependent (`STAT` unresolved,
`GRefCountImpl` concrete) -- they read the argument list directly off the
type's own structure, independent of whether `type.declaration()` resolves
to a genuine specialization decl. 0021's code gated extraction behind
exactly that declaration check (`isSpecialization`), which is false for a
partially-dependent type, and silently skipped extraction as a result. No
textual rewriting, no second substitution engine -- removing the gate was
sufficient. This fixed `FxDelegateHandler`, `IMenu`, and 86 other classes
(88 total per runtime) -- more than 7x patch 0021's own count. See
`patches/0022-fix-ispolymorphic-partial-dependent-args.md` for the full
writeup. Filed here so nobody re-derives "this needs bigger machinery" a
third time.

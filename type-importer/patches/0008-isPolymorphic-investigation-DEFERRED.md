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

Per `LOOP_GOAL.md`'s scope discipline ("one focused attempt... defer
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

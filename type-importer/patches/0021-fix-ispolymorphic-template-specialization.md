# Patch 0021: `isPolymorphic()` sees through one level of class-template specialization

Partial fix for the bug documented in `patches/0008-isPolymorphic-investigation-DEFERRED.md`.
Fixes 10-11 classes (confirmed per-runtime below) of the 122/178 (68.5%) AE
`MISMATCH` classes carrying a spurious +8-byte redundant vptr. Does **not**
fix the majority of that cluster, including the two classes (`FxDelegateHandler`,
`IMenu`) 0008's writeup used as its running example -- see "What's still
deferred" below.

## Root cause (recap from 0008, now fixed for one level)

`SourceParser.isPolymorphic(Cursor classDecl)` decides whether a class needs
a brand-new synthetic vptr field, or whether its virtual methods extend a
vtable already inherited from a base, by walking `classDecl`'s children
looking for a virtual method/destructor, recursing into base-specifiers.
For a base that is a class-template **specialization** (e.g.
`GRefCountBase<FxDelegateHandler, GStatGroups::kGStat_Default_Mem>`),
`clang_visitChildren` on the specialization's own declaration cursor gives
**zero children** (the same quirk patch 0003 established for field
extraction) -- so the walk silently concludes "no virtual method, no bases"
for any such base, even one that plainly inherits a vtable, and a redundant
vptr gets added on top of the base's own (correctly embedded, per patches
0003/0005/0009/0015/0016) real vtable.

## The fix

`isPolymorphic(Cursor)` now delegates to a new `isPolymorphic(Type)`
overload. When the declaration is a specialization, it falls back to the
**primary** (uninstantiated) template's declaration -- real written source,
so `clang_visitChildren` walks it normally (the same fallback pattern
patch 0007 established for base-class field embedding, and the same
Cursor/LibClang/Type bindings it added: `specializedTemplate()`,
`numTemplateArguments()`, `templateArgumentType()` -- reused here verbatim,
see "What was NOT reused from 0007" below). Any base written as a bare
reference to one of the primary template's own parameters (e.g.
`GRefCountBaseStatImpl<Base, StatType>`'s own "Base") is positionally
substituted with this **specific instantiation's** concrete argument type
via `clang_Type_getTemplateArgumentAsType`, then recursed into as a `Type`
(not just a `Cursor`), so a chain several specializations deep resolves all
the way down to a plain, non-template class where the ordinary cursor walk
finds the real virtual destructor.

Confirmed via a `GCPP_DEBUG_POLY=<substring>` trace (added alongside this
fix, same pattern as patches 0013/0014's `GCPP_DEBUG_DEPS`) that this
correctly resolves e.g. `MenuControls`'s and `PlayerControls`'s base chains
down to their real polymorphic root.

## What was NOT reused from patch 0007

Patch 0007 attempted this SAME substitution machinery for base-class
**field embedding** (constructing real `ParsedStructure` content for a
template-specialization base) and was deferred after a confirmed
regression: re-testing it directly this pass showed it regresses
`ArmorRatingVisitor` (`OK` in the current baseline) from 64 down to 40 --
see the "0007 disproven as prerequisite" correction below and the amended
note in `patches/0008-*-DEFERRED.md`. This patch deliberately does **not**
revive any of 0007's `ParsedStructure`/`TypePool`/`anon_tmpl_` naming
changes. `isPolymorphic(Type)` only answers a yes/no question and never
constructs or registers a `ParsedStructure`/`ParsedType` -- it carries none
of 0007's regression risk. Only the three self-contained libclang bindings
(`Cursor.specializedTemplate()`, `Type.numTemplateArguments()`,
`Type.templateArgumentType()`) were cherry-picked from 0007's diff; none of
its `SourceParser`/`TypePool`/`ParsedStructure` changes were touched.

## Correction to 0008's own writeup: patch 0007 is not a prerequisite

0008's writeup states fixing it "should be blocked on patch 0007's own
deferred... reliability question" being resolved first, on the theory that
0008 needs the same argument-substitution machinery 0007 was building. This
session re-tested that assumption directly: applying 0007 as-is against
current mainline **regresses** an already-`OK` class (`ArmorRatingVisitor`,
64 -> 40), because 0007 predates patches 0009/0015/0016, whose more general
field-embedding mechanism has since superseded it for that class's shape
(`BSTArray<T, Allocator>`-style container embedding). 0007 should not be
revived for any purpose; `patches/0008-*-DEFERRED.md` has been amended to
correct this. The actual prerequisite for 0008 was never 0007 as a whole --
only the three narrow libclang bindings it introduced, which this patch
cherry-picks directly without any of the rest of 0007's diff.

## What's still deferred: nested template-parameter references

This fix only substitutes a base spelled as a bare, standalone reference to
one of the primary template's own parameters (e.g. `Base` alone). It does
**not** handle a parameter appearing nested inside another template-id, which
is exactly `FxDelegateHandler`'s and `IMenu`'s actual shape and why they are
NOT fixed by this patch:

```
template <class T, std::uint32_t STAT>
class GRefCountBase : public GRefCountBaseStatImpl<GRefCountImpl, STAT> { ... };
```

Walking `GRefCountBase`'s own primary template body finds one base,
spelled (as literal clang output) `GRefCountBaseStatImpl<GRefCountImpl, STAT>`.
This spelling is not equal to any single parameter name in `paramNames`
(the whole base is not a bare parameter reference), so no substitution is
attempted, and `STAT` stays an unresolved symbolic reference when the walk
recurses one level deeper. Confirmed via `GCPP_DEBUG_POLY=GRefCount`:

```
[POLY] type=RE::GRefCountBase<RE::FxDelegateHandler, 2> found=false numBases=1 paramNames=[T]
[POLY] type=RE::GRefCountBase<RE::FxDelegateHandler, 2> base=GRefCountBaseStatImpl<GRefCountImpl, STAT> -> concrete=GRefCountBaseStatImpl<GRefCountImpl, STAT>
[POLY] type=GRefCountBaseStatImpl<GRefCountImpl, STAT> found=false numBases=1 paramNames=[Base]
```

(the second line's `-> concrete=` unchanged from `base=` shows no
substitution fired; the walk dead-ends on the bare `Base` parameter at the
next level down, since `isSpecialization` is false there and no argument
list is available to substitute from). This is the **exact same
limitation** patch 0007 documented for `hkArray<T> : public hkArrayBase<T>`
("`hkArrayBase<T>` doesn't match the simple bare-parameter-name
substitution... since T only appears nested inside another template
application, not standing alone as the base's entire spelling") -- this
patch's `[POLY]` trace above is the first concrete repro of that same
limitation for `isPolymorphic()` specifically. Resolving it requires
textual/structural substitution into a template-id (rewriting `STAT` to
`2` inside `GRefCountBaseStatImpl<GRefCountImpl, STAT>` to get a genuine
instantiation to look up or re-derive), not just a positional swap -- a
comparably-sized follow-on investigation, not a small extension of this
patch. `FxDelegateHandler`, `IMenu`, and every other class in the 122-class
cluster that resolves through this same nested-parameter shape remain
`MISMATCH`, unchanged by this patch.

## Correctness fix caught in review, before it could bite silently

The primary-template child walk originally collected only
`TEMPLATE_TYPE_PARAMETER` cursors into the positional parameter-name list
used for substitution. `GRefCountBase<class T, std::uint32_t STAT>` mixes a
type parameter (`T`) with a **non-type** parameter (`STAT`, cursor kind
`NON_TYPE_TEMPLATE_PARAMETER`) -- collecting only the type-parameter kind
silently misaligns the positional list (`[T]` instead of `[T, STAT]`)
against `clang_Type_getTemplateArgumentAsType`'s own argument indexing
whenever a template mixes the two parameter kinds. Fixed by collecting
`TEMPLATE_TYPE_PARAMETER`, `NON_TYPE_TEMPLATE_PARAMETER`, and
`TEMPLATE_TEMPLATE_PARAMETER` uniformly, in declaration order. Verified this
had no effect on the measured result for this patch's own fixed classes
(none of them currently hit the misalignment), but left unfixed it would
have been a **latent** correctness hazard for the very next mixed-parameter
case someone's fix or investigation touches.

## Blast radius: 10-11 classes fixed, one pre-existing bug unmasked

Full 1630-header sweep, all three runtimes, against the committed
`coverage_baseline*.json` files (updated by this patch):

- **AE**: 10 improvements (`MISMATCH` -> `OK`), 1 regression, 1052 newly-seen
  entries (see below).
- **SE**: 11 improvements, 1 regression (same set, plus `BSAnimationGraphManager`,
  which has ground truth on SE/VR but not AE), 1052 newly-seen.
- **VR**: 11 improvements (same as SE), 1 regression, 1052 newly-seen.

Improvements: `BGSProcedureTreeProcedure`, `BGSProcedureTreeSequence`,
`GASEnvironment`, `GASFunctionObject`, `GASObject`,
`GASUserDefinedFunctionObject`, `GFxStream`, `MenuControls`,
`PlayerControls`, `TES::SystemEventAdapter` (all runtimes), plus
`BSAnimationGraphManager` (SE/VR only -- AE has no `static_assert` ground
truth for it, so the same underlying fix there shows as
`NO_GROUND_TRUTH` -> `NO_GROUND_TRUTH`, invisible to the improvements
list, not a difference in the fix's actual effect between runtimes).

`FxDelegateHandler`, `IMenu`, `ArmorRatingVisitor`, and the patch 0019
fixes (`BaseExtraList`, `ExtraDataList`) are all unchanged, confirming no
interaction with unrelated prior patches.

**1052 "newly seen" entries** (present in this pass's fresh sweep,
absent from the prior baseline -- not a regression per `check_regression.py`'s
own definition) are `<ClassName>_vtable` structs that previously were never
created at all for any class whose `isPolymorphic()` already correctly
returned `true` *before* this patch (patch 0001's original vtable
registration and the redundant-vptr-suppression decision were coupled in
the same `if` branch, so a class extending an inherited vtable never got
its own vtable-naming struct registered, even though that's independently
useful Ghidra-visible virtual-method typing regardless of whether a new
vptr field is emitted). This patch decouples the two: `ParsedVtable`
registration now happens unconditionally whenever a class has virtual
methods; only the `vptr` **field** is gated on `primaryBaseIsPolymorphic`.
This was necessary to avoid a separate class of regression: without it,
every class this patch newly identifies as correctly extending an inherited
vtable would have *lost* its already-existing `<Class>_vtable` naming
struct (16 such classes hit this in an earlier iteration of this patch,
before the decoupling -- e.g. `PlayerControls_vtable`,
`GASObject_vtable`, `Main_vtable` all going from a real, if
`NO_GROUND_TRUTH`, entry to fully `UNRESOLVED`). After decoupling, those
16 keep their exact baseline sizes, and the same registration now also
fires for the ~1036 other classes whose base was already correctly detected
as polymorphic before this patch but which, by the same old coupling,
never got their own vtable-naming struct either -- a pure net gain in
Ghidra-visible naming, not a new behavior this patch invented.

## The one regression: pre-existing bug unmasked, not caused by this patch

`BGSPackageDataBool: MISMATCH (actual=8) -> EMPTY (actual=1)`.

The baseline's `actual=8` for this class was **already wrong** (real size
per `static_assert` is 16) -- and 8 is exactly the size of one vptr alone.
`BGSPackageDataBool : public BGSNamedPackageData<IPackageData>` has its own
virtual destructor and several overrides; before this patch,
`isPolymorphic()`'s blindness to template-specialization bases meant
`BGSNamedPackageData<IPackageData>` was (wrongly) judged non-polymorphic,
so `BGSPackageDataBool` got its own (redundant) vptr -- which happened to
be the *only* non-zero content in the struct, since
`BGSNamedPackageData<IPackageData>`'s own inline-embedded field content
was **already** resolving to nothing (a separate, pre-existing
template-base-embedding gap, unrelated to `isPolymorphic()`). The redundant
vptr was, by coincidence, masking that base's own already-broken embedding
behind a non-zero (if still wrong) size. This patch correctly suppresses
the now-redundant vptr, and with nothing else contributing, the class
drops to `EMPTY`. This is the same "fixing one bug unmasks a different,
pre-existing one" pattern already documented for patches 0006/0009/0011/0015
-- the underlying `BGSNamedPackageData<T>` embedding gap is a distinct,
unfixed bug, not something this patch introduced or should be blocked on.

## Verification

Full 1630-header sweep, all three runtimes (`ENABLE_SKYRIM_AE`,
`ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_VR`), against
`coverage_baseline{,_se,_vr}.json` via `check_regression.py`: 1 regression
(above, precedented/accepted), 10-11 improvements per runtime, 0 other
changes. `coverage_baseline*.json` updated to lock in the 10-11
improvements and the one accepted regression.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, 0011-0018 (and 0010 on JDK 22+) are already applied:

```bash
patch -p1 < ../../patches/0021-fix-ispolymorphic-template-specialization.patch
```

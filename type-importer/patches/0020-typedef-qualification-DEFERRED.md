# Patch 0020 (DEFERRED): qualify nested typedef registration

**Status: deferred.** No `.patch` file -- the candidate fix below is a net
regression and was not merged. This document exists so the next attempt
doesn't repeat the same investigation from scratch.

## The bug this was trying to fix

`RE::TESClimate` declares a nested type alias:

```cpp
class TESClimate : public TESForm, public TESBoundObject {
public:
    struct SkyObjects {
        using SkyObject = RE::SkyObject;   // (illustrative -- see actual header)
        ...
    };
    ...
};
```

`SourceParser.parseTypedef()` registers every `using`/`typedef` alias under
its **bare** name in `TypePool`'s flat string-keyed pool -- unlike structs,
unions, and enums, which patches 0011 and 0014 already qualified by their
enclosing record (`Outer::Inner`) specifically to avoid this collision
class. A nested `SkyObject` typedef inside `TESClimate::SkyObjects` collides
with the unrelated top-level `RE::SkyObject` class under the same bare pool
key, and `DataTypeConflictHandler`'s last-write-wins semantics let whichever
one parses second silently clobber the other.

This is the same collision shape patches 0011/0014 fixed for structs/unions
and enums respectively -- typedefs were the one record-nested category left
unqualified.

## The candidate fix

`parseTypedef()` was changed to call `recordQualifiedName(cursor)` (the same
helper 0011/0014 use) instead of `cursor.spelling()`, so a nested alias
registers as `TESClimate::SkyObjects::SkyObject` instead of bare
`SkyObject`.

## Why it doesn't converge: full-sweep result

Full 1630-header AE sweep: **8 improvements, 25 regressions.** Net negative.
Not merged, per the project's "never merge a net-negative patch" rule.

The 8 improvements were exactly the intended target (`TESClimate` and five
other classes with the same nested-alias-shadows-a-toplevel-name shape) plus
two incidental fixes. The 25 regressions have no plausible connection to
name collisions -- classes like `NiColorData`, `NiFloatData`,
`GRenderer::BitmapDesc`, and `hkp3AxisSweep::hkpBpEndPoint` went from
`OK`/`NO_GROUND_TRUTH` straight to `EMPTY` (i.e. the entire struct stopped
resolving), which is the signature of a *resolution*-side lookup failing,
not a registration key being subtly wrong.

## Root cause of the regressions, confirmed by tracing

Ran a narrow smoke parse (`RE/N/NiColorData.h` + `RE/N/NiColorInterpolator.h`,
AE runtime) with `GCPP_DEBUG_DEPS=NiColorData` set, which enables the
dependency-tracing log `TypePool.checkDependenciesFulfilled` added for
patches 0013/0014. It surfaced the exact blocker:

```
[DEPS] 'NiColorData' blocked by 'KeyType' exactNameCandidates=0 parsedEntry=none
```

`RE/N/NiColorData.h` contains:

```cpp
class NiColorData : public NiObject {
public:
    using KeyType = NiColorKey::KeyType;   // nested alias, forwards to another record's nested type
    ...
    KeyType type;   // field references the alias by its BARE name, in-scope
};
```

With the candidate fix, the `using KeyType = ...` declaration registers
under the qualified key `NiColorData::KeyType`. But the field `KeyType type;`
is resolved via whatever spelling-lookup path `SourceParser`/`TypePool` uses
for field types, and that path still looks up the **bare** `KeyType` --
which no longer has an entry, since qualification moved it. The class-scope
field reference to its own class's alias is exactly the case a
registration-only qualification change breaks, and it silently turns the
whole `NiColorData` struct into `EMPTY` because the field type comes back
unresolved.

This matches the mechanism patch 0014 had to handle for enums: qualifying
the *registration* side is only half the fix. Patch 0014's writeup notes
`TypePool.getType` was extended to "materialize an exactly-matching parsed
entry on demand... both for the original name and for each peeled suffix"
-- i.e. a **resolution-side** companion change so bare in-scope references
still find the now-qualified entry. The candidate fix here only touched
`parseTypedef()`'s registration call; it did not extend the corresponding
resolution/lookup path (`fieldTypeSpelling` or equivalent) to canonicalize
a bare typedef reference to its qualified form the way it already does for
nested *record* references (that method's own comment notes it
canonicalizes nested record spellings to match qualified registration keys,
and explicitly bails on template spellings -- whether it does the
equivalent for a typedef reference is the open question the next attempt
must answer first).

## What a second attempt needs, if picked back up

1. Read `fieldTypeSpelling` (or whatever resolves a field's declared type
   string to a pool lookup) and confirm whether it currently canonicalizes
   an in-scope bare typedef reference to its enclosing record's qualified
   form. If not, that's the missing half.
2. Any fix needs the same two-part shape 0014 used: qualify the
   registration **and** extend resolution to still find a bare in-scope
   reference (either by canonicalizing the reference at lookup time, or by
   on-demand materializing a bare-name pool entry that forwards to the
   qualified one, as 0014 did for enums).
3. Do not attempt a registration-only variation (e.g. "only qualify when a
   collision is detected") without first fixing the resolution side --
   `NiColorData`'s failure has nothing to do with collision detection; it's
   a plain in-scope self-reference that any qualification of `KeyType`
   breaks regardless of whether a collision exists elsewhere.
4. Re-verify with the same full 1630-header AE sweep + `check_regression.py`
   before considering this for merge.

## Blast radius / current state

- `TESClimate::SkyObjects::SkyObject` collision remains unfixed --
  `TESClimate` and the ~5 other affected classes stay whatever bucket they
  were in before this investigation (not a hotspot-list class; not
  regression-gated).
- The submodule (`vendor/GhidraClangPoweredParse`) has been reverted to
  pristine; no code from this investigation is applied.
- `coverage_baseline.json` was **not** touched -- it still reflects patch
  0019 as the most recent landed change.

## Bigger picture from this grinding pass

Across this pass's broader-than-hotspot-list coverage-sweep sampling
(patch 0019 plus the investigations documented in `patches/0008-*-DEFERRED.md`'s
two updates and this document), essentially every remaining `MISMATCH`
cluster sampled traces back to one of three root causes, all in the same
area of the parser (template-base handling / typedef-and-enum registration
vs. resolution symmetry):

- **Patch 0007** (deferred): container/wrapper templates
  (`BSTArray<T>`, `hkArray<T>`, `hkInplaceArray<T,N>`) whose storage lives
  entirely in template base classes that aren't fully inline-embedded.
- **Patch 0008** (deferred): `isPolymorphic()` can't see an inherited
  virtual method through a class-template-specialization base, adding a
  spurious vptr -- confirmed to affect 122+ classes (68.5% of all
  `MISMATCH` classes), the single highest-leverage remaining gap.
- **This document (0020, deferred)**: nested-typedef registration
  qualification is missing a resolution-side companion fix, mirroring
  0014's own two-part shape.

The remaining ~64% coverage gap is not a long tail of independent bugs --
it's three known, well-understood root causes, all blocked on the same
underlying template/lookup machinery. Further blind cluster-sampling is
low-yield at this point; the highest-value next step for whoever picks
this back up is a focused attempt at one of these three (0008 has the
largest confirmed blast radius) rather than searching for a fourth.

## Second attempt (registration-guard, no qualification): also fails, much worse

A different, narrower candidate was tried in a later session: instead of
qualifying typedef registration (this document's original candidate),
leave registration untouched but add a guard to `TypePool.addParsedType`
refusing to let an incoming `ParsedTypedef` overwrite an existing
`ParsedStructure`/`ParsedUnion`/`ParsedEnum` entry of the same bare name --
reasoning that a typedef is "just an alias" and should never legitimately
clobber a concrete type.

This was motivated by a fresh coverage-sweep finding: `SkyObject` (the
real, top-level `RE::SkyObject` class, base of `Sun`/`Moon`/`Stars`/
`Atmosphere`/`Clouds`) was resolving as a 4-byte `TypedefDB` entry instead
of the real 16-byte struct -- confirmed via direct `.gdt` inspection. Root
cause: `TESClimate::SkyObject` is `using SkyObject = SkyObjects::SkyObject;`,
an alias for a *different*, unrelated nested enum
(`TESClimate::SkyObjects::SkyObject`, itself correctly qualified by patch
0014's enum handling) -- this specific typedef, at `TESClimate`'s own
scope, registers under the bare name `SkyObject` and clobbers the
unrelated top-level class of the same name, purely by parse order.

**Full 1630-header AE sweep result: 8 improvements, 238 regressions.**
Far worse than this document's original candidate (25 regressions). The
guard is *semantically* narrower than blanket qualification (it doesn't
touch resolution or the vast majority of typedef registrations at all),
but its **practical** blast radius is enormous: the overwhelming majority
of typedef-vs-concrete-type bare-name collisions in this codebase are NOT
bugs -- they're the intended, load-bearing mechanism by which a
`using Alias = RealType;` declaration makes `Alias` resolvable by name for
every field/base/return-type that references it as `Alias` rather than
`RealType`. Refusing that overwrite breaks every one of those (`TESClass`,
`TESNPC`, `TESObjectARMO`, `bhkCollisionFilter`, and ~230 more), while
fixing only the one genuine collision this pass was looking for
(`SkyObject` and its 4 direct beneficiaries, `Sun`/`Moon`/`Stars`/
`Atmosphere`/`Clouds`).

This confirms, independently and more strongly, this document's original
conclusion: there is no registration-only fix here, narrow or broad. Any
real fix needs to distinguish a **genuine name collision between two
unrelated entities** (rare -- `SkyObject` may be close to the only instance
in this codebase) from **an intentional alias relationship** (the common
case, load-bearing) -- and that distinction cannot be made from the
registration side alone, since both look identical there (an incoming
typedef with the same bare name as an existing entry). It requires either:

- Detecting the collision by comparing what the two entries' *canonical/
  underlying types* actually resolve to (if the typedef's target is NOT
  the existing entry itself or a wrapper around it, it's a genuine
  collision, not an intentional alias) -- expensive and not yet attempted,
  or
- The full two-part registration+resolution fix this document already
  recommends, scoped much more narrowly than "qualify every typedef" --
  e.g., detect the SPECIFIC collision (canonical-type mismatch, as above)
  and qualify *only* that one typedef's registration, plus verify no
  in-scope bare self-reference to it exists in the same translation unit
  before doing so.

Given the scale of this second attempt's own failure (238 regressions from
a supposedly "safe, narrow" change), this bug is confirmed to be
substantially harder than patches 0022/0023 (both genuine one-line gating
bugs) -- not a shallow fix waiting to be found. Submodule reverted to
pristine; no code from this attempt is applied. `coverage_baseline.json`
untouched.

# Patch 0025: recover base-contributed content that `parseFieldsFromType` silently dropped (patch 0007's cluster, closed via a different mechanism)

## Context: this supersedes patch 0007, not extends it

Patch 0007 ("inline base classes of class-template-specialization fields/
bases") was deferred after two attempts, both blocked by what its own
writeup concluded was a scale-dependent registration-order bug in
`anon_tmpl_*` synthetic-type keying. Reopening that cluster -- a deliberate
decision, not a blind retry -- started by re-reading 0007's own
"recommendation for whoever picks this up next" -- but the codebase has
been substantially restructured since 0007 was written (patches
0011-0018 reworked template-field/base handling into a purely recursive
**inline-embed by value** scheme). Confirmed empirically before writing
any code:

- `anon_tmpl_*` is now just a cosmetic debug name on an unregistered,
  directly-embedded `ParsedStructure` -- it is never used as a `TypePool`
  lookup key anywhere in the current code. The "first-registration-wins
  keying bug" 0007's THIRD investigation diagnosed **does not exist** in
  this architecture; there is nothing left to fix along that path.
- All 10 classes patch 0007's doc listed as "known remaining
  regressions" (`ArmorRatingVisitor`, `BSStream`, `ExtraLinkedRef`, etc.)
  are already `OK` in the current `coverage_baseline.json`, closed by
  later patches (0015/0016) via an unrelated mechanism.

So there was no bug left matching 0007's own diagnosis to fix. Instead,
a fresh full-sweep MISMATCH review (following the "container/wrapper-
template embedding" lead as stated, not 0007's specific old symptom)
found a **different, currently-live** bug in the same problem area
(template specializations used as fields/bases), root-caused and fixed
below.

## The problem this addresses

A live full 1630-header sweep (patch set 0001-0024, no 0007) found two
classes of `-16` byte deltas:

- `HandlerDictionary`, `ResponseDictionary` (both plain, non-template
  classes deriving from a `BSTObjectDictionary<...>` specialization):
  `expected=0x50 actual=0x40`.
- Every `hkInplaceArray<T,N>`-having class (`hkpAllCdPointCollector`,
  `bhkCharacterProxy`, `bhkCharProxyController`,
  `bhkCharacterPointCollector`, `hkpAgentNnTrack`, and transitively
  `hkpSimulationIsland`): each measured exactly 16 bytes short of its
  own `static_assert`.

## Root cause, confirmed empirically

`SourceParser.parseFieldsFromType` (the inline-embedding mechanism used
whenever a field or base is itself a class-template specialization)
calls `type.visitFields()` (`clang_Type_visitFields`), which walks
`CXXRecordDecl::field_begin()/field_end()` directly. By design this
reports **only the type's own direct `FIELD_DECL`s** -- never anything
contributed by ITS OWN base classes.

Two real, concrete shapes hit this:

- `BSTObjectDictionary<T, Key, MissPolicy, InitializationPolicy>`
  (`RE/B/BSTObjectDictionary.h`) has three bases --
  `MissPolicy<T,Key>` and `InitializationPolicy<T,Key>` (each an empty
  interface with a virtual destructor, 8-byte vptr) plus
  `BSTSingletonSDM<...>` -- contributing 17 bytes ahead of its own
  `pad11`/`pad12`/`pad14`/`objectDefinitions`/`definitionLock` fields.
  `visitFields()` finds only the latter five; the two vptrs (16 of the
  17 bytes) were silently dropped.
- `hkInplaceArray<T,N> : hkArray<T,Allocator> : hkArrayBase<T>`
  (`RE/H/hkArray.h`) has exactly ONE field of its own
  (`T storage[N]`, at real offset `0x10`) -- the real `_data`/`_size`/
  `_capacityAndFlags` trio (16 bytes) all live in `hkArrayBase<T>`,
  a base two levels up. `visitFields()` finds only `storage`.

The existing `fields.isEmpty()` opaque-padding fallback (already in
this function, correct for a pure-interface base like `BSTEventSink<T>`
with NO own fields at all) never fires in either case, because
`visitFields()` DOES find real own fields -- just not the
base-contributed ones sitting ahead of them in memory.

## The fix

`clang_Cursor_getOffsetOfField` (the same ground-truth API already
trusted for patches 0023/0024's EBO fixes) gives each visited field's
real, compiler-computed byte offset. If the **first** field callback's
offset is nonzero, everything before it belongs to base classes this
walk cannot see -- prepend one opaque `char[N]` field sized to exactly
that many bytes. This models the aggregate base contribution (however
many bases, vptrs, or singleton mixins it's made of) without needing to
individually walk and resolve each one, matching this codebase's
established opaque-fallback philosophy (see the `fields.isEmpty()`
branch this complements, and 0017's intrinsic-vector opaque fallback).

## A second bug this fix exposed (and also fixes): `isPolymorphic(Type)` never resolves through a typedef

Full-sweep verification of the fix above initially showed **1
regression**: `VoiceSpellFireHandler` (`RE::VoiceSpellFireHandler :
public AnimHandler`, where `using AnimHandler =
IHandlerFunctor<Actor, BSFixedString>;`) went from accidentally-OK(16)
to visibly-MISMATCH(24).

Root-caused via `GCPP_DEBUG_STRUCT`/`GCPP_DEBUG_POLY` tracing (temporary,
not part of this patch): `isPolymorphic(Type)` calls
`type.declaration()` to detect whether a base is a polymorphic template
specialization. For a base spelled via a **plain alias/typedef name**
(here, `AnimHandler`, not `IHandlerFunctor<Actor,BSFixedString>`
written out), `clang_getTypeDeclaration` returns the `TYPEDEF_DECL`
cursor itself -- a one-line `using` declaration with no
base-specifier/method children to walk -- not the aliased record.
Confirmed via trace: `type=RE::AnimHandler found=false numBases=0
paramNames=[]`, even though `IHandlerFunctor<Actor,BSFixedString>`
plainly has a virtual destructor.

This was a **pre-existing** bug, silently invisible before this patch:
with the base's real content also being dropped (the bug fixed above),
the resulting spurious "own vptr" this false-negative causes happened to
land on the exact same final byte count as the real layout, by
coincidence -- Ghidra's own struct-packing alignment (`struct
setPackingEnabled(true)`) rounds `8(spurious vptr) + 4(pad0C only)=12`
up to `16` (the largest member's alignment, 8, from the pointer-typed
vptr field), which happens to equal the real size. Fixing the
inline-embedding gap above recovers the base's REAL vptr too (now `16`
bytes instead of `4`), which no longer needs the spurious own-vptr to
reach the right total -- exposing the double-count as a visible `24`.

**Fix**: when `isPolymorphic(Type)`'s initial `declaration()` isn't a
record (`null`, `TYPEDEF_DECL`, or `TYPE_ALIAS_DECL`), resolve through
`type.canonicalType()` first -- `clang_getCanonicalType` strips through
typedefs/aliases to the real specialization, whose `declaration()` then
correctly reaches `IHandlerFunctor`'s own primary template body.

## Verification

Full 1630-header sweeps on all three runtimes (AE, SE, VR), patch set
0001-0024 + this patch, via `scripts/generate_gdt.sh` +
`scripts/coverage_report.py` + `scripts/check_regression.py` against
each runtime's committed baseline:

- **AE**: 0 regressions, 19 improvements. OK 2064 -> 2082.
- **SE**: 0 regressions, 19 improvements (identical class list).
- **VR**: 0 regressions, 19 improvements (identical class list).

Improvements (all three runtimes): `BGSPackageDataLocation`,
`BGSSaveLoadManager`, `BGSSaveLoadManager::Thread`, `BSPackedTaskQueue`,
`GameSettingCollection`, `HandlerDictionary`, `INIPrefSettingCollection`,
`INISettingCollection`, `Main`, `RegSettingCollection`,
`ResponseDictionary`, `UIMessageQueue`, `bhkCharProxyController`,
`bhkCharacterPointCollector`, `bhkCharacterProxy`, `hkpAgentNnTrack`,
`hkpAllCdPointCollector`, `hkpSimulationIsland` (all MISMATCH -> OK),
plus `BGSPackageDataBool` (EMPTY -> MISMATCH -- a rank improvement per
`check_regression.py`'s ordering, though not yet fully correct; a
different, unrelated -8 delta, not investigated as part of this patch).

Note the fix's effect reaches well beyond the two clusters that
motivated it (`GameSettingCollection`, `Main`, `BSPackedTaskQueue`, etc.
were not part of the original hkInplaceArray/BSTObjectDictionary lead) --
this is a genuinely general fix for the "template specialization used
as a field/base whose real content lives partly in its own bases"
shape, not a narrow one-off.

`coverage_baseline.json`, `coverage_baseline_se.json`,
`coverage_baseline_vr.json` all updated to reflect this patch.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, 0011-0018, 0021-0024 are already applied:

```bash
patch -p1 < ../../patches/0025-inline-embed-base-contributed-prefix.patch
```

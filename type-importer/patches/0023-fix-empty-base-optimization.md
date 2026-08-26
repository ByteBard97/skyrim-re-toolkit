# Patch 0023: correctly apply C++ Empty Base Optimization to a class's first base

Fixes 28 classes per runtime (AE/SE/VR all identical), including `GFxResource`
and ~20 of its descendants (`GFxCharacterDef`, `GFxMovieDef`, `GFxShapeBase`,
etc.) -- the largest remaining cluster from `patches/0008-*-DEFERRED.md`'s
own MISMATCH audit after patch 0022 landed.

## How this was found

After patch 0022, `type-importer`'s remaining 81 `MISMATCH` classes were
regrouped by `actual - expected` delta. The largest surviving cluster was
+8 bytes, 35 classes -- initially assumed to be more `isPolymorphic()`
fallout, but direct `.gdt` inspection of `GFxCharacterDef` and its base
`GFxResource` showed something different: `GFxResource`'s own base,
`GNewOverrideBase<GStatGroups::kGStat_Default_Mem>`, was embedded as a real
1-byte field (`super_GNewOverrideBase`), even though `GNewOverrideBase<Stat>`
(`RE/G/GNewOverrideBase.h`) has **zero data members** -- just an enum and
the `GFC_MEMORY_REDEFINE_NEW` operator-new/delete macro. This 1-byte
"ghost" field, plus the 4-byte alignment padding it forces before the next
member, accounts for exactly the observed +8.

## Root cause

`SourceParser.parseFieldsFromType(Type)` (patch 0003) already has a
documented fallback for a template-specialization base with no explicit
`clang_Type_visitFields` results: pad with an opaque `char[sizeOf()]`, sized
from `clang_Type_getSizeOf()`. The comment explaining this fallback is
explicit about its intended case: "the common case when this specialization
is used as a base class, e.g. `BSTEventSink<T>` -- a pure vtable interface
with no explicit fields, just an implicit compiler-generated vptr" --
i.e. it exists to preserve a base's own **vptr-sized** content (`sizeOf() >= 8`)
that `visitFields` can't see.

For a genuinely empty, non-polymorphic base like `GNewOverrideBase<Stat>`,
`sizeOf()` is exactly `1` -- the C++ standard's mandated minimum for any
complete type (so two distinct objects never share an address), not a
vptr. `parseStruct`'s base-embedding loop (`for (int i = 0; i < baseClasses.size(); i++)`)
unconditionally emits a field for every base, whether that content is a
real vptr-sized pad or this 1-byte minimum -- there was no distinction
between "this base has real content worth preserving" and "this base is
standard-mandated filler for a standalone object, which C++'s **Empty Base
Optimization** elides to zero bytes when used as an actual base subobject."

## The fix, and three attempts to get the condition right

The fix lives entirely in `parseStruct`'s base-embedding loop (not in
`parseFieldsFromType`, to avoid touching its four other call sites): skip
adding a base's `FieldInfo` entirely when that base is eligible for EBO.
Getting the eligibility condition right took three attempts, each verified
with a full 1630-header sweep:

**Attempt 1 -- skip any base with `sizeOf() <= 1`, regardless of position.**
Fixed the 20-class `GFxResource` cluster (36 improvements) but regressed 9
already-`OK` classes: `UI`, `ControlMap`, `GASEnvironment`,
`FOCollisionListener`, `AnimationFileManagerSingleton`, `BaseExtraList`,
`ExtraDataList`, `ActorEquipManager`, `GFxSprite` (2 of these 9 --
`BaseExtraList`/`ExtraDataList` -- later turned out to be a methodology
artifact, not a real regression; see below). Every real regression shares
one shape: the empty base is the **second or later** base in a
multiple-inheritance list, at a compiler-assigned non-zero offset --
confirmed via the headers' own inline offset comments, e.g.
`GASEnvironment : public GFxLogBase<GASEnvironment>, // 000` then
`public GNewOverrideBase<GFxStatMovieViews::kGFxStatMV_ActionScript_Mem> // 008`.
A base placed at its own fixed, non-zero offset still needs real
(minimum 1-byte) space to keep that offset meaningful, exactly like a plain
data member would -- EBO does not apply here.

**Attempt 2 -- narrow to `i == 0` (only the first/sole base).** Reduced
regressions from 9 to 3 real ones (`ActorEquipManager`, `ControlMap`, `UI`)
plus the 2 methodology artifacts. All 3 real regressions are classes with
**no virtual methods anywhere** in their own declaration or base chain --
fully non-polymorphic. `ActorEquipManager : public BSTSingletonSDM<ActorEquipManager>`
is the clearest case: its own `static_assert(sizeof(ActorEquipManager) == 0x2)`
confirms the base contributes exactly 1 byte (offset 0), plus its own
`bool unk01` field (offset 1) = 2 total -- eliding the base to 0 would give
1, not 2. With no vtable anywhere to already occupy offset 0 and establish
identity there, the compiler still reserves the base's standalone 1-byte
minimum.

**Attempt 3 (landed) -- `i == 0` AND the derived class introduces its own
new vtable.** The condition reuses `primaryBaseIsPolymorphic` and
`virtualMethods`, already computed a few lines earlier in `parseStruct` for
the exact same "does this class get a synthetic vptr field" decision:

```java
if (i == 0 && baseSizes.get(i) <= 1
        && !primaryBaseIsPolymorphic && !virtualMethods.isEmpty()) {
    continue;
}
```

`GFxResource` (fixed) introduces its own vtable (three virtual methods plus
a virtual destructor, no polymorphic base) -- that vptr already occupies
offset 0 and establishes a real, distinguishable identity there, so the
empty `GNewOverrideBase<Stat>` base underneath it needs no separate space.
`ActorEquipManager`/`ControlMap`/`UI` (correctly left alone) have no vtable
at all, so the condition never fires for them, and their empty base keeps
its standalone 1-byte minimum. Full sweep, all three runtimes: **0
regressions, 28 improvements, identical set on AE/SE/VR.**

## Methodology gap found along the way (not a code bug)

Attempt 1's initial regression list included `BaseExtraList`/`ExtraDataList`
going `NO_GROUND_TRUTH(24/32) -> EMPTY(1)`. These are NOT a real regression:
`generate_gdt.sh` passes `--tail-padding-hints tail_padding_hints.csv` by
default for AE sweeps (patch 0019's mechanism, working around these two
classes' fields being invisible under `ENABLE_SKYRIM_AE`), but this
session's manual `GenerateGdt` invocations (used to iterate faster than the
full `generate_gdt.sh` wrapper) omitted that flag entirely. Re-running with
`--tail-padding-hints` included resolved both -- confirmed the committed
`coverage_baseline.json` already carries the correct hint-adjusted values
(`24`/`32`), so nothing was ever actually broken, only mis-measured by this
session's own shortcut. Worth flagging for whoever next iterates on AE
sweeps outside the `generate_gdt.sh` wrapper.

## Blast radius: 28 classes fixed per runtime, 0 regressions

Full 1630-header sweep, all three runtimes, against the committed
`coverage_baseline*.json` files (updated by this patch): **AE 0
regressions / 28 improvements, SE 0 regressions / 28 improvements (identical
set), VR 0 regressions / 28 improvements (identical set).**

Improvements: `GFxResource` itself, plus its descendants
`GFxButtonCharacterDef`, `GFxCharacterDef`, `GFxConstShapeCharacterDef`,
`GFxConstShapeNoStyles`, `GFxConstShapeWithStyles`, `GFxEditTextCharacterDef`,
`GFxImageResource`, `GFxMorphCharacterDef`, `GFxMovieDataDef`, `GFxMovieDef`,
`GFxMovieDefImpl`, `GFxShapeBase`, `GFxShapeBaseCharacterDef`,
`GFxShapeCharacterDef`, `GFxShapeNoStyles`, `GFxShapeWithStyles`,
`GFxSpriteDef`, `GFxStaticTextCharacterDef`, `GFxTimelineDef`,
`GFxTimelineIODef`; plus `BSMusicManager`, `BSNavmeshInfoMap`,
`ICellAttachDetachEventSource`, `MenuTopicManager`, `NavMeshInfoMap`,
`TES`, `UISaveLoadManager` (all descend from a `GNewOverrideBase<Stat>`-
or `BSTSingletonSDM<T>`-rooted chain with their own new vtable at the sole
first base).

`Archive` and `BGSDefaultObjectManager` -- the two multiple-inheritance
exceptions patch 0008 flagged as a possibly-different shape (a
template-specialization base as the SECOND, non-primary base) -- remain
`MISMATCH`, unaffected by this patch, confirming they are indeed a
genuinely separate issue (this patch's condition only ever fires for
`i == 0`). `ArmorRatingVisitor`, `BaseExtraList`, `ExtraDataList`,
`BGSPackageDataBool` (0021's accepted regression), and all of patch 0022's
88 fixes are unchanged, confirming no interaction with unrelated prior
patches.

## Verification

Full 1630-header sweep, all three runtimes (`ENABLE_SKYRIM_AE`,
`ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_VR`), against
`coverage_baseline{,_se,_vr}.json` via `check_regression.py`: 0 regressions,
28 improvements per runtime, identical improvement set across all three.
`coverage_baseline*.json` updated to lock in the 28 improvements.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, 0011-0018, 0021, 0022 (and 0010 on JDK 22+) are already
applied:

```bash
patch -p1 < ../../patches/0023-fix-empty-base-optimization.patch
```

# Patch 0024: a second Empty Base Optimization elision path, sourced from clang's own layout

Fixes 7 classes per runtime (AE/SE/VR all identical), extending patch
0023's Empty Base Optimization fix to a case it couldn't cover: a
genuinely empty, non-polymorphic sole base with no vtable anywhere in the
derived class. Instead of guessing at the MSVC ABI rule (which turned out
not to have a clean, reasoning-derivable pattern), this asks clang
directly for the real, compiler-computed offset of the class's own first
field via `clang_Cursor_getOffsetOfField`.

## How this was found

A fresh `coverage_report.py` look at the remaining MISMATCH clusters after
patch 0023 found the +8 cluster's largest remaining member,
`BGSStoryEventManager`, still oversized. Its own header:

```cpp
class BGSStoryEventManager :
    public BSTSingletonImplicit<BGSStoryEventManager>  // 00
{
public:
    ...
    BSTArray<BGSRegisteredStoryEvent>        registeredEvents;    // 00
    ...
};
static_assert(sizeof(BGSStoryEventManager) == 0x68);
```

The header's own offset comment places `registeredEvents` at offset `00`
-- meaning `BSTSingletonImplicit<BGSStoryEventManager>` (a truly empty
struct: `template <class T> struct BSTSingletonImplicit {};`) contributes
**zero** bytes here, even though `BGSStoryEventManager` has no vtable of
its own and doesn't satisfy patch 0023's `!primaryBaseIsPolymorphic &&
!virtualMethods.isEmpty()` condition at all.

This directly contradicts `ActorEquipManager`, patch 0023's own
counter-example for the "no vtable" case:

```cpp
class ActorEquipManager : public BSTSingletonSDM<ActorEquipManager> {
public:
    ...
    bool unk01;  // 01
};
static_assert(sizeof(ActorEquipManager) == 0x2);
```

Here the identically-empty base (`BSTSingletonSDM<T>` is also fully empty,
transitively -- see 0023's own writeup) contributes exactly **one** real
byte (`unk01` at offset `01`, not `00`).

## Why pure ABI reasoning didn't resolve this cleanly

Both classes have a sole, non-polymorphic, genuinely empty base -- the
only visible difference is what follows: `ActorEquipManager`'s next thing
is a 1-byte `bool`; `BGSStoryEventManager`'s is a large, 8-byte-aligned
`BSTArray<T>`. A natural hypothesis: "elide unless the immediately-following
subobject also has 1-byte alignment" (the classic reason C++ compilers
reserve a byte for an empty base -- to keep it at a distinguishable address
from an adjacent object of the same minimal size).

This hypothesis was tested against `ControlMap`/`UI`, patch 0023's other
two counter-examples:

```cpp
class ControlMap :
    public BSTSingletonSDM<ControlMap>,      // 00
    public BSTEventSource<UserEventEnabled>  // 08
```

Here the "next thing" after the empty base is **another base**,
`BSTEventSource<T>` -- a large, real, multi-field class (definitely not
1-byte-aligned), yet the empty base still needs its 1 real byte (confirmed:
eliding it in 0023's first attempt regressed `ControlMap` and `UI` by
exactly -8). This falsifies the alignment hypothesis: a following subobject
with alignment far greater than 1 does *not* guarantee elision is safe.
No clean, purely-reasoned rule was found that explains all four data
points (`GFxResource`, `ActorEquipManager`, `BGSStoryEventManager`,
`ControlMap`/`UI`) simultaneously.

## The fix: ask the compiler, don't guess the ABI

Rather than continue guessing, this patch uses a libclang binding that
already existed in the codebase (`Cursor.getFieldOffset()`, wrapping
`clang_Cursor_getOffsetOfField`, previously unused for this purpose) to
read MSVC's own layout decision directly. `parseStruct` now tracks the
cursor of the class's own first `FIELD_DECL` (`firstFieldCursor`,
captured once during the existing child-visiting walk). In the
base-embedding loop, a second, independent elision path (alongside 0023's
vtable-gated one) fires when:

- this is the class's **sole** base (`baseClasses.size() == 1`),
- it's empty (`baseSizes.get(i) <= 1`), and
- the class has at least one real field to query (`firstFieldCursor[0] != null`).

It then queries that field's real, compiler-computed offset (in bits,
divided by 8) and compares it against the expected "preceding content"
size -- 8 bytes if this class already gets a synthetic vptr (0023's own
condition fired first), 0 bytes otherwise. If they match, the base
contributed nothing and is elided; if not, the existing 1-byte placeholder
is left untouched, unchanged from 0023's behavior. This is a strict,
narrow *addition*: it only ever changes behavior in the specific
sole-base-no-vtable case 0023's own condition doesn't reach, and only
when clang's own answer confirms zero bytes are needed -- it never
overrides 0023's existing vtable-gated decision, and it does nothing at
all for multi-base classes.

Confirmed via direct testing: this path does **not** fire for
`ActorEquipManager` (its own `unk01` sits at byte offset 1, not 0, so the
`firstFieldOffsetBytes == 0` check fails and the existing placeholder is
correctly left in place) but **does** fire for `BGSStoryEventManager` (its
`registeredEvents` sits at byte offset 0, confirming the base was fully
elided by the compiler).

## Blast radius: 7 classes fixed per runtime, 1 pre-existing bug unmasked

Full 1630-header sweep, all three runtimes, against the committed
`coverage_baseline*.json` files (updated by this patch): **AE 1 regression
/ 7 improvements, SE 1 regression / 7 improvements (identical set), VR 1
regression / 7 improvements (identical set).**

Improvements: `BGSStoryEventManager`, `BSPrecomputedNavmeshInfoPathMap`,
`PrecomputedNavmeshInfoPathMap`, `GFxEvent`, `GFxKeyEvent`,
`GFxMouseEvent`, `GFxValue::ObjectInterface` -- all sole-base, empty,
non-polymorphic classes this patch's new elision path now handles
correctly.

## The one regression: pre-existing bug unmasked, not caused by this patch

`NavMeshInfoMap: OK (actual=240) -> MISMATCH (actual=232)`.

`NavMeshInfoMap : public TESForm, public BSNavmeshInfoMap, public
PrecomputedNavmeshInfoPathMap` -- three bases. Its own header's offset
comments give a complete, checkable breakdown:

```
public TESForm,                       // 00
public BSNavmeshInfoMap,              // 20
public PrecomputedNavmeshInfoPathMap  // 30
...
bool updateAll;  // 78
...
std::uint32_t padEC;  // EC
```
`static_assert(sizeof(NavMeshInfoMap) == 0xF0);`

Reading the gaps: `TESForm` contributes `0x20` (32), `BSNavmeshInfoMap`
contributes `0x30 - 0x20 = 0x10` (16), `PrecomputedNavmeshInfoPathMap`
contributes `0x78 - 0x30 = 0x48` (72 -- exactly this patch's now-correct
standalone size for it, fixed above), and the class's own trailing fields
run from `0x78` to `0xF0`, i.e. `0x78` (120) bytes. Sum:
`32 + 16 + 72 + 120 = 240` -- exactly the real, expected total. This
confirms `PrecomputedNavmeshInfoPathMap`'s corrected 72-byte size is
*exactly* what `NavMeshInfoMap` needs when embedding it as a
non-template, already-registered base (looked up via the ordinary
`pool.getType()` path, not this patch's new logic, which never touches
multi-base classes).

Since the arithmetic with the corrected size sums to exactly 240 but our
parser's actual output is 232 (8 short), the missing 8 bytes must come
from somewhere else in `TESForm`'s or `BSNavmeshInfoMap`'s own embedding
-- a separate, pre-existing, currently-unidentified shortfall, unrelated
to this patch's fix. Before this patch, `PrecomputedNavmeshInfoPathMap`'s
own size was independently *oversized* by exactly 8 bytes (the same
`BSTSingletonExplicit<T>`-sole-base pattern this patch now fixes,
confirmed by its own entry in the improvements list above), and that
independent +8 error happened to exactly cancel the still-unidentified
-8 shortfall elsewhere in `NavMeshInfoMap`'s own layout, producing a
coincidentally-correct 240 total. This is the same "two wrongs cancel to
look right" pattern already documented for patches 0021 (`BGSPackageDataBool`)
and 0022 (`GFxLoaderImpl`/`GFxMovieRoot`) -- fixing one bug unmasks a
different, pre-existing one; not a regression this patch introduced or
should be blocked on. The unidentified shortfall in `TESForm`/
`BSNavmeshInfoMap`'s own embedding remains open for whoever picks it up
next.

## Verification

Full 1630-header sweep, all three runtimes (`ENABLE_SKYRIM_AE`,
`ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_VR`), against
`coverage_baseline{,_se,_vr}.json` via `check_regression.py`: 1 regression
(above, precedented/accepted), 7 improvements per runtime, identical
improvement and regression set across all three. `coverage_baseline*.json`
updated to lock in the 7 improvements and the one accepted regression.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006, 0009, 0011-0018, 0021, 0022, 0023 (and 0010 on JDK 22+) are
already applied:

```bash
patch -p1 < ../../patches/0024-fix-empty-base-optimization-ground-truth.patch
```

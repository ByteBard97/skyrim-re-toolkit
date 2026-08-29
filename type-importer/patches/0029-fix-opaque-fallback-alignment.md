# Patch 0029: preserve the real ABI alignment of opaque-padded template specializations

**Status: accepted, zero regressions. Fixes 5 classes across all three runtimes.**

## Task: T1-10 (BACKLOG.md), investigate the 30 remaining checkable MISMATCH classes

A quick spot-check flagged 8 classes sharing an exact -8-byte delta
(`Atmosphere`, `BGSPackageDataBool`, `Clouds`, `CombatInventory`,
`GFxLoaderImpl`, `GFxMovieRoot`, `GFxStateBagImpl`, `Moon`) plus several
with -4/-7 deltas, as a possible single systematic cause. Investigating
each with real ground-truth (`clang-cl` layout dumps, `dump_layout.sh`)
and the parser's own `--report-json` field-level output found this bucket
actually splits into **at least three distinct, unrelated mechanisms**:

1. **A scale-dependent bug** (`SkyObject`/`Atmosphere`/`Clouds`/likely
   `Moon`/`Stars`/`Sun`/`Precipitation`): all resolve **correctly** in an
   isolated small-scale parse (confirmed via a 3-4 header
   `generate_gdt.sh` run -- `SkyObject`=16, `Atmosphere`=56, `Clouds`=1312,
   all byte-exact) but wrong at full-1630-header-sweep scale. Same
   category as patch 0007's "THIRD investigation" findings -- not
   root-caused this pass, needs the same kind of TypePool/registration-
   order instrumentation that investigation used. **Deferred, not
   attempted further this pass** (see "Remaining work" below).
2. **A base-content-loss bug specific to one template chain**
   (`BGSPackageDataBool` via `BGSNamedPackageData<IPackageData>`): the
   base's real `data` field (confirmed via
   `static_assert(offsetof(BGSPackageDataBool, data) == 0x08)`) is
   missing from the opaque-padded base entirely. Different from patch
   0025's fix (which handles base-contributed content dropped due to a
   type's OWN fields being visited but its base's not) -- this one visits
   *no* fields at all and pads to a wrong (too-small) `sizeOf()`. **Not
   root-caused this pass** -- needs tracing `BGSNamedPackageData<T>`'s own
   template structure specifically.
3. **The alignment bug this patch fixes** (`CombatEquipment`/
   `CombatInventory`, and, found via the full-sweep verification below,
   `BGSDecalNode::RUNTIME_DATA`, `BSShaderPropertyLightData`,
   `SubtitleManager`) -- detailed below.

A fourth class of investigation, `GFxStateBagImpl`/`GFxLoaderImpl`, traced
each of their three template bases individually (`GRefCountBase`=16,
`GFxStateBag`=8, `GFxLogBase`=8, all independently correct against their
own `static_assert`s) but the *composed* class is still 8 bytes short --
real MSVC multi-vtable-base inter-base padding this investigation could
not isolate to the specific mechanism in the time available. **Not fixed
this pass.**

## Root cause (the one this patch fixes)

`SourceParser.parseFieldsFromType`'s opaque-padding fallback -- used when
a class-template specialization (field- or base-typed) has no directly
visitable own fields, e.g. `BSTArray<T>` (real storage lives in a base
`clang_Type_visitFields` doesn't walk) -- builds a synthetic struct
containing exactly one field: `opaque: char[N]`, `N` = the real
`clang_Type_getSizeOf()`. A `char[N]` array has alignment 1. With Ghidra's
auto-packing enabled and no override, a struct containing only that field
gets **alignment 1**, discarding the specialization's true ABI alignment
(commonly 8, for any pointer-bearing container internal).

When this synthetic struct is then embedded **by value as a field** in an
enclosing struct, the enclosing struct's own auto-computed alignment (and
therefore its tail padding) is driven by the *maximum* alignment among
its fields -- and this one now silently reports 1 instead of its real 8,
so the enclosing struct's tail gets rounded to the wrong (smaller)
boundary.

Confirmed via `--report-json` field dump: `CombatEquipment`'s `items`
field (`BSTArray<NiPointer<CombatInventoryItem>>`) opaque-pads to a
24-byte `char[24]` struct. `CombatEquipment`'s own fields end at byte 44
(`items` 24 + `slot`/`maxRange`/`optimalRange`/`minRange`/`score`, 4
floats+1 uint32 = 20). Real `sizeof(CombatEquipment) == 0x30` (48) --
the real compiler tail-pads 44 up to 48 for 8-byte alignment (the real
`BSTArray` internally holds pointers). The parser, seeing only a
1-aligned opaque blob, stopped at 44. `CombatInventory` embeds
`CombatEquipment` **twice** by value (`unk118`, `unk148`) -- the 4-byte
deficit compounds to exactly the observed -8.

## Fix

Added `explicitMinAlignment` to `ParsedStructure` (new optional
constructor parameter, calls Ghidra's
`Composite.setExplicitMinimumAlignment` when set), and pass
`type.alignOf()` (a real, already-existing libclang binding,
`Type.alignOf()` → `clang_Type_getAlignOf`) when constructing the
opaque-padded synthetic struct.

### Two guards, both found necessary via full-sweep regression checking

**Guard 1 -- skip the trivial empty-class placeholder (`opaqueSize <= 1`).**
A genuinely empty base/field (C++'s "empty class still has `sizeof >= 1`"
rule) pads to `char[1]`. Forcing e.g. `align=8` onto a 1-byte struct makes
Ghidra round **that struct's own length** up to 8 to satisfy its declared
alignment -- turning a near-zero-content placeholder into a real 8-byte
one. Unguarded, this alone caused 3 regressions on the first full sweep
(see below).

**Guard 2 -- only apply to field-typed specializations, never base-class
ones (`!isBaseClass`, a new parameter threaded through
`parseFieldsFromType`).** Even with Guard 1, a second full sweep still
regressed the same 3 classes (`MenuControls`, `PlayerControls`,
`StatsNode`) by exactly +8 each. Root cause, traced via `--report-json`:
each is `BSTEventSink<A> : BSTSingletonSDM<T> : BSTEventSink<B>` (three
base-class-typed specializations). `BSTSingletonSDM<T>` is a genuinely
near-empty singleton mixin (opaque-pads to `char[1]`, correctly guarded
by Guard 1 -- untouched by this patch). But the parser's existing
empty-base-optimization (patches 0023/0024) only collapses a *first*
empty base, not a middle one in a 3-way chain -- so this middle base
already contributed a stray, uncollapsed byte **before this patch**.
Confirmed via a baseline (0001-0028-only) run: `MenuControls` was already
placing its third base at the wrong internal offset (9 instead of the
real 16) -- but happened to land on the **correct total size** (136) by
coincidence, because the two adjacent 8-byte opaque interface bases
(`BSTEventSink<A>`/`BSTEventSink<B>`) were *also* alignment-1, packing
tightly against the misaligned middle base in a way that summed to the
right total. Once this patch's alignment fix correctly gives those two
interface bases `align=8`, Ghidra's packer places the third base at a
*more* geometrically correct offset (16) -- but the pre-existing,
still-unfixed EBO gap on the middle base now shows up as a real, wrong
extra 8 bytes instead of being absorbed by coincidence. Two separate bugs
were canceling each other out; fixing one exposed the other. Scoping this
patch to field-only embedding avoids the interaction entirely -- the base-
class-embedding path (and its EBO-adjacency bug) is untouched, a
documented follow-on for whoever picks it up (see "Remaining work").

## Verification

Full 1630-header sweeps, all three runtimes, before vs. after (patch set
0001-0028 vs. 0001-0029):

| Runtime | OK before | OK after | Regressions | Improvements |
|---|---|---|---|---|
| AE | 2,097 | 2,102 | 0 | 5 |
| SE | 2,115 | 2,120 | 0 | 5 |
| VR | 2,116 | 2,121 | 0 | 5 |

Improvements, identical set on all three runtimes:
`BGSDecalNode::RUNTIME_DATA`, `BSShaderPropertyLightData`,
`CombatEquipment`, `CombatInventory`, `SubtitleManager` -- all MISMATCH ->
OK, all via the same opaque-field-alignment mechanism (each embeds at
least one class-template-specialization field by value).

Two earlier attempts at this fix (unguarded, and Guard-1-only) each
introduced 3 real regressions (`MenuControls`, `PlayerControls`,
`StatsNode`), caught by this same full-sweep check before landing --
documented in this file rather than silently discarded, per this
project's own verification discipline.

## Remaining work (not attempted further this pass, `T1-10`'s bucket is not fully closed)

- **The scale-dependent `SkyObject`/`Atmosphere`/`Clouds`/`Moon`/`Stars`/
  `Sun`/`Precipitation` cluster** -- correct in isolation, wrong at full-
  sweep scale. Needs the same TypePool/registration-order instrumentation
  patch 0007's THIRD investigation used, not attempted this pass.
- **`BGSPackageDataBool`** -- `BGSNamedPackageData<IPackageData>`'s own
  `data` field is missing from the opaque padding entirely (not an
  alignment issue -- the base pads to too *small* a `sizeOf()`, not just
  wrong alignment). Needs tracing that specific template's structure.
- **`GFxStateBagImpl`/`GFxLoaderImpl`** -- a real MSVC multi-vtable-base
  inter-base padding gap (~8 bytes) this investigation traced each base's
  individual correctness for but could not isolate the composition
  mechanism for.
- **Base-class-embedded opaque specializations losing alignment** -- this
  patch's Guard 2 deliberately leaves this case unfixed. The real fix
  needs empty-base-optimization (patches 0023/0024) extended to collapse
  non-first empty bases in a 3+-way multiple-inheritance chain, which
  would remove the coincidental-cancellation this patch's Guard 2 is
  working around, at which point Guard 2 could likely be lifted safely.
- **Two large outliers** (`SkyrimVM` -32984, `VirtualMachine` -32776) and
  a handful of +4/+8/+16 deltas (`Argument`, `Archive`,
  `BGSDefaultObjectManager`, `BGSStoryTeller`, `GRendererEventHandler`,
  `LooseFileStream`, `UIBlurManager`, `MovementControllerAI`,
  `MovementControllerNPC`) -- not investigated this pass at all.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0028 are already applied:

```bash
patch -p1 < ../../patches/0029-fix-opaque-fallback-alignment.patch
```

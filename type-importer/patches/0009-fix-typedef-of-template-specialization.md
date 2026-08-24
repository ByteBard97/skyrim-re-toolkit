# Patch 0009: fix typedef-of-template-specialization resolution

## The problem

From patch 0006's "Known follow-ups": `SourceParser.parseTypedef` registers
a `ParsedTypedef` whose underlying-type string is the raw clang spelling
of the aliased type. For a typedef whose target is a class-template
specialization -- e.g. `using ActorHandle = BSPointerHandle<Actor>;`
(`RE/B/BSPointerHandle.h`) -- that spelling is `"BSPointerHandle<Actor>"`.
`ParsedTypedef.createDataType()` resolves its target via a plain
name-keyed `pool.getType(typeName)` lookup. A template-specialization
spelling is never independently registered under that literal string
anywhere in the pool (unlike field/base-class usage of the same
specialization, which routes through `SourceParser.parseFieldsFromType`'s
inline-embedding mechanism, patches 0003/0005) -- so this lookup can
never succeed, and any class depending on such a typedef gets stuck
either EMPTY or under-sized forever.

This was the confirmed cause of `RE::AIProcess` (240 vs expected 320) and
`RE::ActiveEffect` (fully EMPTY) remaining wrong even after patch 0006 --
both blocked specifically on `ActorHandle`.

## The fix

Same shape as the fix already proven for fields/bases: instead of a
name-keyed lookup, carry the already-parsed structure directly.

- `ParsedTypedef` gets a second constructor taking a `ParsedType
  inlineType` (mirroring `ParsedStructure.FieldInfo`'s `anonymousType`).
  `createDataType()` calls `inlineType.createDataType(pool)` directly
  when present, instead of `pool.getType(typeName)`.
  `getDependencies()` returns an empty list in this case, mirroring
  `ParsedStructure.getDependencies()`'s filtering of `isAnonymous()`
  fields -- there's no name-keyed dependency to wait on since nothing is
  registered under a lookup-able name; the inline type's own nested
  dependencies are resolved when its `createDataType()` runs, same as any
  other inline-embed.
- `SourceParser.parseTypedef` checks whether the underlying type's
  spelling contains `<` (a template specialization). If so, it calls the
  existing `parseFieldsFromType(underlying, category)` (unchanged, the
  same method patches 0003/0005 already use for fields/bases) and
  constructs a `ParsedTypedef` with the resulting `ParsedStructure` as its
  inline type, instead of the plain string-based constructor.

## Verification

Isolated test (`RE/A/AIProcess.h RE/A/ActiveEffect.h`, zero clang
diagnostics):

| Class | Before (0001-0006) | After (+0009) | Expected (`static_assert`) |
|---|---|---|---|
| `ActiveEffect` | 1 (EMPTY) | **144 (0x90)** ✅ exact | 0x90 |
| `AIProcess` | 240 | 288 | 0x140 (320) -- improved, not exact; see below |

Full 1630-header sweep (via `scripts/list_re_headers.sh`), independently
re-run after two transient environment collisions (see below):
**17778 resolved data types, 5179 composites, 1144 clang diagnostics**
(unchanged from the 0006 baseline -- this is a `TypePool`/`ParsedTypedef`
resolution fix, not a parse fix).

`scripts/check_regression.py` against `coverage_baseline.json`
(patches 0001-0006): **366 improvements, 1 regression.** OK count
1234 → **1523** (+289 net).

## The 1 regression -- root-caused, not a bug in this fix

`BGSSoundOutput`: OK (64, matching its real `static_assert(sizeof(...) ==
0x40)`) → MISMATCH (72). Root-caused via `InspectGdt.java` component
inspection: `BGSSoundOutput` has its own nested `struct Data` (real size
confirmed via its own `static_assert(sizeof(Data) == 0x4)`,
`RE/B/BGSSoundOutput.h`), but `TypePool` registers every struct/union
under its **bare** (non-namespace/non-owner-qualified) name -- and
`"Data"` is a notoriously overloaded name in this codebase: the coverage
sweep's own ground-truth miner (`scripts/mine_static_asserts.py`) already
flagged 25 unrelated classes each declaring their own distinct nested
`Data` struct, all colliding on the same bare pool key (documented in
`COVERAGE_SWEEP_PLAN.md`'s Step 1 section). Before this patch,
`BGSSoundOutput`'s own 4-byte `Data` happened to be the one that won that
collision (whichever candidate resolves last/with the most fields in
`TypePool`'s iterative fixed-point loop, per patch 0002's forward-decl
preference logic). This patch resolves ~289 additional classes that were
previously EMPTY or MISMATCH, which changes the pass-by-pass order
`TypePool.resolve()`'s loop stabilizes in -- and for this one class,
a *different* class's 8-byte `Data` now wins the same collision instead.

This is not a defect introduced by the typedef-routing fix itself (which
never touches name collision resolution at all) -- it's the same
"unmasking a pre-existing, unrelated bug via a shift in resolution order"
pattern already seen in patches 0006 and 0007's own regressions
(`GFxValue`/`IMenu` and `FxDelegateHandler` respectively). The real,
underlying issue -- bare, unqualified names for nested types colliding
across unrelated classes -- is a distinct, considerably larger
architectural gap (nested types would need scope-qualified registration
keys, e.g. `BGSSoundOutput::Data`, to fix generally) well outside the
scope of this patch's one focused fix, and is already tracked as a known
limitation from the coverage-sweep's ground-truth mining work.

**Given 366 genuine improvements against 1 well-understood,
pre-existing collision artifact, this patch is recommended for
acceptance as-is** -- fixing the name-collision problem properly is
follow-up work for a much larger patch, not a blocker for this one.

**Explicitly ruling out an alternative theory, so it isn't
re-investigated later:** the +8-byte delta (64→72) initially looked like
it could be a duplicated interface-base vptr (the pattern behind patches
0001/0006/0007's various vptr bugs). It is not -- confirmed directly by
reading `RE/B/BGSSoundOutput.h`: `BGSSoundOutput` has no polymorphic
bases, and its own `Data data;` member (offset 0x28) is exactly the
colliding nested-struct name described above. The size change is a
different, unrelated 8-byte `Data` struct now winning the same
bare-name collision, not a vptr issue.

**Independently double-verified across two separate toolchains**: this
patch's numbers (366 improvements, 1 regression, same class) were
reproduced identically in two independent sessions running two different
JVM/FFI configurations (JDK 21 + `-Xint` preview FFM, and JDK 25 + JIT +
final FFM) -- strong evidence the fix itself is toolchain-independent and
solid, separate from whichever toolchain migration is ultimately
accepted.

## Note on environment flakiness during verification

Two of four full-sweep attempts failed for reasons unrelated to this
patch's code: a `NoClassDefFoundError`/`UnsupportedClassVersionError`
from a concurrently-running agent building the same shared submodule
directory under a different JDK version at the same time (confirmed via
`pgrep` showing two live Gradle daemons, one JDK 21 and one JDK 25/22,
and a stale cross-JDK-version `build/classes/java/main` from a prior
collision). Resolved by trashing the submodule's gitignored `build/`
directory to force a clean compile before the successful run. Not a
patch-0009 issue.

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`, after patches
0001-0006 are already applied:

```bash
patch -p1 < ../../patches/0009-fix-typedef-of-template-specialization.patch
```

## Known follow-ups (not fixed by this patch)

- `AIProcess` (288 vs expected 320) remains non-exact -- a separate,
  not-yet-investigated issue beyond the `ActorHandle` typedef this patch
  fixes.
- The bare-name collision issue that caused this patch's one regression
  is a real, systemic gap (documented in `COVERAGE_SWEEP_PLAN.md`) that
  would benefit from scope-qualified type registration keys -- a
  significant separate undertaking, not scoped here.
- **Likely shares a root cause with patch 0007's remaining blocker.**
  Both are string-keyed, first-registration-wins type resolution
  deciding by bare/ambiguous spelling: 0007's `anon_tmpl_*` hash
  collisions are canonical-vs-sugared spellings of the same template
  instantiation resolving to different hash keys; this patch's
  regression is 25 unrelated nested `Data` structs sharing one bare-name
  key. A single general fix -- keying pool registration on namespace/
  parent-qualified names, or on canonical spellings consistently -- may
  resolve both, and possibly other silent mis-resolutions that happen to
  currently land on a plausible size and haven't been noticed. Worth
  considering as the next patch (0011) candidate, evaluated against both
  0007's and this patch's known regressions simultaneously.

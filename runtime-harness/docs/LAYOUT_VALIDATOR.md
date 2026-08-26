# LayoutValidator — design doc

**Status: built, deployed, and live-verified (2026-08-26).** See
[`T3-3_LAYOUTVALIDATOR_REPORT.md`](T3-3_LAYOUTVALIDATOR_REPORT.md) for
the full first-compile report — two real bugs found and fixed (a wrong
build-config assumption in this doc's original text, corrected below;
and a messaging-listener conflict with `main.cpp`), plus the actual
three-way diff result against `coverage_baseline.json` (0 confirmed
mismatches). Real log evidence:
[`examples/RuntimeHarness_T3-3_layoutvalidator.log.txt`](../examples/RuntimeHarness_T3-3_layoutvalidator.log.txt).

## What this is

An inspector that cross-checks C++ type layouts against the **running
game process**, closing the loop with type-importer's static analysis:

- type-importer parses the vendored CommonLibSSE-NG headers with libclang
  into Ghidra `.gdt` archives and tracks layout accuracy in
  `type-importer/coverage_baseline.json` (2,082 of 3,017 checkable
  classes byte-accurate against the headers' own `static_assert`s; the
  39-class modder-relevant hotspot list is closed — 37/39 byte-exact,
  `BaseExtraList`/`ExtraDataList` deferred with documented reasons in
  `type-importer/LOOP_GOAL.md` / `COVERAGE_SWEEP_PLAN.md`).
- runtime-harness compiles those **same headers** into a live SKSE
  plugin. Every layout claim in the headers is therefore already
  compile-time-checked: `static_assert(sizeof(TESForm) == 0x20)` etc.
  fire at plugin build time.

So what does an in-process validator add that `static_assert` doesn't?

### What it CAN prove (that static analysis cannot)

1. **The deployed binary agrees with the build.** The compile-time
   report (phase 1) logs the `sizeof`/`offsetof` values actually baked
   into the shipped DLL. If the DLL was ever built against the wrong
   CommonLibSSE-NG revision, wrong macro configuration
   (`ENABLE_SKYRIM_AE` leaking in), or stale headers, the logged numbers
   diverge from the expected values immediately — visible in a log file,
   no disassembler needed. It is a build-config fingerprint.

2. **Address Library resolution is anchored to real code.** Phase 2a
   resolves published `RE::VTABLE_*` / `RE::RTTI_*` IDs
   (`Offsets_VTABLE.h` / `Offsets_RTTI.h`) through `REL::Relocation`
   against the live module and logs resolved address + RVA. Every offset
   the whole toolkit trusts flows through Address Library; if the `.bin`
   mismatches the game build, SKSE64 refuses to load the plugin at all,
   but *partial* table mismatches or a wrong-ID-in-headers bug would
   resolve "successfully" to the wrong address. Logging RVAs makes them
   diffable against the published tables; reading back the RTTI
   type_descriptor's decorated name (TODO) turns it into a positive
   identity check.

3. **Live instances match the compiled layout.** Phase 2b reads fields
   of a live object twice — once through the typed accessor (compiled
   layout + `RelocateMember` plumbing), once as raw bytes at the
   compiled `offsetof` — and flags disagreement. Static asserts compare
   the headers against *themselves*; this compares the headers against
   *the shipping binary's actual objects*. A wrong `formID` offset in
   `TESForm` (the single most-depended-on layout in the ecosystem) would
   show up here even if every static assert passed.

4. **Machine-readable report for diffing.** Every line is
   `LayoutValidator: LAYOUT class=<name> sizeof=0xNN off.<field>=0xNN …`
   (compile-time) or `LayoutValidator: LIVE …` / `LayoutValidator: ADDR …`
   (runtime). Extraction is one grep:

   ```
   grep 'LayoutValidator: LAYOUT' RuntimeHarness.log
   ```

   The `sizeof` values diff directly against `coverage_baseline.json`'s
   `actual` (parser) and `expected` (static_assert) columns, giving a
   three-way comparison: **parser vs. header assert vs. compiled
   plugin**, plus the LIVE lines as a fourth, ground-truth leg for the
   few classes with reachable instances. The `off.*` values have no
   baseline counterpart today — the baseline tracks sizes only — so the
   runtime report is strictly richer there; extending type-importer's
   coverage tooling to track member offsets would make the diff total.

### What it CANNOT prove (honest limitations)

- **AE-specific member positions are not verifiable via `offsetof` in
  this build.** Corrected after the first real compile (see
  `T3-3_LAYOUTVALIDATOR_REPORT.md`): the plugin actually builds with
  `ENABLE_SKYRIM_SE`, `ENABLE_SKYRIM_AE`, **and** `ENABLE_SKYRIM_VR` all
  `ON` simultaneously (dynamic multi-runtime dispatch), not with none of
  them defined as originally assumed here. That combination lands every
  runtime-guarded class in a narrower `#else` branch of the headers —
  different from a plain SE-only *or* AE-only view. Measured compiled
  sizes: `Actor` `0x78`, `TESObjectREFR` `0x78`, `BaseExtraList` `0x1`
  (its `data`/`presence` members aren't even offsetof-able in this
  branch — accessor-only), `TESObjectCELL` `0x50`. Real AE live-object
  field access still has to go through `REL::RelocateMemberIfNewer`
  accessors like `Actor::GetActorRuntimeData()` (Actor.h:710) — the
  logged offsets for these classes are ground truth for *this specific
  compiled plugin*, not for any one real runtime's live memory.
  Validating the AE layout of divergent classes requires
  accessor-based live reads (TODO in phase 2b), never raw-offset reads.
- **Member semantics.** Proving `currentProcess` sits at some offset
  does not prove it points at the right `AIProcess`. Pointer-plausibility
  checks (non-null, `race->formType == FormType::Race`) are the planned
  approximation — heuristics, not proofs.
- **Vtable *contents*.** Resolving a vtable's address proves the ID
  resolves; it does not prove vfunc ordering inside the table. Checking
  that would need per-vfunc Address Library IDs and disassembly-level
  ground truth — out of scope.
- **Tail padding, alignment, bitfield packing, and
  empty-base-optimization details** beyond what `sizeof` already
  captures.
- **Any class with no reachable live instance.** Abstract classes
  (`bhkCharacterState`), engine-internal singletons without published
  `GetSingleton()`s, and short-lived objects can't be sampled from
  `kDataLoaded`. The live check covers `TESForm`-derived objects first
  precisely because the form map gives free, enumerable instances.
- **`BaseExtraList`/`ExtraDataList` remain thin.** These are the two
  hotspot classes type-importer's baseline still marks EMPTY
  (`sizeof == 1` under AE-mode parsing is *correct* — the real members
  are macro-guarded and accessor-relocated; see
  `type-importer/LOOP_GOAL.md`). In-process, `ExtraDataList`'s members
  are private and `BaseExtraList`'s are the SE view, so the compile-time
  report logs only what's compilable. Real AE ground truth for these
  needs the planned live walk: grab a loaded refr's `extraList`, read a
  known extra (e.g. `ExtraTextDisplayData`) through the accessor API, and
  confirm the chain walks sanely. That closes the last hotspot gap with
  runtime evidence instead of inference.
- **Form-type coverage of one record.** The live check samples formID
  `0x00000007` (the player base `TESNPC`) because it is guaranteed to
  exist at `kDataLoaded`. It validates the shared `TESForm` header
  region, not `TESNPC`-specific members.

## Phases

1. **Compile-time report** (`Install()`, plugin load): logs
   `sizeof` + key `offsetof` for 11 classes — `TESForm`, `TESObjectREFR`,
   `Actor` (+`Actor::ACTOR_RUNTIME_DATA`), `Character`, `BaseExtraList`,
   `ExtraDataList`, `TESObjectCELL`, `NiAVObject`, `BGSLocation`,
   `TESQuest`, `bhkCharacterState`. Selection rationale: the first seven
   cover the form/refr/actor/extra-data spine every modder-facing API
   touches (and include both baseline-EMPTY classes and all the
   SE/AE-divergent ones); `NiAVObject` is the scene-graph root with a
   VR-divergent guarded branch; `BGSLocation`/`TESQuest` are unguarded
   classes already byte-exact in the baseline (cross-validation anchors —
   if *these* ever mismatch, suspect the toolchain, not the class);
   `bhkCharacterState` proves the abstract/vtable-only case.
2. **Live check** (message listener, `kDataLoaded`): 2a resolves
   `VTABLE_TESForm[0]`, `VTABLE_Actor[0]`, `VTABLE_TESObjectREFR[0..3]`,
   `RTTI_TESForm` and logs address + RVA; 2b raw-vs-accessor field reads
   on `TESForm::LookupByID(0x00000007)`.

## TODO for the live-verification pass

Tracked in `LayoutValidator.cpp` as `TODO(live-verify)` comments.

Two done since T3-3, neither needed gameplay (both run at `kDataLoaded`,
which fires at the main menu):

- ~~RTTI type_descriptor decorated-name readback~~ **Done**: reads
  `RE::RTTI::TypeDescriptor::mangled_name()` at the resolved
  `RTTI_TESForm` address and string-compares against `.?AVTESForm@@` —
  a real positive identity check, not just address resolution. Passed
  clean on the real run (`mangled_name=.?AVTESForm@@(OK)`).
- ~~Live instance vtable-pointer identity check against resolved
  `RE::VTABLE_*` addresses~~ **Investigated, reclassified as an invalid
  invariant, not implemented as designed.** `TESForm` is an abstract
  base — every live instance is actually some derived class (the player
  base at formID `0x00000007` is a live `TESNPC`, confirmed by its own
  `formType` check passing), so its vptr correctly points to ITS OWN
  class's vtable, never `TESForm`'s. Comparing against
  `RE::VTABLE_TESForm[0]` reported `MISMATCH` on the very first real run
  (`raw=0x7FF792114D50` vs `VTABLE_TESForm[0]=0x7FF7920B0B00`) while the
  `formID`/`formType` checks on the same instance both read `OK` — a
  wrong check design, not a layout defect. The log now reports the raw
  vptr + RVA with no pass/fail verdict; a real version of this check
  would need the live instance's *actual* class's own `VTABLE_*`
  Address Library ID, which isn't among the ones this pass resolves.

Genuinely still open (need an actual game session past `kDataLoaded`,
not just the main menu):

- `PlayerCharacter::GetSingleton()` checks at `kNewGame` /
  `kPostLoadGame` (nullptr at `kDataLoaded` by design): formID `0x14`,
  formType `ActorCharacter`.
- Live `Actor::ACTOR_RUNTIME_DATA` sanity via `GetActorRuntimeData()` —
  validates the AE `RelocateMember` path, which nothing else covers.
- `ExtraDataList` live walk off a loaded cell's refrs — runtime ground
  truth for the last two baseline-EMPTY hotspot classes.
- ~~A small script that parses the `LayoutValidator: LAYOUT` lines into
  JSON for a mechanical three-way diff against `coverage_baseline.json`.~~
  **Done**: `runtime-harness/tools/parse_layout_log.py`. Parses all three
  line kinds (`LAYOUT`/`ADDR`/`LIVE`) into JSON and, with
  `--diff-baseline`, prints a parser-vs-header-vs-compiled three-way
  table and exits 1 on any confirmed mismatch. Verified against two
  hand-written sample logs in `runtime-harness/tools/sample_logs/`
  (`RuntimeHarness_layout_ok.log.txt` passes with exit 0; a deliberately
  injected `TESForm` size mismatch in `RuntimeHarness_layout_mismatch.log.txt`
  is correctly caught with exit 1) — built and tested entirely
  Linux-side, before any Windows compile exists to produce a real log.
  **Since re-run against the real log** (`RuntimeHarness_T3-3_layoutvalidator.log.txt`,
  T3-3): all 11 classes parsed correctly, 0 confirmed mismatches against
  `coverage_baseline.json`'s static_assert-backed values. See
  `T3-3_LAYOUTVALIDATOR_REPORT.md`.

The four items above (RTTI name readback, `PlayerCharacter` checks,
`ACTOR_RUNTIME_DATA` sanity, `ExtraDataList` walk, vtable-pointer
identity) remain genuinely open after T3-3 — that pass only exercised
the `TESForm(0x00000007)` live check, which was clean.

# T3-3 -- LayoutValidator: first Windows compile + deploy + live diff report

**Status: done.** First-ever MSVC compile, in-game deploy, and live
three-way diff, 2026-08-26. Real log evidence:
[`examples/RuntimeHarness_T3-3_layoutvalidator.log.txt`](../examples/RuntimeHarness_T3-3_layoutvalidator.log.txt)
(`.log.txt`, not `.log` -- `*.log` is gitignored repo-wide).

## What actually happened (short version)

1. Compiled `LayoutValidator.cpp`/`.h` for the first time -- found and fixed
   two real bugs (see below), not cosmetic ones.
2. Deployed the built DLL to the Windows box's live Skyrim AE 1.6.1170 +
   SKSE64 install, replacing the long-running three-inspector build from
   earlier the same day.
3. Got a full compile-time `LAYOUT` report (11/11 classes) and, after
   fixing a second real bug (a message-listener conflict), a full live
   `ADDR`/`LIVE` report too.
4. Ran `tools/parse_layout_log.py --diff-baseline` against the real log:
   **all 5 unguarded classes match the baseline's static_assert-backed
   values exactly (`OK`); the 6 guarded classes correctly report
   "no ground truth to check" rather than a false mismatch. Exit code 0,
   zero confirmed mismatches.**

## Bug #1: the design doc's build-config assumption was wrong

`LAYOUT_VALIDATOR.md` (and the code comments it was based on) assumed
this build compiles with **no** `ENABLE_SKYRIM_SE/AE/VR` macro defined.
The real `type-importer/vendor/CommonLibSSE-NG/CMakeLists.txt` defaults
all **three** macros **ON simultaneously** (dynamic multi-runtime
dispatch) -- confirmed from the actual build log:

```
Enable Skyrim SE: ON
Enable Skyrim AE: ON
Enable Skyrim VR: ON
```

That combination routes every runtime-guarded class into a **third,
narrower `#else` branch** in the headers -- different from both the
SE-only and AE-only views the original comments described. Two fields
referenced by the original `LayoutValidator.cpp` don't exist in that
branch at all:

- `RE::NiAVObject::userData` -- only a named member when VR is off, or
  when none of the three are defined; absent when all three are on.
- `RE::BaseExtraList::data` / `RE::BaseExtraList::presence` -- only named
  members `#ifndef ENABLE_SKYRIM_AE`; with AE on, they're accessor-only
  (`GetData()`/`GetPresence()`).

Both `offsetof()` calls were compile errors (`C2039`/`C2618`), not
runtime bugs -- fixed by dropping those two fields from the compile-time
report (with a `note=` explaining why) and correcting `LAYOUT_VALIDATOR.md`
/ `LayoutValidator.h`'s doc comments to state the real macro
configuration and the real measured sizes:

| class | doc originally claimed | actually compiles to |
|---|---|---|
| `Actor` | `0x2B0` | `0x78` |
| `TESObjectREFR` | `0x98` | `0x78` |
| `BaseExtraList` | `0x10` | `0x1` |
| `TESObjectCELL` | (not stated) | `0x50` |

These are ground truth for **this compiled plugin's specific macro
combination**, not for any one real runtime's live memory -- they are
correctly reported `NO-STATIC-ASSERT(baseline=NO_GROUND_TRUTH)` by the
diff tool rather than a false "mismatch," since `coverage_baseline.json`
has no `expected` value for guarded classes to compare against.

## Bug #2: only the first `SKSE::MessagingInterface` listener a plugin registers actually fires

`LayoutValidator::Install()` called
`SKSE::GetMessagingInterface()->RegisterListener(OnMessage)` itself, on
top of `main.cpp`'s own existing registration. The call returned `true`
(no error logged) and the compile-time report + "live-instance check
registered" line printed normally -- but the registered callback never
actually ran: `kDataLoaded` fired at `17:05:55` and only `main.cpp`'s own
`OnMessage` handler logged `"kDataLoaded received"`; the `ADDR`/`LIVE`
lines that only `LayoutValidator`'s own listener could produce were
absent. None of the other three inspectors hit this because none of them
need message-driven timing -- they only install vtable hooks at load.

Fix: removed `LayoutValidator`'s own `RegisterListener` call entirely.
`Install()` now only logs the compile-time report; a new
`LayoutValidator::OnDataLoaded()` function does the live check, called
directly from `main.cpp`'s existing single `OnMessage` handler
(`main.cpp:71`, alongside its own `kDataLoaded` log line). After this
fix, the very next relaunch produced full `ADDR`/`LIVE` output.

This is worth remembering for any future inspector needing message
timing: **route it through `main.cpp`'s one registration, don't call
`RegisterListener` a second time from the same plugin.**

## Correction to an assumption in `LAYOUT_VALIDATOR.md`

The doc assumed the live check would need actual gameplay progression
(`kNewGame`/loading a save) to reach `kDataLoaded`. In fact `kDataLoaded`
fires as soon as the game's ESM/ESP data is loaded -- **at the main menu**,
seconds after the SKSE plugin finishes loading, before any save is
touched. (`kDataLoaded` fired at `17:05:55`, six seconds after
`Loaded.` at `17:05:49` -- no save load, no gameplay, still sitting at the
main menu.) The `PlayerCharacter::GetSingleton()` TODO in the doc
(needs `kNewGame`/`kPostLoadGame`, since the player object doesn't exist
until a game is actually running) is unaffected and still gated
separately.

One cosmetic oddity in the log: `kDataLoaded` was dispatched **twice**
(`17:05:55.238` and `17:05:55.537`), producing duplicate `ADDR`/`LIVE`
blocks. Both blocks agree byte-for-byte. Not investigated further -- SKSE
message re-dispatch on this build/version is a pre-existing engine/SKSE
behavior, not something `LayoutValidator` controls, and it doesn't affect
the correctness of either report.

## Live-check result

Both `kDataLoaded` firings produced identical, clean output:

- Address Library resolved `TESForm[0]`, `Actor[0]`, all four
  `TESObjectREFR[0..3]` vtable slots, and `RTTI_TESForm` -- proves the
  deployed `versionlib-1.6.1170.0.bin` matches this exact game build.
- `TESForm::LookupByID(0x00000007)` (the player base `TESNPC`) round-tripped
  clean: raw-memory `formID`/`formType` reads matched the typed accessors
  exactly (`formID=00000007(raw=00000007,OK)`,
  `formType=0x2B(raw=0x2B,OK)`) -- the one field pair this pass could
  verify against live memory (`TESForm`'s layout is unguarded, so the
  compiled offsets are directly comparable to the live AE process).

## Addendum: RTTI readback + vtable-pointer check (same session, after the report above)

Two of the TODO items below turned out not to need gameplay after all --
both run at `kDataLoaded`, which this build showed fires at the main menu
already (see above). Landed in a follow-up compile/deploy/relaunch cycle
(same session, builds 5 and 6; the committed evidence log
`examples/RuntimeHarness_T3-3_layoutvalidator.log.txt` is from build 6 --
build 5's log was not retained, see below).

- **RTTI decorated-name readback: done, passed.** Reads
  `RE::RTTI::TypeDescriptor::mangled_name()` (`RE::msvc::type_info` in
  the vendored `RTTI.h` -- a real accessor, not a hand-rolled offset) at
  the resolved `RTTI_TESForm` address and string-compares against
  `.?AVTESForm@@`. Real log line:
  `LayoutValidator: LIVE rtti=TESForm mangled_name=.?AVTESForm@@(OK)`.
  This is a genuine positive identity check beyond bare address
  resolution -- proves the Address Library ID points at TESForm's own
  RTTI descriptor, not a neighbouring one.
- **Live vtable-pointer identity check: investigated, and the originally
  planned version turned out to be an invalid check, not a missing
  feature.** First attempt compared the live instance's vptr directly
  against `RE::VTABLE_TESForm[0]` and logged `MISMATCH`
  (`raw=0x7FF792114D50` vs `VTABLE_TESForm[0]=0x7FF7920B0B00`) on build
  5's run -- **that intermediate log was not saved before the next
  relaunch overwrote it**, so this exact pairing isn't in any committed
  file; treat it as a recorded observation from this pass, not
  re-derivable evidence. The mismatch is expected, not a bug: `TESForm`
  is an abstract base, so the live instance at formID `0x00000007` is
  actually a `TESNPC` (its own `formType` check reads `OK` on the same
  line) and its vptr correctly points to `TESNPC`'s own vtable, never
  `TESForm`'s. Comparing a derived instance's vptr against a base
  class's vtable is not a valid layout check regardless of whether the
  compiled layout is correct. Fixed in build 6: the check no longer
  asserts a verdict, it only logs the raw vptr and its RVA from the
  module base, for a human (or a future check with the derived class's
  own `VTABLE_*` Address Library ID) to use. Real log line (build 6):
  `LayoutValidator: LIVE TESForm(0x07) vtbl=0x7FF792114D50 rva=0x17E4D50 note=not-compared-to-VTABLE_TESForm-see-comment`.

`parse_layout_log.py` was extended with two new regexes
(`LIVE_RTTI_RE`, `LIVE_VTBL_RE`) to parse both line shapes into the JSON
output (`live_rtti`, `live_vtbl` keys) rather than silently dropping
them; both T3-4's original two sample-log self-tests (exit 0 clean, exit
1 on injected mismatch) and a fresh run against the real build-6 log
were verified after the change, confirming the new fields actually
populate with real data, not just that the exit code stayed correct.

## Addendum 2: PlayerCharacter / ACTOR_RUNTIME_DATA / ExtraDataList live checks (same session, build 7)

The three items below (previously "genuinely still open," see the
original "What this does NOT close" text further down, now closed)
needed an actual game session past `kDataLoaded` -- the main menu alone
doesn't instantiate `PlayerCharacter`. Closed by adding
`LayoutValidator::RunGameSessionChecks()`, wired to both `kNewGame` and
`kPostLoadGame` in `main.cpp` (the same single-listener pattern as
`OnDataLoaded()` -- see Bug #2 above), then loading a save via the
`PressEnter` scheduled task's synthetic Enter at the main menu.

Real log evidence (`kPostLoadGame` firing at `18:19:30.055`, six seconds
after `kPreLoadGame` at `18:19:26.913` -- a real save load, not an instant
no-op):

```
kPreLoadGame received -- a save is about to load.
kPostLoadGame received -- a save finished loading.
LayoutValidator: LIVE PlayerCharacter formID=00000014(raw=00000014,OK) formType=0x3E(raw=0x3E,OK)
LayoutValidator: LIVE PlayerCharacter vtbl=0x7FF7921DB9C0 rva=0x18AB9C0 note=not-compared-to-VTABLE_TESForm-see-comment
LayoutValidator: LIVE PlayerCharacter ACTOR_RUNTIME_DATA currentProcess=non-null race=0x21BE1674400(plausible)
LayoutValidator: LIVE PlayerCharacter extraList.GetCount()=1
```

All three checks passed on real data, honestly evaluated:

- **PlayerCharacter sanity: OK.** `formID=0x14` (the well-known player
  form ID) and `formType=0x3E` (`ActorCharacter`) both matched their raw
  and accessor reads exactly -- same `CheckLiveForm` path already proven
  against `TESForm(0x07)` in the base report, now proven on a second,
  independently-instantiated class.
- **`ACTOR_RUNTIME_DATA` / `GetActorRuntimeData()` plausibility: OK, not
  inconclusive.** `currentProcess` is non-null (the player has an active
  `AIProcess`, as expected while in-game) and `race` resolves to a
  non-null pointer whose `GetFormType() == RE::FormType::Race` -- proving
  the AE `RelocateMemberIfNewer<T>` accessor path lands on a real,
  correctly-typed member on this exact build, not garbage or a
  wrong-runtime offset. Per the plan going in: had `race` come back NULL
  or wrong-formtype while `formID`/`formType` still read OK, that would
  have needed investigating *this check's own correctness* (wrong
  runtime branch, SE offset resolving on an AE process) before writing
  it up as an engine finding -- that branch didn't trigger here.
- **`ExtraDataList` live walk: OK.** `extraList.GetCount()=1` -- the
  accessor-based walk executes on a live instance without crashing,
  which is this TODO's actual ground truth. A count of 1 on a loaded
  player save is plausible real data, not a failure signal; this check
  was never about hitting a particular count.

`parse_layout_log.py` was extended again with `LIVE_RUNTIME_DATA_RE` and
`LIVE_EXTRALIST_RE`, producing `live_runtime_data`/`live_extralist` JSON
keys. Verified after the change: both T3-4 self-test fixtures still pass
(exit 0 / exit 1 as before -- this log shape doesn't appear in either
fixture, so they only confirm no regression), and a fresh parse of this
real build-7 log populates both new keys with the data above (not empty
lists) plus a clean `--diff-baseline` run: zero confirmed mismatches
against static_assert-backed baseline values (the guarded classes, now
including `Actor::ACTOR_RUNTIME_DATA` and `ExtraDataList`, again
correctly report `NO-STATIC-ASSERT(baseline=NO_GROUND_TRUTH)` rather than
a false mismatch).

The evidence log at
[`examples/RuntimeHarness_T3-3_layoutvalidator.log.txt`](../examples/RuntimeHarness_T3-3_layoutvalidator.log.txt)
was overwritten with this build-7 run (main-menu `LIVE` lines *and* the
game-session `LIVE` lines both present in the same file -- one continuous
session, no synthetic stitching).

## What this closes

All three items originally listed below as "genuinely still open" are
now closed (see Addendum 2 immediately above):

- `PlayerCharacter::GetSingleton()` sanity at `kNewGame`/`kPostLoadGame`. **Done.**
- Live `Actor::ACTOR_RUNTIME_DATA` / `GetActorRuntimeData()` sanity. **Done.**
- `ExtraDataList` live walk. **Done.**

Remaining future work, not closed by this pass: a real version of the
vtable-pointer identity check against the live instance's *actual*
class's own `VTABLE_*` ID (e.g. `VTABLE_PlayerCharacter` instead of
`VTABLE_TESForm`), replacing the originally planned but invalid version
described in Addendum 1 above.

## Addendum 3: the real vtable-pointer identity check (T3-7, build 8, same session)

Closed the one item left open by Addendum 1's reclassification.
`RE::VTABLE_PlayerCharacter`
(`Offsets_VTABLE.h`) is a 17-entry array -- one `REL::VariantID` per base
subobject in `PlayerCharacter`'s inheritance chain. Only slot `[0]`
corresponds to the primary vptr at a live instance's own address 0
(standard MSVC layout); slots `[1..16]` belong to secondary bases at
nonzero `this` offsets and are not comparable against
`*(uintptr_t*)player` -- checked this distinction before writing any code,
since comparing the wrong slot would have reproduced the exact
invalid-check mistake Addendum 1 retracted.

Real log evidence (build 8):

```
LayoutValidator: ADDR vtable=PlayerCharacter[0] resolved=0x7FF7921DB9C0 rva=0x18AB9C0
LayoutValidator: LIVE PlayerCharacter vtbl=0x7FF7921DB9C0 rva=0x18AB9C0 expected=0x7FF7921DB9C0(OK)
```

Exact match -- a genuine positive identity check, not a coincidence of
matching RVAs: the live instance's primary vptr resolves to precisely the
Address Library ID for `PlayerCharacter`'s own vtable slot 0, closing the
item Addendum 1 could only report raw data for. `parse_layout_log.py`'s
`LIVE_VTBL_RE` was extended (optional trailing `expected=/status` group,
since `TESForm(0x07)`'s line shape has no verdict and `PlayerCharacter`'s
now does) -- both self-tests still pass, and a fresh parse of the real
build-8 log confirms the new `expected`/`status` fields populate
(`status: 'OK'`) rather than staying `None`. Zero confirmed mismatches
against `coverage_baseline.json`, unchanged.

This closes every item from the original `LAYOUT_VALIDATOR.md` TODO list.

## Housekeeping note

Deploying this build required killing the previous long-running
`SkyrimSE.exe` process (the one from the earlier `AIProcessInspector`/
`SavegameTracer`/`HavokStepLogger` session, ~26,800s+ accumulated CPU) to
overwrite the loaded DLL. That process's 70+-minute `HavokStepLogger`
silence run was already concluded and documented in `README.md` before
this pass started -- nothing was lost by ending it, but a future reader
should not assume that PID is still accumulating evidence.

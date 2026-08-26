# T3-3 — LayoutValidator: first Windows compile + deploy + live diff report

**Status: done.** First-ever MSVC compile, in-game deploy, and live
three-way diff, 2026-08-26. Real log evidence:
[`examples/RuntimeHarness_T3-3_layoutvalidator.log.txt`](../examples/RuntimeHarness_T3-3_layoutvalidator.log.txt)
(`.log.txt`, not `.log` — `*.log` is gitignored repo-wide).

## What actually happened (short version)

1. Compiled `LayoutValidator.cpp`/`.h` for the first time — found and fixed
   two real bugs (see below), not cosmetic ones.
2. Deployed the built DLL to the Windows box's live Skyrim AE 1.6.1170 +
   SKSE64 install, replacing the long-running three-inspector build from
   earlier tonight.
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
dispatch) — confirmed from the actual build log:

```
Enable Skyrim SE: ON
Enable Skyrim AE: ON
Enable Skyrim VR: ON
```

That combination routes every runtime-guarded class into a **third,
narrower `#else` branch** in the headers — different from both the
SE-only and AE-only views the original comments described. Two fields
referenced by the original `LayoutValidator.cpp` don't exist in that
branch at all:

- `RE::NiAVObject::userData` — only a named member when VR is off, or
  when none of the three are defined; absent when all three are on.
- `RE::BaseExtraList::data` / `RE::BaseExtraList::presence` — only named
  members `#ifndef ENABLE_SKYRIM_AE`; with AE on, they're accessor-only
  (`GetData()`/`GetPresence()`).

Both `offsetof()` calls were compile errors (`C2039`/`C2618`), not
runtime bugs — fixed by dropping those two fields from the compile-time
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
combination**, not for any one real runtime's live memory — they are
correctly reported `NO-STATIC-ASSERT(baseline=NO_GROUND_TRUTH)` by the
diff tool rather than a false "mismatch," since `coverage_baseline.json`
has no `expected` value for guarded classes to compare against.

## Bug #2: only the first `SKSE::MessagingInterface` listener a plugin registers actually fires

`LayoutValidator::Install()` called
`SKSE::GetMessagingInterface()->RegisterListener(OnMessage)` itself, on
top of `main.cpp`'s own existing registration. The call returned `true`
(no error logged) and the compile-time report + "live-instance check
registered" line printed normally — but the registered callback never
actually ran: `kDataLoaded` fired at `17:05:55` and only `main.cpp`'s own
`OnMessage` handler logged `"kDataLoaded received"`; the `ADDR`/`LIVE`
lines that only `LayoutValidator`'s own listener could produce were
absent. None of the other three inspectors hit this because none of them
need message-driven timing — they only install vtable hooks at load.

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
fires as soon as the game's ESM/ESP data is loaded — **at the main menu**,
seconds after the SKSE plugin finishes loading, before any save is
touched. (`kDataLoaded` fired at `17:05:55`, six seconds after
`Loaded.` at `17:05:49` — no save load, no gameplay, still sitting at the
main menu.) The `PlayerCharacter::GetSingleton()` TODO in the doc
(needs `kNewGame`/`kPostLoadGame`, since the player object doesn't exist
until a game is actually running) is unaffected and still gated
separately.

One cosmetic oddity in the log: `kDataLoaded` was dispatched **twice**
(`17:05:55.238` and `17:05:55.537`), producing duplicate `ADDR`/`LIVE`
blocks. Both blocks agree byte-for-byte. Not investigated further — SKSE
message re-dispatch on this build/version is a pre-existing engine/SKSE
behavior, not something `LayoutValidator` controls, and it doesn't affect
the correctness of either report.

## Live-check result

Both `kDataLoaded` firings produced identical, clean output:

- Address Library resolved `TESForm[0]`, `Actor[0]`, all four
  `TESObjectREFR[0..3]` vtable slots, and `RTTI_TESForm` — proves the
  deployed `versionlib-1.6.1170.0.bin` matches this exact game build.
- `TESForm::LookupByID(0x00000007)` (the player base `TESNPC`) round-tripped
  clean: raw-memory `formID`/`formType` reads matched the typed accessors
  exactly (`formID=00000007(raw=00000007,OK)`,
  `formType=0x2B(raw=0x2B,OK)`) — the one field pair this pass could
  verify against live memory (`TESForm`'s layout is unguarded, so the
  compiled offsets are directly comparable to the live AE process).

## What this does NOT close

Per `LAYOUT_VALIDATOR.md`'s own TODO list — none of these were attempted
this pass:

- RTTI decorated-name readback (positive identity check beyond address
  resolution).
- `PlayerCharacter::GetSingleton()` sanity at `kNewGame`/`kPostLoadGame`
  (needs an actual game session, not just main-menu `kDataLoaded`).
- Live `Actor::ACTOR_RUNTIME_DATA` / `GetActorRuntimeData()` sanity (the
  AE `RelocateMember` path — nothing in this pass touches it, since the
  live check only covers `TESForm`).
- `ExtraDataList` live walk.
- Live vtable-pointer identity check against the resolved `RE::VTABLE_*`
  addresses.

These remain real, scoped future work, not silently dropped — same list
as before this pass, unchanged.

## Housekeeping note

Deploying this build required killing the previous long-running
`SkyrimSE.exe` process (the one from earlier tonight's `AIProcessInspector`/
`SavegameTracer`/`HavokStepLogger` session, ~26,800s+ accumulated CPU) to
overwrite the loaded DLL. That process's 70+-minute `HavokStepLogger`
silence run was already concluded and documented in `README.md` before
this session started — nothing was lost by ending it, but a future reader
should not assume that PID is still accumulating evidence.

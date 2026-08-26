# Patch 0027: fix `mine_static_asserts.py`'s brace/depth desync across untaken preprocessor branches

**Note on numbering**: like patch 0026, this one does not touch the
vendored `GhidraClangPoweredParse` submodule at all -- no `.patch` file
accompanies this doc. The bug and the fix are entirely in
`type-importer/scripts/mine_static_asserts.py`, the ground-truth miner
used by `coverage_report.py`/`check_regression.py`, not the parser
itself. Numbered into the same sequence for traceability (found while
investigating T1-7, flagged as a "future pass" lead in patch 0026's own
writeup) and because it changes `coverage_baseline*.json` the same way a
submodule patch would.

## Task: T1-7 (BACKLOG.md) -- the `RUNTIME_DATA2` name collision

Patch 0026's writeup flagged a loose end: three unrelated classes
(`Console`, `MapMenu`, `NiCamera`) each declare their own nested
`RUNTIME_DATA2` struct with different real sizes (no static_assert,
0x138, and 0x38 respectively). `mine_static_asserts.py`'s ground-truth
map was observed picking one arbitrarily for the bare, unqualified name
`RUNTIME_DATA2` -- "a real, separate bug in the ground-truth miner (or
in how nested-type names are recorded)", left undiagnosed.

## Root cause, confirmed empirically -- not the parser, not a real 3-way collision

`mine_static_asserts.py` already qualifies a `static_assert` with its
enclosing class(es) via a `record_stack` (patch 0011's convention,
`Outer::Inner`), built by tracking brace depth as it scans each header
line-by-line. That tracking is a heuristic, not a real preprocessor --
and it counts every `{`/`}` character on every line **unconditionally**,
regardless of which branch of an `#if`/`#elif`/`#else` chain is actually
taken for the target runtime.

`RE/N/NiCamera.h`'s `RUNTIME_DATA` struct exposes exactly this:

```cpp
struct RUNTIME_DATA
{
#ifndef ENABLE_SKYRIM_VR
	...
		};
		static_assert(sizeof(RUNTIME_DATA) == 0x40);
#elif !defined(ENABLE_SKYRIM_AE) && !defined(ENABLE_SKYRIM_SE)
	...
		};
		static_assert(sizeof(RUNTIME_DATA) == 0x98);
#else
	...
		};
#endif

	struct RUNTIME_DATA2
	{
		...
	};
	static_assert(sizeof(RUNTIME_DATA2) == 0x38);
```

The struct's opening `{` appears once, unconditionally, right after
`struct RUNTIME_DATA`. Its closing `};` appears **three times** -- once
per branch -- because each branch is a self-contained alternative body
for the same struct. The old scanner counted all three closes
regardless of which branch was active for the target runtime, so for
every runtime it over-popped `record_stack` by one extra frame past the
struct's own frame -- taking `NiCamera` itself off the stack. Every
subsequent `static_assert` in the file (here, `RUNTIME_DATA2`'s) then
mined under an empty/wrong record stack, producing a bare, unqualified
`RUNTIME_DATA2` key instead of `NiCamera::RUNTIME_DATA2`.

That bare key then collided in the flat `{ClassName: size}` output with
nothing else, in the strict sense: `Console::RUNTIME_DATA2` has no
static_assert at all (never entered the map), and `MapMenu::RUNTIME_DATA2`
was, on inspection, **already correctly qualified** before this fix --
`MapMenu.h` has no analogous brace-count asymmetry earlier in the file.
So there was never a genuine 3-way key collision; there was one
desynced class (`NiCamera`) whose real, correctly-sized assert (0x38)
surfaced under the wrong (bare) key, which coincidentally read as
"colliding" with `MapMenu::RUNTIME_DATA2`'s already-correct entry only
because both are named `RUNTIME_DATA2` in isolation.

## The fix

Skip the record-scope bookkeeping (both `pending`-record detection and
brace/depth counting) entirely for any line inside a branch that's
**definitively not taken** for the target runtime -- i.e.
`not currently_active() and not any_unevaluated()`, the same
active/ambiguous/unevaluated distinction the assert-recording code a few
lines above already uses to bucket results/ambiguous/unevaluated. A
branch whose guard couldn't be evaluated (`any_unevaluated()`) is left
alone, matching the existing conservative "best effort" behavior for
guards this script can't resolve.

```python
if not currently_active() and not any_unevaluated():
    continue
```

placed immediately before the existing `template`/`RECORD_DECL_RE`/
brace-counting block in `scan_file()`. One guard clause, no other lines
changed.

## Verification

Confirmed directly before running any full sweep: `mine_static_asserts.py`
against the real headers, `--runtime ENABLE_SKYRIM_AE`, before (via
`git stash`) and after the fix -- output identical across all 2149
entries **except exactly one rename**: `RUNTIME_DATA2` (56) ->
`NiCamera::RUNTIME_DATA2` (56), same value. Zero collateral changes.

Full 1630-header sweeps on all three runtimes (AE, SE, VR), patch set
0001-0025 (submodule, unchanged) + patch 0026 (`GenerateGdt.java`,
unchanged) + this fix (`mine_static_asserts.py` only), via
`scripts/generate_gdt.sh` + `scripts/mine_static_asserts.py` +
`scripts/coverage_report.py` + `scripts/check_regression.py` against
each runtime's previously-committed (post-0026) baseline:

- **AE**: 0 regressions, 1 improvement. `NiCamera::RUNTIME_DATA2`:
  NO_GROUND_TRUTH -> OK. UNRESOLVED 17 -> 16 (the bogus bare
  `RUNTIME_DATA2` entry is gone, not replaced).
- **SE**: 0 regressions, 1 improvement, identical to AE.
- **VR**: 0 regressions, **2** improvements -- VR also flips
  `NiCamera::RUNTIME_DATA` (not just `RUNTIME_DATA2`) from
  NO_GROUND_TRUTH to OK, because VR is the `#elif` branch in the same
  `RUNTIME_DATA` chain, and its own static_assert
  (`sizeof(RUNTIME_DATA) == 0x98`... VR-specific value 152 decimal for
  the branch actually taken here) was subject to the identical
  desync-before-you-even-reach-it mechanism for that runtime's
  branch selection. UNRESOLVED 18 -> 16.

This is a **narrow, single-class-family fix**, not a broad regression
sweep like 0025 or 0026 -- it corrects exactly the ground-truth
bookkeeping for one file's brace-asymmetric preprocessor chain that
happened to be observed. It is not claimed to fix every possible
instance of this class of bug across all 1630 headers; no other
`#if`/`#elif`/`#else` chain with brace-count asymmetry was found or
searched for exhaustively during this pass -- the mechanism is now
understood and fixed at the source (any file with the same shape
benefits automatically), but a full audit for other affected files
was out of scope here.

`coverage_baseline.json`, `coverage_baseline_se.json`,
`coverage_baseline_vr.json` all updated to reflect the confirmed
improvements above.

## How to apply

No submodule patch -- the fix is directly in
`type-importer/scripts/mine_static_asserts.py`, already in the working
tree. Nothing to apply.

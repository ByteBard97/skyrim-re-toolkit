# Patch 0014: qualify nested enums + materialize known types on demand

## Root cause of the runner-only cascade, finally named

Patch 0013's upgraded `GCPP_DEBUG_DEPS` trace on the hosted runner
(run in `traced_run.id`'s dispatch) printed the smoking gun:

    [DEPS] 'BGSDirectionalAmbientLightingColors' blocked by 'Color'
           exactNameCandidates=0 parsedEntry=ParsedEnum@/MistMenu.h

The pool's entry for the bare key `Color` was MistMenu's nested
`enum Color` -- not the top-level `RE::Color` struct. Enums were patch
0011's deliberate phase-1 exclusion from record-qualification, and a
struct-vs-enum contest for a bare key has no tiebreaker (the
keep-more-fields heuristic only compares two ParsedStructures), so
different machines kept different winners. That is the entire remaining
CI-vs-local nondeterminism.

## The fix, two halves

1. **`parseEnum` registers record-qualified names** (`MistMenu::Color`),
   exactly like structs/unions since 0011. This alone flipped 46 classes
   better locally (`Color: UNRESOLVED -> OK` among them -- the enum had
   been shadowing the struct in the pool even on the dev machine).

2. **On-demand materialization, at every peel step.** Qualifying enums
   exposed the next latent defect: `DisguiseEffect::State` (nested enum,
   correctly registered) was not yet materialized in the DTM when its
   owner's field resolved, so 0011's qualifier peeling fell through to
   the bare `State` -- now an uncontested 152-byte struct -- inflating
   DisguiseEffect 152 -> 296. Resolution must never peel PAST a name the
   pool knows: `TypePool.getType` now materializes an exactly-matching
   parsed entry on demand (with a `materializing` guard set breaking
   embed cycles), both for the original name and for each peeled suffix
   (canonical references like `RE::DisguiseEffect::State` only match
   their pool key after one peel).

## Verification (full sweep, JDK 25 + JIT)

- **Zero regressions, 46 improvements** vs the committed baseline;
  OK 1668 -> 1701. `DisguiseEffect` back to its correct 152.
- Baseline updated with this patch's acceptance (locks the 46).
- Runner validation: the CI run for this commit is the machine this
  entire 0012/0013/0014 chain exists to fix -- see its verdict.

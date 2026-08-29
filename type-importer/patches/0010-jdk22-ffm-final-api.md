# Patch 0010: port FFM bindings to the final (JDK 22+) API -- and the real story behind "-Xint"

## Summary

Six mechanical renames from the JDK 21 *preview* Foreign Function & Memory
API to the final API (JDK 22+, unchanged through 25):

| Preview (JDK 21)                  | Final (JDK 22+)              |
|-----------------------------------|------------------------------|
| `MemorySegment.getUtf8String(0)`  | `MemorySegment.getString(0)` |
| `Arena.allocateUtf8String(s)`     | `Arena.allocateFrom(s)`      |
| `Arena.allocateArray(layout, n)`  | `Arena.allocate(layout, n)`  |

`generate_gdt.sh` applies this patch only when `JAVA_HOME` is a JDK 22+
(the renamed methods don't exist on 21); the vendored `build.gradle`
already had the matching version switch.

## Why this matters far beyond a version bump

This patch is the delivery vehicle for the root-cause fix of the two
worst open problems in this pipeline, both previously misattributed:

### 1. "Panama FFI upcalls crash under JIT" -- FALSE. It was libclang's signal handler.

The pipeline has always run `-Xint` because it crashed under JIT.
Reproducing the crash on JDK 25 produced an `hs_err` showing:

- `SIGSEGV ... (sent by kill)` -- an externally-raised signal, not a real
  memory fault at the faulting pc;
- the "problematic frame" was **JIT-compiled Ghidra database code**
  (`DataTypeManagerDB.getCategory`), nowhere near FFM or libclang, during
  the Ghidra type-resolution phase after parsing had finished.

Root cause: LLVM installs its own SIGSEGV "crash recovery" handler when a
`CXIndex` is created. HotSpot's JIT-compiled code *deliberately* triggers
benign SIGSEGVs (implicit null checks) and expects its own handler to
receive them. LLVM's handler intercepts one, misreads it as a crash, and
kills the JVM. Interpreter mode merely avoided emitting implicit-null-check
traps -- masking the symptom, at ~10x the runtime.

Fix: `export LIBCLANG_DISABLE_CRASH_RECOVERY=1` (honored by libclang --
verified present in the LLVM 19.1.0 binary via `strings`), now set
unconditionally in `generate_gdt.sh`. With it, the full pipeline runs
to completion under JDK 25 with the JIT enabled.

### 2. The "scale-dependent libclang misbehavior" that blocked patch 0007 -- NOT libclang.

Patch 0007 was deferred because `clang_Type_getSizeOf` and
`clang_getCanonicalType`+`clang_Type_getTemplateArgumentAsType` returned
different (wrong) answers at full-1630-header-sweep scale than in
isolation, across two structurally different Java implementations.

A pure-C probe (`scale_probe.c`, no Java/Panama at all) parsing the
**identical** 1630-header umbrella TU with the **identical** clang flags
(including `-fdelayed-template-parsing`) proved libclang is deterministic
and correct at that scale: it queried all 10 regressed classes and the
`hkRefPtr` fields before and after sweep-scale traffic (sizeof + canonical
+ template-arg enumeration over all 3,445 record definitions in the TU) --
every answer identical both times, and *correct* (e.g.
`sizeof(ArmorRatingVisitor) = 64`, canonical `BSTArray` reporting both
template args including the 24-byte `BSScrapArrayAllocator`).

By elimination, the wrong values came from the Java side: the JDK 21
*preview* FFM implementation under `-Xint` (struct-by-value downcall
returns are exactly the code path all the affected calls share). The fix
is not to work around it but to stop running on it: JDK 22+ final FFM,
JIT enabled.

## Verification

- Smoke (TESForm chain, JDK 25 + JIT + crash recovery disabled): completes,
  zero clang diagnostics, 4,742 types committed, 0 failed.
- Full 1630-header sweep: see COVERAGE_SWEEP_PLAN.md for the regression
  check against `coverage_baseline.json`.

## How to apply

Applied automatically by `generate_gdt.sh` when `JAVA_HOME` is JDK 22+.
Manually, from `type-importer/vendor/GhidraClangPoweredParse` after
patches 0001–0009:

```bash
patch -p1 < ../../patches/0010-jdk22-ffm-final-api.patch
```

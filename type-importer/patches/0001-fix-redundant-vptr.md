# Patch 0001: fix redundant vptr field in GhidraClangPoweredParse

**Status: written, applied, and functionally verified end-to-end
(2026-08-24) against a real build of the extension using JDK 21 and Ghidra
12.1.3. This is the "redundant-vptr bug on polymorphic derived classes"
flagged as an unresolved known limitation in DESIGN.md.**

## The bug

`SourceParser.parseStruct` (in the vendored
`type-importer/vendor/GhidraClangPoweredParse` submodule) unconditionally
adds a synthetic `vptr` struct field whenever a class declares or overrides
any virtual method or destructor, with no check for whether a base class
already provides one:

```java
// original code, SourceParser.java:351-365
if (!virtualMethods.isEmpty()) {
    String vtableName = name + "_vtable";
    pool.addParsedType(new ParsedVtable(vtableName, virtualMethods, name, category));
    allFields.add(new ParsedStructure.FieldInfo(
        "vptr", vtableName + " *", false, 0, false, null));
}
for (String[] base : baseClasses) {
    allFields.add(new ParsedStructure.FieldInfo(base[0], base[1], false, 0, false, null));
}
```

In MSVC/Itanium ABI, overriding a base class's virtual method does **not**
add a new vptr -- it changes an entry in the vtable already inherited from
the primary base. Any class that overrides even one virtual from a
polymorphic base gets a spurious extra field here, on top of the correct
vptr already embedded as the first member of that base's own field. Every
subsequent field shifts by 8 bytes, and the total struct size is wrong.

This isn't an edge case -- it fires on essentially every override in an
inheritance chain, including CommonLibSSE-NG's `TESObjectREFR` (our actual
v0.1 target), which overrides base `TESForm` virtuals.

## The fix

Track each base's declaration `Cursor` alongside its field info, add a
recursive `isPolymorphic(Cursor)` helper that checks a class (or any of its
own bases, recursively) for a virtual method/destructor, and only emit the
synthetic vptr when the primary base is *not* already polymorphic:

```java
boolean primaryBaseIsPolymorphic = !baseDeclCursors.isEmpty()
    && isPolymorphic(baseDeclCursors.get(0));

if (!virtualMethods.isEmpty() && !primaryBaseIsPolymorphic) {
    // ... emit synthetic vptr, as before
}
```

Full diff: `0001-fix-redundant-vptr.patch` in this directory.

## Known limitation this does NOT fix

`ParsedVtable` still creates a **fresh** `<ClassName>_vtable` type per class
that declares virtual methods (when it's the vtable root). It does not model
"this class's overrides replace specific slots in the inherited vtable, and
its new virtuals append to it." For pure layout/size purposes (what the
type-importer needs for a `.gdt`) this is fine -- the fix's job was only to
stop the field-count/offset corruption. A fully accurate vtable *contents*
model (which slots are overridden vs. new) is a separate, larger piece of
work, not attempted here.

## How this was verified (not just reasoned about)

1. Built the unpatched extension for real (`./gradlew
   createDistribution_linux_x86_64`) against JDK 21 (Temurin
   21.0.12.1+1, user-local install, no sudo) and Ghidra 12.1.3 (also
   user-local, no sudo).
2. Wrote a standalone Java harness (not committed -- it's a throwaway
   validation tool, see below if you want to reproduce it) that:
   - Initializes Ghidra's `Application` framework headlessly
     (`GhidraApplicationLayout` + `ApplicationConfiguration`) so
     `StandAloneDataTypeManager` can be constructed outside a running
     Ghidra GUI/headless-analyzer process.
   - Calls `SourceParser.parseFiles(...)` directly against a synthetic
     `.hpp` reproducing `TESObjectREFR`'s exact shape: a primary
     polymorphic base whose virtual method gets overridden, plus a
     secondary polymorphic base with no override.
   - Resolves the `TypePool` and inspects the resulting `Structure`'s
     fields.
   - Ran with `-Xint` per the extension's own documented JIT-crash
     workaround (Panama FFI upcalls crash under JIT compilation on this
     JDK).
   - Loaded libclang via the system's existing `libclang-14.so.13`
     (symlinked locally to the versioned name the extension's Linux
     fallback loader searches for -- the extension's own bundled
     `os/linux_x86_64/libclang.so` needs a running Ghidra `Application`
     module-resource system to locate, which this standalone harness
     doesn't have).
3. **Before the fix:** the harness showed a `vptr` field at offset 0x0 on
   the derived class, in addition to the primary base's own already-correct
   vptr embedded in its field right after -- the bug, reproduced live.
4. **After the fix:** zero `vptr` fields directly on the derived class; it
   correctly relies on the inherited one from its primary base. Ran a clean
   A/B: reverted to the unpatched file, rebuilt, reproduced the bug;
   reapplied the patch, rebuilt, confirmed the fix; reverted the vendored
   submodule's working tree back to pristine afterward (per this repo's own
   convention of not committing changes into `vendor/`).

## How to apply

From `type-importer/vendor/GhidraClangPoweredParse`:

```bash
patch -p1 < ../../patches/0001-fix-redundant-vptr.patch
```

Verified to apply cleanly against the submodule's current pinned commit.

## Toolchain notes for reproducing the build/test

- JDK: Temurin 21.0.12.1+1 Linux x64, user-local (no sudo available on this
  box) -- `~/.local/tools/jdk-21.0.12.1+1`.
- Ghidra: 12.1.3 (`Ghidra_12.1.3_build`), user-local --
  `~/.local/tools/ghidra_12.1.3_PUBLIC`.
- Build: `GHIDRA_INSTALL_DIR=... JAVA_HOME=... ./gradlew
  createDistribution_linux_x86_64 --offline` (add `--offline` after the
  first run once Gradle's own wrapper distribution and dependencies are
  cached).
- Neither JDK nor Ghidra are vendored in this repo -- same reasoning as the
  Windows SDK/CRT headers in `DESIGN.md`'s toolchain note: large,
  license-bearing or simply huge, and trivially re-downloadable.

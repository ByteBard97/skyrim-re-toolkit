# Worked example: a `TESObjectREFR` virtual, before and after

Both files are real Ghidra decompiler output for the **same function** at
`0x1401e1270` in Skyrim SE 1.6.1170 (a virtual in `TESObjectREFR`'s vtable,
reached by walking the binary's own MSVC RTTI). The only difference is
whether this repo's generated `.gdt` type archive was applied.

## Before — no types (`before_TESObjectREFR_vfunc.c`)

```c
void FUN_1401e1270(longlong *param_1,undefined8 param_2)
{
  ...
  uVar4 = *(uint *)(param_1 + 2);                       // what is +0x10?
  ...
  *(undefined1 *)((longlong)param_1 + 0x1a) = *(undefined1 *)(lVar2 + 0x1a);
  *(uint *)(param_1 + 2) =
       (uVar4 ^ *(uint *)(lVar2 + 0x10)) & 0x4000 ^ *(uint *)(lVar2 + 0x10);
  ...
}
```

Raw offset arithmetic. `param_1 + 2` is byte offset `0x10` — but of *what*?
`0x4000` is a magic number. The `(**(code **)(*param_1 + 0x120))(param_1)`
call is an unlabeled vtable slot.

## After — archive applied, `this` typed as `TESObjectREFR*`

```c
void FUN_1401e1270(TESObjectREFR *self)
{
  ...
  uVar4 = (self->super_TESForm).formFlags;             // <- +0x10 named
  if (((byte)(uVar4 >> 1) & 1) != ...) {
    (*(self->super_TESForm).super_BaseFormComponent.vptr[9]...)(...);  // <- vtable slot
    uVar4 = (self->super_TESForm).formFlags;
  }
  (self->super_TESForm).formType._impl = *(uchar *)(lVar2 + 0x1a);      // <- +0x1a named
  (self->super_TESForm).formFlags =
       (uVar4 ^ *(uint *)(lVar2 + 0x10)) & 0x4000 ^ *(uint *)(lVar2 + 0x10);
  ...
}
```

Now the same code reads as what it is: this virtual **copies a specific bit
(`0x4000`) of `formFlags` and the `formType` from another form onto this
one**. `+0x10` was `TESForm::formFlags`; `+0x1a` was `TESForm::formType`.
The offsets came from CommonLibSSE-NG's headers, and CI validates them
against those headers' own `static_assert`s on every change.

This is the whole value in one function: **the crash log / disassembly
gives you an address and an offset; the type archive tells you what the
offset means.**

## Reproduce

```bash
# 1. unpack SteamStub DRM (Windows/.NET tool; see ../README.md)
Steamless.CLI.exe SkyrimSE.exe          # -> SkyrimSE.exe.unpacked.exe
# 2. one command: analyze + apply types + export before/after
JAVA_HOME=... GHIDRA_INSTALL_DIR=... \
  ../analyze_skyrim.sh SkyrimSE.exe.unpacked.exe CommonLibSSE_AE.gdt ./work 0x1401e1270
```

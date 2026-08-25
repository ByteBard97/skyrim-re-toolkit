// ==== 0x1401e1270 ====
// function: FUN_1401e1270 @ 1401e1270

void FUN_1401e1270(TESObjectREFR *self)

{
  undefined4 uVar1;
  longlong lVar2;
  undefined4 *puVar3;
  uint uVar4;
  longlong unaff_GS_OFFSET;
  
  puVar3 = (undefined4 *)
           (*(longlong *)(*(longlong *)(unaff_GS_OFFSET + 0x58) + (ulonglong)_tls_index * 8) + 0x768
           );
  uVar1 = *puVar3;
  *puVar3 = 0x65;
  lVar2 = __RTDynamicCast();
  if (lVar2 != 0) {
    uVar4 = (self->super_TESForm).formFlags;
    if (((byte)(uVar4 >> 1) & 1) != ((byte)(*(uint *)(lVar2 + 0x10) >> 1) & 1)) {
      (*(self->super_TESForm).super_BaseFormComponent.vptr[9].~BaseFormComponent)
                ((BaseFormComponent *)self);
      uVar4 = (self->super_TESForm).formFlags;
    }
    (self->super_TESForm).formType._impl = *(uchar *)(lVar2 + 0x1a);
    (self->super_TESForm).formFlags =
         (uVar4 ^ *(uint *)(lVar2 + 0x10)) & 0x4000 ^ *(uint *)(lVar2 + 0x10);
  }
  *puVar3 = uVar1;
  return;
}



// ==== 0x1401e1270 ====
// function: FUN_1401e1270 @ 1401e1270

void FUN_1401e1270(longlong *param_1,undefined8 param_2)

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
  lVar2 = __RTDynamicCast(param_2,0,&PTR_PTR_142038118,&PTR_PTR_142038168,0);
  if (lVar2 != 0) {
    uVar4 = *(uint *)(param_1 + 2);
    if (((byte)(uVar4 >> 1) & 1) != ((byte)(*(uint *)(lVar2 + 0x10) >> 1) & 1)) {
      (**(code **)(*param_1 + 0x120))(param_1);
      uVar4 = *(uint *)(param_1 + 2);
    }
    *(undefined1 *)((longlong)param_1 + 0x1a) = *(undefined1 *)(lVar2 + 0x1a);
    *(uint *)(param_1 + 2) = (uVar4 ^ *(uint *)(lVar2 + 0x10)) & 0x4000 ^ *(uint *)(lVar2 + 0x10);
  }
  *puVar3 = uVar1;
  return;
}

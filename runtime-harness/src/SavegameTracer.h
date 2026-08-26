#pragma once

// SavegameTracer -- hooks BGSSaveLoadManager::ProcessEvent(BSSaveDataEvent)
// via vtable to observe save/load lifecycle activity and dump known
// savegame metadata (the third of the three planned inspectors -- see
// README.md).
//
// Hook point: RE::BGSSaveLoadManager is a genuine singleton
// (RE::BGSSaveLoadManager::GetSingleton()) with exactly one live
// instance, so unlike AIProcessInspector/HavokStepLogger there is only
// one concrete vtable to hook -- no Actor/Character-style multi-vtable
// trap here. RE::VTABLE_BGSSaveLoadManager[0] corresponds to the
// BSTEventSink<BSSaveDataEvent> base subobject (declared at offset 0x000
// in BGSSaveLoadManager.h, the primary base, so the vtable's `this` is
// BGSSaveLoadManager* directly with no pointer adjustment needed);
// ProcessEvent(const BSSaveDataEvent*, ...) is vfunc index 1 there
// (BGSSaveLoadManager.h's own "// 01" comment on that override).
//
// RE::BSSaveDataEvent and RE::BGSSaveLoadManagerEvent are both only ever
// forward-declared in the vendored CommonLibSSE-NG tree, never defined,
// so their payloads can't be read -- this inspector treats
// ProcessEvent firing as a pure lifecycle signal (a pointer, logged for
// identity only) and gets its real data instead from
// BGSSaveLoadManager::saveGameList, a BSTArray<BGSSaveLoadFileEntry*>
// that IS fully defined (BGSSaveLoadFileEntry has named fileName/
// playerName/playerTitle/location/playTime/raceName fields) -- dumped
// on every ProcessEvent(BSSaveDataEvent) firing, since that event is the
// save-list-changed notification.

namespace SavegameTracer
{
    // Installs the ProcessEvent(BSSaveDataEvent) hook. Must be called
    // after SKSE::Init() (write_vfunc needs the module base
    // REL::Relocation resolves against).
    void Install();
}

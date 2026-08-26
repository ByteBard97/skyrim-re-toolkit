#include "SavegameTracer.h"

#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

namespace SavegameTracer
{
    namespace
    {
        using ProcessEventFn = RE::BSEventNotifyControl (RE::BGSSaveLoadManager::*)(
            const RE::BSSaveDataEvent*, RE::BSTEventSource<RE::BSSaveDataEvent>*);

        REL::Relocation<ProcessEventFn> _ProcessEvent;

        void DumpSaveGameList()
        {
            auto* manager = RE::BGSSaveLoadManager::GetSingleton();
            if (!manager) {
                return;
            }

            SKSE::log::info("SavegameTracer: saveGameList has {} entries", manager->saveGameList.size());
            for (auto* entry : manager->saveGameList) {
                if (!entry) {
                    continue;
                }
                SKSE::log::info("  {} -- player '{}' ({}) at '{}', playtime {}",
                    entry->fileName.c_str(), entry->playerName.c_str(), entry->raceName.c_str(),
                    entry->location.c_str(), entry->playTime.c_str());
            }
        }

        RE::BSEventNotifyControl ProcessEvent_Hook(RE::BGSSaveLoadManager* a_this,
            const RE::BSSaveDataEvent* a_event, RE::BSTEventSource<RE::BSSaveDataEvent>* a_eventSource)
        {
            const auto result = _ProcessEvent(a_this, a_event, a_eventSource);

            SKSE::log::info("SavegameTracer: BSSaveDataEvent {} fired", static_cast<const void*>(a_event));
            DumpSaveGameList();

            return result;
        }
    }

    void Install()
    {
        REL::Relocation<std::uintptr_t> vtbl{ RE::VTABLE_BGSSaveLoadManager[0] };
        _ProcessEvent = vtbl.write_vfunc(1, ProcessEvent_Hook);
        SKSE::log::info("SavegameTracer: BGSSaveLoadManager::ProcessEvent(BSSaveDataEvent) hook installed.");
    }
}

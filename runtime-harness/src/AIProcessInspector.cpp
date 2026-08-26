#include "AIProcessInspector.h"

#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

#include <unordered_map>

namespace AIProcessInspector
{
    namespace
    {
        // Actor::Update is hooked on both RE::VTABLE_Actor and
        // RE::VTABLE_Character: live NPCs are RE::Character instances,
        // which have their own vtable array distinct from RE::Actor's
        // (Offsets_VTABLE.h) even though Character.h doesn't override
        // Update -- patching only VTABLE_Actor never touches Character
        // objects' vtable at all.
        REL::Relocation<decltype(&RE::Actor::Update)> _ActorUpdate;
        REL::Relocation<decltype(&RE::Actor::Update)> _CharacterUpdate;

        // formID -> last-logged package formID, so the log only records
        // package transitions instead of one line per actor per frame.
        std::unordered_map<RE::FormID, RE::FormID> g_lastPackage;

        void LogPackageIfChanged(RE::Actor* a_this)
        {
            auto* process = a_this ? a_this->GetActorRuntimeData().currentProcess : nullptr;
            if (!process || !process->InHighProcess()) {
                return;
            }

            auto* package = process->GetRunningPackage();
            const RE::FormID packageID = package ? package->GetFormID() : 0;

            auto [it, inserted] = g_lastPackage.try_emplace(a_this->GetFormID(), packageID);
            if (!inserted && it->second == packageID) {
                return;
            }
            it->second = packageID;

            if (package) {
                SKSE::log::info("actor {:08X} -> package {:08X} ({}) [{}]",
                    a_this->GetFormID(), packageID, package->GetFormEditorID(),
                    package->GetObjectTypeName());
            } else {
                SKSE::log::info("actor {:08X} -> package <none>", a_this->GetFormID());
            }
        }

        void ActorUpdate_Hook(RE::Actor* a_this, float a_delta)
        {
            _ActorUpdate(a_this, a_delta);
            LogPackageIfChanged(a_this);
        }

        void CharacterUpdate_Hook(RE::Actor* a_this, float a_delta)
        {
            _CharacterUpdate(a_this, a_delta);
            LogPackageIfChanged(a_this);
        }
    }

    void Install()
    {
        REL::Relocation<std::uintptr_t> actorVtbl{ RE::VTABLE_Actor[0] };
        _ActorUpdate = actorVtbl.write_vfunc(0xAD, ActorUpdate_Hook);

        REL::Relocation<std::uintptr_t> characterVtbl{ RE::VTABLE_Character[0] };
        _CharacterUpdate = characterVtbl.write_vfunc(0xAD, CharacterUpdate_Hook);

        SKSE::log::info("AIProcessInspector: Actor::Update hook installed (Actor + Character vtables).");
    }
}

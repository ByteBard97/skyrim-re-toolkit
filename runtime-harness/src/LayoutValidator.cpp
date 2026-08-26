#include "LayoutValidator.h"

#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

#include <cstddef>

namespace LayoutValidator
{
    namespace
    {
        // -----------------------------------------------------------------
        // Phase 1: compile-time layout report (runs at plugin load).
        //
        // Every line is emitted in a machine-readable
        //   "LayoutValidator: LAYOUT class=<name> sizeof=0xNNN off.<field>=0xNN ..."
        // format so `grep 'LayoutValidator: LAYOUT' RuntimeHarness.log` can be
        // diffed against type-importer/coverage_baseline.json (see
        // docs/LAYOUT_VALIDATOR.md). offsetof here is the plugin's COMPILED
        // view -- for runtime-divergent classes (Actor, TESObjectREFR,
        // BaseExtraList, TESObjectCELL) that is the SE layout, per the header
        // comment; unguarded classes are directly comparable to live memory.
        // -----------------------------------------------------------------

        void LogCompileTimeLayout()
        {
            // Unguarded layouts -- identical on SE/AE/VR, offsets are
            // directly checkable against live memory.
            SKSE::log::info("LayoutValidator: LAYOUT class=TESForm sizeof=0x{:X} off.formFlags=0x{:X} off.formID=0x{:X} off.formType=0x{:X}",
                sizeof(RE::TESForm), offsetof(RE::TESForm, formFlags),
                offsetof(RE::TESForm, formID), offsetof(RE::TESForm, formType));
            SKSE::log::info("LayoutValidator: LAYOUT class=NiAVObject sizeof=0x{:X} off.parent=0x{:X} off.local=0x{:X} off.world=0x{:X} off.worldBound=0x{:X} off.userData=0x{:X}",
                sizeof(RE::NiAVObject), offsetof(RE::NiAVObject, parent),
                offsetof(RE::NiAVObject, local), offsetof(RE::NiAVObject, world),
                offsetof(RE::NiAVObject, worldBound), offsetof(RE::NiAVObject, userData));
            SKSE::log::info("LayoutValidator: LAYOUT class=BGSLocation sizeof=0x{:X} off.parentLoc=0x{:X} off.keywordData=0x{:X} off.cleared=0x{:X}",
                sizeof(RE::BGSLocation), offsetof(RE::BGSLocation, parentLoc),
                offsetof(RE::BGSLocation, keywordData), offsetof(RE::BGSLocation, cleared));
            SKSE::log::info("LayoutValidator: LAYOUT class=TESQuest sizeof=0x{:X} off.currentStage=0x{:X} off.formEditorID=0x{:X}",
                sizeof(RE::TESQuest), offsetof(RE::TESQuest, currentStage),
                offsetof(RE::TESQuest, formEditorID));

            // Runtime-divergent layouts -- these are the SE-view offsets the
            // plugin actually compiled (no ENABLE_SKYRIM_AE in this build);
            // AE access goes through REL::RelocateMemberIfNewer accessors.
            SKSE::log::info("LayoutValidator: LAYOUT class=TESObjectREFR sizeof=0x{:X} off.data=0x{:X} off.parentCell=0x{:X} off.loadedData=0x{:X} off.extraList=0x{:X} note=se-view",
                sizeof(RE::TESObjectREFR), offsetof(RE::TESObjectREFR, data),
                offsetof(RE::TESObjectREFR, parentCell), offsetof(RE::TESObjectREFR, loadedData),
                offsetof(RE::TESObjectREFR, extraList));
            SKSE::log::info("LayoutValidator: LAYOUT class=Actor sizeof=0x{:X} note=se-view runtime-data-via=GetActorRuntimeData",
                sizeof(RE::Actor));
            SKSE::log::info("LayoutValidator: LAYOUT class=Actor::ACTOR_RUNTIME_DATA sizeof=0x{:X} off.currentProcess=0x{:X} off.currentCombatTarget=0x{:X} off.race=0x{:X} note=relocated-to-0xE0-se-0xE8-ae",
                sizeof(RE::Actor::ACTOR_RUNTIME_DATA),
                offsetof(RE::Actor::ACTOR_RUNTIME_DATA, currentProcess),
                offsetof(RE::Actor::ACTOR_RUNTIME_DATA, currentCombatTarget),
                offsetof(RE::Actor::ACTOR_RUNTIME_DATA, race));
            SKSE::log::info("LayoutValidator: LAYOUT class=Character sizeof=0x{:X} note=se-view",
                sizeof(RE::Character));
            SKSE::log::info("LayoutValidator: LAYOUT class=BaseExtraList sizeof=0x{:X} off.data=0x{:X} off.presence=0x{:X} note=se-view",
                sizeof(RE::BaseExtraList), offsetof(RE::BaseExtraList, data),
                offsetof(RE::BaseExtraList, presence));
            // ExtraDataList's members (_extraData/_lock) are private
            // (ExtraDataList.h:198), so only sizeof is compilable here.
            SKSE::log::info("LayoutValidator: LAYOUT class=ExtraDataList sizeof=0x{:X} note=se-view members-private",
                sizeof(RE::ExtraDataList));
            SKSE::log::info("LayoutValidator: LAYOUT class=TESObjectCELL sizeof=0x{:X} off.cellFlags=0x{:X} off.cellState=0x{:X} off.extraList=0x{:X} note=se-view",
                sizeof(RE::TESObjectCELL), offsetof(RE::TESObjectCELL, cellFlags),
                offsetof(RE::TESObjectCELL, cellState), offsetof(RE::TESObjectCELL, extraList));

            // Abstract/vtable-only: bhkCharacterState carries no members of
            // its own (hkReferencedObject base + Unk_08 pure virtual,
            // bhkCharacterState.h:7-20); sizeof is the only layout datum.
            SKSE::log::info("LayoutValidator: LAYOUT class=bhkCharacterState sizeof=0x{:X} note=abstract-vtable-only",
                sizeof(RE::bhkCharacterState));
        }

        // -----------------------------------------------------------------
        // Phase 2a: Address Library resolution check. Resolving these
        // REL::VariantIDs against the live module is itself a layout-relevant
        // fact: it proves the deployed Address Library .bin matches this game
        // build, so every offset the toolkit trusts is anchored to real code.
        // -----------------------------------------------------------------

        void LogResolvedAddresses()
        {
            const auto base = REL::Module::get().base();
            SKSE::log::info("LayoutValidator: ADDR module.base=0x{:X}", base);

            const REL::Relocation<std::uintptr_t> tesFormVtbl{ RE::VTABLE_TESForm[0] };
            SKSE::log::info("LayoutValidator: ADDR vtable=TESForm[0] id=231469/187895 resolved=0x{:X} rva=0x{:X}",
                tesFormVtbl.address(), tesFormVtbl.address() - base);

            const REL::Relocation<std::uintptr_t> actorVtbl{ RE::VTABLE_Actor[0] };
            SKSE::log::info("LayoutValidator: ADDR vtable=Actor[0] id=260538/207511 resolved=0x{:X} rva=0x{:X}",
                actorVtbl.address(), actorVtbl.address() - base);

            for (std::size_t i = 0; i < RE::VTABLE_TESObjectREFR.size(); ++i) {
                const REL::Relocation<std::uintptr_t> refrVtbl{ RE::VTABLE_TESObjectREFR[i] };
                SKSE::log::info("LayoutValidator: ADDR vtable=TESObjectREFR[{}] resolved=0x{:X} rva=0x{:X}",
                    i, refrVtbl.address(), refrVtbl.address() - base);
            }

            const REL::Relocation<std::uintptr_t> rtti{ RE::RTTI_TESForm };
            SKSE::log::info("LayoutValidator: ADDR rtti=TESForm id=513848/392216 resolved=0x{:X} rva=0x{:X}",
                rtti.address(), rtti.address() - base);

            // TODO(live-verify): read the RTTI type_descriptor's decorated
            // `name` at the resolved address and string-compare against
            // ".?AVTESForm@@" -- proves the Address Library ID actually
            // points at TESForm's descriptor and not a neighbouring one.
        }

        // -----------------------------------------------------------------
        // Phase 2b: live-instance field sanity. Reads fields twice -- once
        // through the typed accessor (compiled layout + RelocateMember
        // plumbing) and once as raw bytes at the compiled offsetof -- and
        // flags any disagreement. Only valid for UNGUARDED-layout classes
        // (TESForm here); runtime-divergent classes would compare an SE-view
        // offset against AE memory and must go through the accessors instead.
        // -----------------------------------------------------------------

        void CheckLiveForm(const RE::TESForm* a_form, const char* a_what)
        {
            if (!a_form) {
                SKSE::log::warn("LayoutValidator: LIVE {} instance=nullptr (skipped)", a_what);
                return;
            }

            const auto* raw = reinterpret_cast<const std::uint8_t*>(a_form);
            const auto  rawFormID = *reinterpret_cast<const RE::FormID*>(raw + offsetof(RE::TESForm, formID));
            // formType is stored as a single byte (stl::enumeration<FormType,
            // std::uint8_t>, TESForm.h:356); FormType itself is 4 bytes wide
            // (plain enum class, FormTypes.h:138), so read one raw byte and
            // widen, not the other way around.
            const auto  rawFormType = static_cast<RE::FormType>(*(raw + offsetof(RE::TESForm, formType)));

            const bool formIDOk = rawFormID == a_form->GetFormID();
            const bool formTypeOk = rawFormType == a_form->GetFormType();

            SKSE::log::info(
                "LayoutValidator: LIVE {} formID={:08X}(raw={:08X},{}) formType=0x{:02X}(raw=0x{:02X},{})",
                a_what, a_form->GetFormID(), rawFormID, formIDOk ? "OK" : "MISMATCH",
                static_cast<std::uint8_t>(a_form->GetFormType()), static_cast<std::uint8_t>(rawFormType),
                formTypeOk ? "OK" : "MISMATCH");
        }

        void RunLiveChecks()
        {
            LogResolvedAddresses();

            // formID 0x00000007 is the player base TESNPC ("Player"); the
            // form map is fully populated by kDataLoaded. Expect
            // FormType::NPC (0x2B, FormTypes.h:183).
            const auto* playerBase = RE::TESForm::LookupByID(0x00000007);
            CheckLiveForm(playerBase, "TESForm(0x07)");
            if (playerBase && playerBase->GetFormType() != RE::FormType::NPC) {
                SKSE::log::warn("LayoutValidator: LIVE TESForm(0x07) formType=0x{:02X}, expected NPC (0x2B)",
                    static_cast<std::uint8_t>(playerBase->GetFormType()));
            }

            // TODO(live-verify): the remaining live checks, roughly in
            // order of value:
            //   - RE::PlayerCharacter::GetSingleton(): nullptr at
            //     kDataLoaded (no game started yet) -- needs kNewGame /
            //     kPostLoadGame timing, then check formID==0x14 and
            //     formType==FormType::ActorCharacter (0x3E).
            //   - Walk RE::TES::GetSingleton() to a loaded TESObjectCELL
            //     and sanity-check its ExtraDataList at the compiled
            //     offset -- the only in-process way to get ground truth on
            //     ExtraDataList, the hotspot class type-importer's baseline
            //     still marks EMPTY.
            //   - Read a live high-process Actor's ACTOR_RUNTIME_DATA via
            //     GetActorRuntimeData() and sanity-check currentProcess /
            //     race pointer plausibility (valid pointer, race formType
            //     == FormType::Race) -- validates the RelocateMember path
            //     on AE, which compile-time offsets cannot cover.
            //   - Compare a live instance's vtable pointer against the
            //     RE::VTABLE_* address resolved above (identity check that
            //     the object really is the class the headers claim).
        }

        void OnMessage(SKSE::MessagingInterface::Message* a_message)
        {
            if (a_message->type == SKSE::MessagingInterface::kDataLoaded) {
                RunLiveChecks();
            }
        }
    }

    void Install()
    {
        LogCompileTimeLayout();

        if (!SKSE::GetMessagingInterface()->RegisterListener(OnMessage)) {
            SKSE::log::error("LayoutValidator: failed to register messaging listener.");
            return;
        }

        SKSE::log::info("LayoutValidator: layout report logged; live-instance check registered (kDataLoaded).");
    }
}

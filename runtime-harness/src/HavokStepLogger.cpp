#include "HavokStepLogger.h"

#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

#include <array>
#include <unordered_map>

namespace HavokStepLogger
{
    namespace
    {
        using UpdateFn = decltype(&RE::bhkCharacterState::Update);

        REL::Relocation<UpdateFn> _OnGroundUpdate;
        REL::Relocation<UpdateFn> _JumpingUpdate;
        REL::Relocation<UpdateFn> _InAirUpdate;
        REL::Relocation<UpdateFn> _ClimbingUpdate;
        REL::Relocation<UpdateFn> _FlyingUpdate;
        REL::Relocation<UpdateFn> _SwimmingUpdate;

        // Instance address of the owning hkpCharacterContext -> last state
        // logged, so the log only records transitions, not one line per
        // physics step. See HavokStepLogger.h for why this is keyed by
        // context instance rather than by actor.
        std::unordered_map<const void*, RE::hkpCharacterStateType> g_lastState;

        const char* StateName(RE::hkpCharacterStateType a_state)
        {
            switch (a_state) {
                case RE::hkpCharacterStateTypes::kOnGround:
                    return "OnGround";
                case RE::hkpCharacterStateTypes::kJumping:
                    return "Jumping";
                case RE::hkpCharacterStateTypes::kInAir:
                    return "InAir";
                case RE::hkpCharacterStateTypes::kClimbing:
                    return "Climbing";
                case RE::hkpCharacterStateTypes::kFlying:
                    return "Flying";
                case RE::hkpCharacterStateTypes::kSwimming:
                    return "Swimming";
                default:
                    return "Unknown";
            }
        }

        void LogIfChanged(RE::hkpCharacterContext& a_context, const RE::hkpCharacterOutput& a_output)
        {
            const auto state = a_context.currentState;
            const void* key = std::addressof(a_context);

            auto [it, inserted] = g_lastState.try_emplace(key, state);
            if (!inserted && it->second == state) {
                return;
            }
            it->second = state;

            SKSE::log::info("hkpCharacterContext {} -> state {} (velocity {:.2f})",
                key, StateName(state), a_output.velocity.Length3());
        }

        void OnGroundUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _OnGroundUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        void JumpingUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _JumpingUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        void InAirUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _InAirUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        void ClimbingUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _ClimbingUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        void FlyingUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _FlyingUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        void SwimmingUpdate_Hook(RE::bhkCharacterState* a_this, RE::hkpCharacterContext& a_context,
            const RE::hkpCharacterInput& a_input, RE::hkpCharacterOutput& a_output)
        {
            _SwimmingUpdate(a_this, a_context, a_input, a_output);
            LogIfChanged(a_context, a_output);
        }

        constexpr std::size_t kUpdateVfuncIndex = 6;
    }

    void Install()
    {
        REL::Relocation<std::uintptr_t> onGround{ RE::VTABLE_bhkCharacterStateOnGround[0] };
        _OnGroundUpdate = onGround.write_vfunc(kUpdateVfuncIndex, OnGroundUpdate_Hook);

        REL::Relocation<std::uintptr_t> jumping{ RE::VTABLE_bhkCharacterStateJumping[0] };
        _JumpingUpdate = jumping.write_vfunc(kUpdateVfuncIndex, JumpingUpdate_Hook);

        REL::Relocation<std::uintptr_t> inAir{ RE::VTABLE_bhkCharacterStateInAir[0] };
        _InAirUpdate = inAir.write_vfunc(kUpdateVfuncIndex, InAirUpdate_Hook);

        REL::Relocation<std::uintptr_t> climbing{ RE::VTABLE_bhkCharacterStateClimbing[0] };
        _ClimbingUpdate = climbing.write_vfunc(kUpdateVfuncIndex, ClimbingUpdate_Hook);

        REL::Relocation<std::uintptr_t> flying{ RE::VTABLE_bhkCharacterStateFlying[0] };
        _FlyingUpdate = flying.write_vfunc(kUpdateVfuncIndex, FlyingUpdate_Hook);

        REL::Relocation<std::uintptr_t> swimming{ RE::VTABLE_bhkCharacterStateSwimming[0] };
        _SwimmingUpdate = swimming.write_vfunc(kUpdateVfuncIndex, SwimmingUpdate_Hook);

        SKSE::log::info("HavokStepLogger: bhkCharacterState::Update hook installed (6 concrete state vtables).");
    }
}

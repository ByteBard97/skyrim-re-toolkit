// Minimal forced-include header for layout verification only.
//
// NOT a replacement for CommonLibSSE-NG's real SKSE/Impl/PCH.h. That PCH
// pulls in spdlog (which drags in real <windows.h>, which then trips
// REX/W32/BASE.h's own "don't include real Windows headers" guard) and a
// generated per-runtime RTTI/offset table we don't have without a full
// build. Since the type-importer only needs *record layouts* (sizes and
// field offsets), not a linked, runnable binary, this stub supplies just
// enough for clang to type-check class bodies far enough to lay them out:
//
//   - the STL headers CommonLibSSE-NG's own headers assume are already
//     globally included (they don't `#include <cstdint>` themselves, they
//     rely on the project-wide PCH)
//   - a stand-in for REL::Relocation<T>/RELOCATION_ID that matches the
//     REAL verified layout (single pointer/uintptr_t-sized member — see
//     DESIGN.md's template flattening table) instead of pulling in the
//     real REL/Relocation.h, which transitively needs REX::W32 module
//     handling we don't want here
//   - generated_symbols.h for the RTTI_*/VTABLE_* constants (see that
//     file's own header comment for why zero-stubbing them is safe)
//
// Usage: `clang-cl /FI"stubs/layout_pch.h" ...` when compiling a
// single RE/ header for -fdump-record-layouts. See scripts/ for the
// harness that does this automatically.

#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <bitset>
#include <cassert>
#include <cmath>
#include <concepts>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <cwchar>
#include <cwctype>
#include <exception>
#include <filesystem>
#include <functional>
#include <intrin.h>
#include <iomanip>
#include <ios>
#include <istream>
#include <iterator>
#include <limits>
#include <locale>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <numeric>
#include <optional>
#include <set>
#include <source_location>
#include <span>
#include <sstream>
#include <stack>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>
#include <tuple>
#include <type_traits>
#include <typeinfo>
#include <utility>
#include <variant>
#include <vector>

// Deliberately NOT included here (see header comment above for why):
//   <execution>, <format>, <fstream>, <random>, <regex> — present in the
//   real PCH but not needed by the RE/ headers exercised so far; add if a
//   new class chain needs them.

// std::to_underlying is C++23; CommonLibSSE-NG targets C++20 here plus this
// one C++23 convenience used in BGSDefaultObjectManager.h (outside our
// TESObjectREFR target, pulled in transitively).
namespace std
{
    template <class Enum>
    constexpr underlying_type_t<Enum> to_underlying(Enum e) noexcept
    {
        return static_cast<underlying_type_t<Enum>>(e);
    }
}

// --- SKSE::stl stand-in --------------------------------------------------
// The real `stl` namespace (SKSE::stl, aliased to `stl` project-wide by the
// real PCH) is used only inside a handful of function BODIES in the RE/
// headers we exercise (TES_HEAP_REDEFINE_NEW's report_and_fail call,
// atomic_ref locals) — never as a data member, so it can't affect any
// record layout. This stub just needs to type-check those call sites.
using namespace std::literals;

namespace stl
{
    inline void report_and_fail(std::string_view) { std::abort(); }

    // Real type is a non-owning null-terminated wide string view
    // (SKSE's stl::zwstring); std::wstring_view is layout/usage-compatible
    // enough for the two function-signature uses in our chain (never a
    // data member).
    using zwstring = std::wstring_view;
    using zstring = std::string_view;

    template <class T>
    class atomic_ref : public std::atomic_ref<T>
    {
        using super = std::atomic_ref<T>;
    public:
        using super::super;
        using super::operator=;
    };

    template <class T>
    atomic_ref(volatile T&) -> atomic_ref<T>;

    // Local-variable-only RAII helper (never a data member) — simplified
    // from the real definition at SKSE/Impl/PCH.h:156.
    template <class EF>
    class scope_exit
    {
    public:
        template <class Fn>
        explicit scope_exit(Fn&& a_fn) : _fn(std::forward<Fn>(a_fn)) {}
        ~scope_exit() noexcept { if (_fn.has_value()) (*_fn)(); }
    private:
        std::optional<EF> _fn;
    };
    template <class Fn>
    scope_exit(Fn) -> scope_exit<Fn>;

    // Real layout, verified against source: single member of the
    // underlying integer type (SKSE::stl::enumeration, SKSE/Impl/PCH.h:
    // 221-269 — see DESIGN.md's template flattening table for the
    // citation). This is the row we get to check directly against a real
    // static_assert: TESForm.h:355-356 uses stl::enumeration as an actual
    // data member, and TESForm.h:360 asserts sizeof(TESForm) == 0x20.
    template <class Enum, class Underlying = std::underlying_type_t<Enum>>
    class enumeration
    {
    public:
        using enum_type = Enum;
        using underlying_type = Underlying;

        constexpr enumeration() noexcept = default;

        template <class... Args>
        constexpr enumeration(Args... a_values) noexcept
            : _impl((static_cast<underlying_type>(a_values) | ...)) {}

        [[nodiscard]] constexpr explicit operator bool() const noexcept { return _impl != static_cast<underlying_type>(0); }
        [[nodiscard]] constexpr enum_type get() const noexcept { return static_cast<enum_type>(_impl); }
        [[nodiscard]] constexpr enum_type operator*() const noexcept { return get(); }
        [[nodiscard]] constexpr underlying_type underlying() const noexcept { return _impl; }

        template <class... Args>
        constexpr enumeration& set(Args... a_args) noexcept
        {
            _impl |= (static_cast<underlying_type>(a_args) | ...);
            return *this;
        }

        template <class... Args>
        [[nodiscard]] constexpr bool any(Args... a_args) const noexcept
        {
            return (_impl & (static_cast<underlying_type>(a_args) | ...)) != static_cast<underlying_type>(0);
        }

        template <class... Args>
        [[nodiscard]] constexpr bool all(Args... a_args) const noexcept
        {
            return (_impl & (static_cast<underlying_type>(a_args) | ...)) == (static_cast<underlying_type>(a_args) | ...);
        }

    private:
        underlying_type _impl{ 0 };
    };

    // Not found anywhere in this codebase's real source (grepped, no
    // definition exists) — only used in BSTList.h, which is outside our
    // current TESForm-chain target. Minimal non-owning-pointer guess so
    // unrelated BSTList errors don't cascade into headers we DO care
    // about; do not trust this shape without checking real usage first.
    template <class T>
    class observer
    {
    public:
        constexpr observer() noexcept = default;
        constexpr observer(T a_ptr) noexcept : _ptr(a_ptr) {}
    private:
        T _ptr{};
    };
}

#include "generated_symbols.h"

// Real header (not build-generated as first assumed) — just needed the
// include path, and our stl::zwstring/using-literals above already in
// scope for it. REL::Version itself only needs REL/Common.h, included
// next.
#include "SKSE/Version.h"

// Self-contained (pure macros, no further includes) — defines
// SKYRIM_REL_VR_VIRTUAL and friends based on ENABLE_SKYRIM_AE/SE/VR.
// Real header, not a stub: safe to use as-is.
#include "REL/Common.h"

// --- REL::Relocation<T> / RELOCATION_ID stand-in -------------------------
// NOT the real header: REL/Relocation.h transitively pulls in REL/Module.h
// (runtime detection, PE segment tables, the SKYRIM_REL macro) and
// stl::zwstring — real functionality this layout-only pass doesn't need
// and that isn't worth chasing (that's standing up most of the real
// runtime-detection machinery for zero layout benefit).
//
// This stand-in matches the REAL verified layout from REL/Relocation.h
// (single `_impl` member of `value_type`, pointer/uintptr_t-sized — see
// DESIGN.md's template flattening table for the citation) and uses
// std::invoke so operator() correctly deduces the return type for both
// free-function and member-function-pointer T — which several
// MemoryManager.h/BSStringPool.h call sites need to even type-check
// (a `void`-returning method's `return func(...)` requires the call
// expression to actually be void, not just "some ignorable value").
namespace REL
{
    template <class T = std::uintptr_t>
    class Relocation
    {
    public:
        using value_type = std::conditional_t<
            std::is_member_pointer_v<T> || std::is_function_v<std::remove_pointer_t<T>>,
            std::decay_t<T>,
            T>;

        constexpr Relocation() noexcept = default;
        explicit constexpr Relocation(std::uintptr_t) noexcept {}

        template <class... CallArgs>
        decltype(auto) operator()(CallArgs&&... a_args) const
        {
            return std::invoke(_impl, std::forward<CallArgs>(a_args)...);
        }

        decltype(auto) operator*() const { return *_impl; }
        value_type operator->() const { return _impl; }

    private:
        value_type _impl{};
    };

    // RelocateMember<T>(this, se_offset, ae_offset) — real semantics pick
    // one of two byte offsets at runtime based on detected game version
    // (see DESIGN.md's TESObjectREFR field-map section for the mechanism —
    // this is exactly the pattern behind GetReferenceRuntimeData). Layout-
    // wise this returns a reference into existing object memory, so a stub
    // that just uses the AE offset (second arg) is fine for our AE-only
    // pass: it never allocates new storage, so it can't add spurious bytes
    // to any enclosing class.
    template <class T>
    T& RelocateMember(void* a_base, std::size_t /*a_seOffset*/, std::size_t a_aeOffset) noexcept
    {
        return *reinterpret_cast<T*>(static_cast<std::byte*>(a_base) + a_aeOffset);
    }

    template <class T>
    const T& RelocateMember(const void* a_base, std::size_t /*a_seOffset*/, std::size_t a_aeOffset) noexcept
    {
        return *reinterpret_cast<const T*>(static_cast<const std::byte*>(a_base) + a_aeOffset);
    }

    // Real name/signature differs (picks se/ae offset by comparing a
    // runtime-detected version against the given threshold); for a
    // single-runtime AE-only pass, always resolving to the ae offset is
    // exactly correct, not just a simplification.
    template <class T, class Version>
    T& RelocateMemberIfNewer(Version&&, void* a_base, std::size_t a_seOffset, std::size_t a_aeOffset) noexcept
    {
        return RelocateMember<T>(a_base, a_seOffset, a_aeOffset);
    }

    template <class T, class Version>
    const T& RelocateMemberIfNewer(Version&&, const void* a_base, std::size_t a_seOffset, std::size_t a_aeOffset) noexcept
    {
        return RelocateMember<T>(a_base, a_seOffset, a_aeOffset);
    }
}
#define RELOCATION_ID(a_se, a_ae) (std::uintptr_t{0})

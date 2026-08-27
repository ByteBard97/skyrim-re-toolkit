// RuntimeHarness -- minimal SKSE plugin skeleton.
//
// Proves the Windows/MSVC/CommonLibSSE-NG toolchain end to end: loads,
// sets up file logging, reports the running game version, and confirms
// the messaging interface works by logging kDataLoaded. The real
// inspectors (AIProcessInspector etc. -- see README.md) build on this.
//
// Built against the repo's VENDORED CommonLibSSE-NG (v3.7.0) -- the exact
// headers the .gdt type archives are generated from. All mechanisms below
// are verified against that tree, not external docs:
//
//   - SKSEPluginInfo(...)  (SKSE/Interfaces.h:685): expands to an exported
//     `SKSEPlugin_Version` -- a constinit SKSE::PluginDeclaration (0x350
//     bytes, static_assert Interfaces.h:682), which is the
//     SKSEPluginVersionData block AE-era SKSE loads plugins by -- PLUS an
//     exported SKSEPlugin_Query for pre-AE SKSE compatibility.
//   - PluginDeclarationInfo designated fields (Interfaces.h:575-623):
//     Version, Name, Author, SupportEmail, StructCompatibility,
//     RuntimeCompatibility, MinimumSKSEVersion.
//   - RuntimeCompatibility(VersionIndependence) constructor
//     (Interfaces.h, in-struct); VersionIndependence::AddressLibrary
//     (Interfaces.h:439) -- correct for CommonLibSSE-NG, which resolves
//     addresses through Address Library on all runtimes.
//   - SKSEPluginLoad macro (Interfaces.h:695), SKSE::Init (SKSE/API.h:15),
//     SKSE::log::log_directory() (SKSE/Logger.h:38),
//     SKSE::stl::report_and_fail (SKSE/Impl/PCH.h:660).

#include "AIProcessInspector.h"
#include "DevBenchIntegration.h"
#include "HavokStepLogger.h"
#include "LayoutValidator.h"
#include "SavegameTracer.h"

#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

#include <spdlog/sinks/basic_file_sink.h>

using namespace std::literals;

SKSEPluginInfo(
    .Version = { 0, 1, 0, 0 },
    .Name = "RuntimeHarness"sv,
    .Author = "skyrim-re-toolkit"sv,
    .StructCompatibility = SKSE::StructCompatibility::Independent,
    .RuntimeCompatibility = SKSE::VersionIndependence::AddressLibrary)

namespace {

void SetupLog()
{
    auto path = SKSE::log::log_directory();
    if (!path) {
        SKSE::stl::report_and_fail("Cannot locate the SKSE log directory.");
    }
    *path /= "RuntimeHarness.log"sv;

    auto sink = std::make_shared<spdlog::sinks::basic_file_sink_mt>(path->string(), true);
    auto logger = std::make_shared<spdlog::logger>("global", std::move(sink));
    logger->set_level(spdlog::level::info);
    logger->flush_on(spdlog::level::info);
    spdlog::set_default_logger(std::move(logger));
    spdlog::set_pattern("[%H:%M:%S.%e] [%l] %v");
}

void OnMessage(SKSE::MessagingInterface::Message* message)
{
    switch (message->type) {
        case SKSE::MessagingInterface::kPostLoad:
            // devbench's own contract (DevBenchAPI.h): its cross-plugin
            // interface is only fetchable after SKSE has finished
            // dispatching kPostLoad to every plugin (so devbench itself,
            // if present, has already registered its message listener).
            DevBenchIntegration::Install();
            break;
        case SKSE::MessagingInterface::kDataLoaded:
            SKSE::log::info("kDataLoaded received -- game data is fully loaded.");
            LayoutValidator::OnDataLoaded();
            break;
        case SKSE::MessagingInterface::kNewGame:
            SKSE::log::info("kNewGame received -- a new game started.");
            LayoutValidator::OnGameSessionReady();
            break;
        case SKSE::MessagingInterface::kPreLoadGame:
            SKSE::log::info("kPreLoadGame received -- a save is about to load.");
            break;
        case SKSE::MessagingInterface::kPostLoadGame:
            SKSE::log::info("kPostLoadGame received -- a save finished loading.");
            LayoutValidator::OnGameSessionReady();
            break;
        default:
            break;
    }
}

}  // namespace

SKSEPluginLoad(const SKSE::LoadInterface* skse)
{
    SKSE::Init(skse);
    SetupLog();

    const auto* plugin = SKSE::PluginDeclaration::GetSingleton();
    SKSE::log::info("{} v{} loading (runtime: Skyrim {})",
        plugin->GetName(), plugin->GetVersion().string(),
        REL::Module::get().version().string());

    if (!SKSE::GetMessagingInterface()->RegisterListener(OnMessage)) {
        SKSE::log::error("Failed to register messaging listener.");
        return false;
    }

    AIProcessInspector::Install();
    HavokStepLogger::Install();
    SavegameTracer::Install();
    LayoutValidator::Install();

    SKSE::log::info("Loaded.");
    return true;
}

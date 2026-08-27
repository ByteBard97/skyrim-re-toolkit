#include "DevBenchIntegration.h"

#include "AIProcessInspector.h"

#include "../vendor/devbench/DevBenchAPI.h"

#include <SKSE/SKSE.h>

#include <format>
#include <string>

namespace DevBenchIntegration
{
    namespace
    {
        // Hand-rolled JSON, not a library: runtime-harness has no JSON
        // dependency today (CommonLibSSE-NG's own vcpkg.json pulls in only
        // rapidcsv + spdlog, see runtime-harness/vcpkg.json's own comment),
        // and this payload is a flat list of unsigned integers with no
        // string content to escape -- pulling in nlohmann-json or similar
        // for that would be more dependency than the task needs.
        std::string SerializeAiPackageResult(const std::unordered_map<RE::FormID, RE::FormID>& a_snapshot)
        {
            std::string json = "{\"count\":";
            json += std::to_string(a_snapshot.size());
            json += ",\"actors\":[";

            bool first = true;
            for (const auto& [actorFormID, packageFormID] : a_snapshot) {
                if (!first) {
                    json += ',';
                }
                first = false;
                json += std::format(R"({{"actor":"0x{:08X}","package":"0x{:08X}"}})", actorFormID, packageFormID);
            }

            json += "]}";
            return json;
        }

        // ToolFn contract (DevBenchAPI.h): plain C function, runs on
        // devbench's own listener thread, args in as JSON, result out via
        // a_write(a_sink, json) called exactly once. a_argsJson/a_ctx are
        // unused -- this tool takes no arguments and needs no per-call
        // context (AIProcessInspector's snapshot accessor is itself
        // thread-safe, see AIProcessInspector.h).
        void AiPackageTool_Handler(void* /*a_ctx*/, const char* /*a_argsJson*/, void* a_sink,
            DevBenchAPI::WriteFn a_write)
        {
            const auto snapshot = AIProcessInspector::GetLastPackageSnapshot();
            const auto json = SerializeAiPackageResult(snapshot);
            a_write(a_sink, json.c_str());
        }
    }

    void Install()
    {
        auto* devBench = DevBenchAPI::GetDevBenchInterface001();
        if (!devBench) {
            SKSE::log::info("DevBenchIntegration: devbench not present, skipping tool registration.");
            return;
        }

        constexpr const char* kDescriptor =
            R"({"description":"Live AIProcessInspector state: every NPC actor AIProcessInspector has seen change package, with its most recently observed package. Read-only, no arguments.","inputSchema":{"type":"object","properties":{}},"readOnly":true})";

        const bool registered = devBench->RegisterTool(
            "runtimeharness.ai_package", kDescriptor, AiPackageTool_Handler, nullptr);

        SKSE::log::info(
            "DevBenchIntegration: devbench found (build {}), registered runtimeharness.ai_package ({}).",
            devBench->GetBuildNumber(), registered ? "new" : "replaced existing");
    }
}

#pragma once

// DevBenchIntegration -- registers RuntimeHarness's inspector data as
// live tools on alandtse/devbench (github.com/alandtse/devbench), a
// third-party SKSE plugin that hosts an MCP+REST server for Skyrim mod
// development (see runtime-harness/docs/MCP_SERVER_DESIGN.md v0.3 for
// the design decision). Uses devbench's MIT-licensed cross-plugin C-ABI
// (vendor/devbench/DevBenchAPI.h/.cpp) rather than devbench's own
// GPL-3.0 plugin code, so this integration carries no GPL obligation.
//
// devbench is optional: if it isn't loaded, DevBenchAPI::GetDevBenchInterface001()
// returns nullptr (per its own header contract) and Install() below no-ops
// cleanly -- RuntimeHarness's own inspectors are unaffected either way.

namespace DevBenchIntegration
{
    // Call from main.cpp's OnMessage on kPostLoad (devbench's own contract:
    // its interface is only fetchable after SKSE has finished dispatching
    // kPostLoad to every plugin). No-ops if devbench isn't present.
    void Install();
}

# RuntimeHarness -- minimal SKSE plugin skeleton (see README.md).
#
# Builds against the CommonLibSSE-NG tree ALREADY VENDORED in this repo
# (type-importer/vendor/CommonLibSSE-NG, v3.7.0) rather than a vcpkg
# registry port. Two reasons:
#   1. The Color-Glass vcpkg registry that hosted the commonlibsse-ng
#      port is abandoned (last commit 2023-05); its port no longer
#      configures against a current vcpkg tree (first Windows build
#      attempt failed on FAST_CPP_CSV_PARSER_INCLUDE_DIRS-NOTFOUND).
#   2. Consistency is a feature: the plugin is compiled against the EXACT
#      headers type-importer's .gdt archives are generated from, so the
#      runtime harness and the type archives can never disagree about a
#      struct layout.
# vcpkg (classic C:\vcpkg + toolchain file) still supplies the vendored
# tree's own dependencies -- see vcpkg.json (rapidcsv, spdlog).
cmake_minimum_required(VERSION 3.21)

project(
    RuntimeHarness
    VERSION 0.1.0
    DESCRIPTION "Live Creation Engine state inspection harness (skyrim-re-toolkit)."
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)

# The vendored CommonLibSSE-NG submodule. Out-of-tree relative to this
# directory, hence the explicit binary-dir second argument. Overridable
# for unusual checkouts.
set(RUNTIME_HARNESS_COMMONLIB_PATH
    "${CMAKE_CURRENT_SOURCE_DIR}/../type-importer/vendor/CommonLibSSE-NG"
    CACHE PATH "Path to the CommonLibSSE-NG source tree to build against.")

if (NOT EXISTS "${RUNTIME_HARNESS_COMMONLIB_PATH}/CMakeLists.txt")
    message(FATAL_ERROR
        "CommonLibSSE-NG not found at ${RUNTIME_HARNESS_COMMONLIB_PATH}. "
        "Build from a full clone of skyrim-re-toolkit with submodules "
        "(git clone --recursive), or set RUNTIME_HARNESS_COMMONLIB_PATH.")
endif()

# The vendored tree's options (type-importer/vendor/CommonLibSSE-NG/
# CMakeLists.txt:3-7): keep all three runtimes ON (NG's dynamic-runtime
# support is the point -- one DLL for SE/AE/VR), tests OFF.
set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${RUNTIME_HARNESS_COMMONLIB_PATH}" commonlibsse-ng)

set(sources
    src/main.cpp)

# Without the registry port's add_commonlibsse_plugin() helper, declare
# the DLL directly. The SKSE plugin version data AE requires is exported
# from source instead: see src/main.cpp's SKSEPluginInfo block and the
# citations there (SKSE/Interfaces.h in the vendored tree).
add_library(${PROJECT_NAME} SHARED ${sources})
target_link_libraries(${PROJECT_NAME} PRIVATE CommonLibSSE::CommonLibSSE)

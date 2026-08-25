# Configure + build RuntimeHarness (Release) on the Windows build machine.
#
# Prerequisites (see README.md):
#   - Visual Studio 2022 Build Tools with the "Desktop development with C++"
#     workload (v143 toolset)
#   - CMake 3.21+
#   - vcpkg at C:\vcpkg (override with -VcpkgRoot)
#   - A FULL clone of skyrim-re-toolkit with submodules: the build does
#     add_subdirectory(../type-importer/vendor/CommonLibSSE-NG), so this
#     script must run from runtime-harness/ inside the repo checkout, not
#     from a copied-out folder.
#
# Usage (from this directory):
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
param(
    [string]$VcpkgRoot = "C:\vcpkg",
    [string]$Config = "Release"
)

$ErrorActionPreference = "Stop"
$toolchain = Join-Path $VcpkgRoot "scripts\buildsystems\vcpkg.cmake"
if (-not (Test-Path $toolchain)) {
    throw "vcpkg toolchain not found at $toolchain -- pass -VcpkgRoot or install vcpkg."
}

$src = $PSScriptRoot
$build = Join-Path $src "build"

cmake -S $src -B $build -G "Visual Studio 17 2022" -A x64 `
    -DCMAKE_TOOLCHAIN_FILE="$toolchain" `
    -DVCPKG_TARGET_TRIPLET=x64-windows-static-md
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed." }

cmake --build $build --config $Config --parallel
if ($LASTEXITCODE -ne 0) { throw "Build failed." }

$dll = Get-ChildItem -Recurse (Join-Path $build $Config) -Filter "RuntimeHarness.dll" |
    Select-Object -First 1
if ($dll) {
    Write-Host "Built: $($dll.FullName)"
} else {
    Write-Host "Build finished, but RuntimeHarness.dll not found where expected -- check $build."
}

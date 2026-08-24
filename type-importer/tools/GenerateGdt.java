import playday3008.gcpp.processing.*;
import ghidra.program.model.data.*;
import ghidra.framework.Application;
import ghidra.framework.ApplicationConfiguration;
import ghidra.GhidraApplicationLayout;

import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Standalone command-line driver for the patched GhidraClangPoweredParse
 * SourceParser, producing a real Ghidra .gdt type archive from CommonLibSSE-NG
 * headers -- without needing to open Ghidra's GUI or run a headless analyzer
 * session.
 * <p>
 * This is the tool version of the ad hoc test harnesses used to develop and
 * verify patches/0001 through 0005 (see type-importer/DESIGN.md and
 * type-importer/patches/*.md for the full investigation). It requires:
 * <ul>
 *   <li>JDK 21+ (Panama FFI)</li>
 *   <li>Ghidra 12+ on the classpath (for ghidra.program.model.data.* etc.)</li>
 *   <li>The GhidraClangPoweredParse submodule, patched with all of
 *       type-importer/patches/000{1,2,3,4,5}-*.patch, compiled classes on
 *       the classpath</li>
 *   <li>A libclang.so that reports as Clang 19+ to satisfy MSVC STL's own
 *       version check in the vendored Windows SDK/CRT headers -- the system
 *       libclang-14 that ships on many Linux distros is NOT sufficient (see
 *       DESIGN.md's toolchain note). The extension's own bundled libclang
 *       cannot be located without a running Ghidra Application module-
 *       resource system, so on Linux this falls back to searching for a
 *       system-installed libclang.so by name -- make sure a real one (19+)
 *       is first on that search path, e.g. via LD_LIBRARY_PATH.</li>
 *   <li>-Xint on the JVM (Panama FFI upcalls crash under JIT compilation --
 *       a documented limitation of GhidraClangPoweredParse itself, not
 *       something this tool can work around).</li>
 * </ul>
 * See scripts/generate_gdt.sh for a wrapper that sets all of this up.
 *
 * Usage:
 *   java -Xint --enable-preview --enable-native-access=ALL-UNNAMED \
 *     -cp &lt;classpath&gt; GenerateGdt \
 *     --commonlib &lt;path-to-CommonLibSSE-NG/include&gt; \
 *     --stubs &lt;path-to-type-importer/stubs&gt; \
 *     --winsdk-crt &lt;path-to-xwin-splat&gt;/crt/include \
 *     --winsdk-ucrt &lt;path-to-xwin-splat&gt;/sdk/include/ucrt \
 *     --output &lt;path&gt;/CommonLibSSE_AE.gdt \
 *     --runtime ENABLE_SKYRIM_AE=1 \
 *     RE/T/TESForm.h RE/T/TESObject.h RE/T/TESBoundObject.h RE/T/TESObjectREFR.h
 */
public class GenerateGdt {

    public static void main(String[] args) throws Exception {
        String commonlib = null, stubs = null, winsdkCrt = null, winsdkUcrt = null;
        String output = null, runtimeDefine = "ENABLE_SKYRIM_AE=1";
        List<String> headers = new ArrayList<>();

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--commonlib" -> commonlib = args[++i];
                case "--stubs" -> stubs = args[++i];
                case "--winsdk-crt" -> winsdkCrt = args[++i];
                case "--winsdk-ucrt" -> winsdkUcrt = args[++i];
                case "--output" -> output = args[++i];
                case "--runtime" -> runtimeDefine = args[++i];
                default -> headers.add(args[i]);
            }
        }

        if (commonlib == null || stubs == null || winsdkCrt == null
            || winsdkUcrt == null || output == null || headers.isEmpty()) {
            System.err.println(
                "Usage: GenerateGdt --commonlib <dir> --stubs <dir> --winsdk-crt <dir> "
                + "--winsdk-ucrt <dir> --output <file.gdt> [--runtime ENABLE_SKYRIM_AE=1] "
                + "<header1.h> [header2.h ...]");
            System.exit(1);
        }

        if (!Application.isInitialized()) {
            Application.initializeApplication(new GhidraApplicationLayout(), new ApplicationConfiguration());
        }

        File src = File.createTempFile("generate_gdt", ".hpp");
        src.deleteOnExit();
        StringBuilder content = new StringBuilder();
        for (String h : headers) {
            content.append("#include \"").append(h).append("\"\n");
        }
        Files.writeString(src.toPath(), content.toString());

        TypePool pool = new TypePool(new DataTypeManager[]{});
        SourceParser parser = new SourceParser();

        String[] runtimeParts = runtimeDefine.split("=", 2);
        String options = String.join("\n",
            "-std=c++20",
            "-include", stubs + "/layout_pch.h",
            "-D_WIN64", "-DWIN32",
            "-D" + runtimeDefine,
            "-ferror-limit=0"
        );

        System.out.println("Parsing " + headers.size() + " header(s) with runtime=" + runtimeDefine + "...");
        List<String> diagnostics = parser.parseFiles(
            pool,
            new String[]{src.getAbsolutePath()},
            new String[]{commonlib, stubs, winsdkCrt, winsdkUcrt},
            options,
            "x86:LE:64:default",
            "windows"
        );

        if (!diagnostics.isEmpty()) {
            System.out.println(diagnostics.size() + " clang error diagnostic(s):");
            for (String d : diagnostics) {
                System.out.println("  " + d);
            }
        } else {
            System.out.println("Zero clang diagnostics.");
        }

        TypePool.ResolutionResult result = pool.resolve();
        List<DataType> dataTypes = result.getDataTypes();
        System.out.println("Resolved " + dataTypes.size() + " data types.");
        if (!result.getUnresolvedDependencies().isEmpty()) {
            System.out.println(result.getUnresolvedDependencies().size()
                + " unresolved dependencies remain (some types may be incomplete).");
        }

        File gdtFile = new File(output);
        if (gdtFile.exists()) {
            System.out.println("Overwriting existing " + gdtFile.getAbsolutePath());
            gdtFile.delete();
        }
        FileDataTypeManager fileDtMgr = FileDataTypeManager.createFileArchive(
            gdtFile, "x86:LE:64:default", "windows");
        int txId = fileDtMgr.startTransaction("Add clang-parsed data types");
        int added = 0, failed = 0;
        for (DataType t : dataTypes) {
            try {
                fileDtMgr.addDataType(t, DataTypeConflictHandler.REPLACE_HANDLER);
                added++;
            } catch (Exception e) {
                failed++;
            }
        }
        fileDtMgr.endTransaction(txId, true);
        fileDtMgr.save();
        fileDtMgr.close();

        System.out.println("Committed " + added + " types (" + failed + " failed) to "
            + gdtFile.getAbsolutePath() + " (" + gdtFile.length() + " bytes)");
    }
}

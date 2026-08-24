import playday3008.gcpp.processing.*;
import ghidra.program.model.data.*;
import ghidra.framework.Application;
import ghidra.framework.ApplicationConfiguration;
import ghidra.GhidraApplicationLayout;

import java.io.File;
import java.io.PrintStream;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
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
 *
 * Coverage-sweep mode (see ../COVERAGE_SWEEP_PLAN.md): pass --report-csv
 * &lt;path&gt; to additionally write a two-column {@code ClassName,SizeInBytes}
 * CSV of every resolved data type, plus a companion
 * {@code &lt;path&gt;.unresolved.txt} listing every dependency name the
 * pipeline could not resolve at all. This is separate from (and does not
 * replace) the .gdt file, which is still always written -- --report-csv
 * only adds the plain-text summary scripts/coverage_report.py consumes.
 */
public class GenerateGdt {

    public static void main(String[] args) throws Exception {
        String commonlib = null, stubs = null, winsdkCrt = null, winsdkUcrt = null;
        String output = null, runtimeDefine = "ENABLE_SKYRIM_AE=1", reportCsv = null;
        List<String> headers = new ArrayList<>();

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--commonlib" -> commonlib = args[++i];
                case "--stubs" -> stubs = args[++i];
                case "--winsdk-crt" -> winsdkCrt = args[++i];
                case "--winsdk-ucrt" -> winsdkUcrt = args[++i];
                case "--output" -> output = args[++i];
                case "--runtime" -> runtimeDefine = args[++i];
                case "--report-csv" -> reportCsv = args[++i];
                default -> headers.add(args[i]);
            }
        }

        if (commonlib == null || stubs == null || winsdkCrt == null
            || winsdkUcrt == null || output == null || headers.isEmpty()) {
            System.err.println(
                "Usage: GenerateGdt --commonlib <dir> --stubs <dir> --winsdk-crt <dir> "
                + "--winsdk-ucrt <dir> --output <file.gdt> [--runtime ENABLE_SKYRIM_AE=1] "
                + "[--report-csv <path>] <header1.h> [header2.h ...]");
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

        System.out.println("Committed " + added + " types (" + failed + " failed) to "
            + gdtFile.getAbsolutePath() + " (" + gdtFile.length() + " bytes)");

        if (reportCsv != null) {
            // Read sizes back from the FileDataTypeManager itself, NOT the
            // pre-commit `dataTypes` list. Ghidra recomputes/finalizes a
            // Structure's length when it's actually added to a real
            // DataTypeManager (component offsets/padding that were already
            // set can still change the reported getLength() before vs.
            // after this step) -- measuring pre-commit was found to
            // silently misreport sizes for a large fraction of otherwise-
            // correctly-parsed classes (e.g. AMMO_DATA measured as 12
            // pre-commit, but the actual committed .gdt has it at the
            // correct 16), which would have falsely inflated the MISMATCH
            // bucket in coverage_report.py. See COVERAGE_SWEEP_PLAN.md.
            List<DataType> committed = new ArrayList<>();
            java.util.Iterator<DataType> it = fileDtMgr.getAllDataTypes();
            while (it.hasNext()) {
                committed.add(it.next());
            }
            writeCoverageReport(reportCsv, committed, result.getUnresolvedDependencies());
        }
        fileDtMgr.close();
    }

    /**
     * Writes {@code path} as a two-column {@code ClassName,SizeInBytes} CSV
     * of every resolved data type (sorted by name), and a companion
     * {@code path + ".unresolved.txt"} listing every dependency name the
     * pipeline never resolved at all. Consumed by
     * scripts/coverage_report.py -- see COVERAGE_SWEEP_PLAN.md Step 4.
     */
    private static void writeCoverageReport(String path, List<DataType> dataTypes,
            java.util.Set<String> unresolved) throws Exception {
        // Only structs/unions have a meaningful "size" to check against a
        // static_assert(sizeof(...)) -- the resolved set also contains
        // function-signature DataTypes (FunctionDefinition), which report
        // getLength() == -1 and would otherwise flood the EMPTY bucket in
        // coverage_report.py with irrelevant "actual=0x-1" noise.
        List<DataType> sorted = new ArrayList<>();
        for (DataType t : dataTypes) {
            if (t instanceof Composite) {
                sorted.add(t);
            }
        }
        sorted.sort(Comparator.comparing(DataType::getName));
        try (PrintStream out = new PrintStream(new File(path))) {
            for (DataType t : sorted) {
                out.println(t.getName() + "," + t.getLength());
            }
        }
        File unresolvedFile = new File(path + ".unresolved.txt");
        try (PrintStream out = new PrintStream(unresolvedFile)) {
            unresolved.stream().sorted().forEach(out::println);
        }
        System.out.println("Wrote coverage report (" + sorted.size() + " types) to " + path
            + " and " + unresolved.size() + " unresolved name(s) to " + unresolvedFile);
    }
}

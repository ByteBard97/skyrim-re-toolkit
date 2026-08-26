import playday3008.gcpp.processing.*;
import ghidra.program.model.data.*;
import ghidra.framework.Application;
import ghidra.framework.ApplicationConfiguration;
import ghidra.GhidraApplicationLayout;

import java.io.File;
import java.io.PrintStream;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

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
 * <p>
 * TIL-export prototype (see ../TIL_EXPORT_DESIGN.md): pass --report-json
 * &lt;path&gt; to additionally write the intermediate JSON format that doc
 * specifies -- a self-contained, flattened, IDA-agnostic description of
 * every committed type, dumped from the same post-tail-padding
 * {@code FileDataTypeManager} the coverage CSV reads from. Validate the
 * output with scripts/validate_til_json.py.
 */
public class GenerateGdt {

    public static void main(String[] args) throws Exception {
        String commonlib = null, stubs = null, winsdkCrt = null, winsdkUcrt = null;
        String output = null, runtimeDefine = "ENABLE_SKYRIM_AE=1", reportCsv = null;
        String tailPaddingHints = null;
        String reportJson = null, commonlibCommit = "unknown";
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
                case "--tail-padding-hints" -> tailPaddingHints = args[++i];
                case "--report-json" -> reportJson = args[++i];
                case "--commonlib-commit" -> commonlibCommit = args[++i];
                default -> headers.add(args[i]);
            }
        }

        if (commonlib == null || stubs == null || winsdkCrt == null
            || winsdkUcrt == null || output == null || headers.isEmpty()) {
            System.err.println(
                "Usage: GenerateGdt --commonlib <dir> --stubs <dir> --winsdk-crt <dir> "
                + "--winsdk-ucrt <dir> --output <file.gdt> [--runtime ENABLE_SKYRIM_AE=1] "
                + "[--report-csv <path>] [--report-json <path>] [--commonlib-commit <sha>] "
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

        if (tailPaddingHints != null) {
            applyTailPaddingHints(fileDtMgr, tailPaddingHints);
            fileDtMgr.save();
        }

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

        if (reportJson != null) {
            // Must read from fileDtMgr AFTER the tail-padding pass above --
            // see TIL_EXPORT_DESIGN.md's "Post-commit mutations" note: a
            // JSON dumped before this pass disagrees with the shipped .gdt
            // for exactly the classes tail_padding_hints.csv exists for.
            List<DataType> committed = new ArrayList<>();
            java.util.Iterator<DataType> it = fileDtMgr.getAllDataTypes();
            while (it.hasNext()) {
                committed.add(it.next());
            }
            writeJsonReport(reportJson, committed, result.getUnresolvedDependencies(),
                runtimeDefine, commonlibCommit, sha256OfFile(gdtFile));
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

    /** SHA-256 of a file's bytes, hex-encoded -- for the JSON report's gdt_sha256 field. */
    private static String sha256OfFile(File f) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] hash = digest.digest(Files.readAllBytes(f.toPath()));
        StringBuilder hex = new StringBuilder(hash.length * 2);
        for (byte b : hash) {
            hex.append(String.format("%02x", b));
        }
        return hex.toString();
    }

    /**
     * Writes {@code path} as the intermediate JSON described in
     * ../TIL_EXPORT_DESIGN.md's "Intermediate JSON format" section --
     * self-contained (every referenced type is either in {@code primitives}
     * or defined in {@code types}), flattened (inheritance already erased by
     * the parser; this walks Ghidra's own committed Composite/Enum/TypeDef
     * shapes verbatim, adding no new layout logic), with a `provenance`
     * block per struct/union. Validate the result with
     * scripts/validate_til_json.py.
     * <p>
     * Prototype scope (see TIL_EXPORT_DESIGN.md's own work-breakdown list):
     * `provenance.baseline_status` is not yet cross-referenced against
     * coverage_baseline.json -- every struct/union gets a placeholder
     * "NOT_CHECKED" for now, which the validator accepts (only presence of
     * the field is required) but a future pass should replace with the real
     * per-class status. `tail_padded` IS populated for real, detected via
     * the distinctive description applyTailPaddingHints sets on a struct it
     * widens.
     */
    private static void writeJsonReport(String path, List<DataType> dataTypes, Set<String> unresolved,
            String runtimeDefine, String commonlibCommit, String gdtSha256) throws Exception {
        // First pass: every Composite/Enum/TypeDef's own name is a valid
        // reference target for other members -- collect before building
        // member type-refs so forward/backward references both resolve.
        Set<String> definedNames = new LinkedHashSet<>();
        for (DataType t : dataTypes) {
            if (t instanceof Composite || t instanceof ghidra.program.model.data.Enum || t instanceof TypeDef) {
                definedNames.add(t.getName());
            }
        }

        Map<String, Object> primitives = new LinkedHashMap<>();
        List<Object> types = new ArrayList<>();
        // Ghidra's category-path system lets the SAME bare name legitimately
        // exist more than once (e.g. two identical anon_tmpl_<hash> synthetic
        // structs registered under different categories) -- IDA TILs are
        // flat by name (TIL_EXPORT_DESIGN.md), so this JSON must be too.
        // Track first-seen content per name: an exact repeat is a harmless
        // Ghidra-category artifact and is dropped; a same-named entry with
        // DIFFERENT content is a genuine collision this prototype can't
        // silently resolve, so it's kept under a disambiguated name with a
        // loud stderr warning rather than either overwriting data or
        // emitting two types under one name (which would break the schema's
        // global-uniqueness assumption).
        Map<String, Object> firstSeenByName = new LinkedHashMap<>();
        int renamedForCollision = 0;

        for (DataType t : dataTypes) {
            Map<String, Object> entry;
            if (t instanceof Composite composite) {
                entry = compositeToJson(composite, definedNames, primitives);
            } else if (t instanceof ghidra.program.model.data.Enum enumType) {
                entry = enumToJson(enumType, primitives);
            } else if (t instanceof TypeDef typeDef) {
                entry = typeDefToJson(typeDef, definedNames, primitives);
            } else {
                // Function-signature DataTypes (FunctionDefinition) and
                // anything else are skipped -- function prototypes are an
                // explicit TIL_EXPORT_DESIGN.md non-goal for v0.1.
                continue;
            }

            String name = (String) entry.get("name");
            Map<String, Object> existing = (Map<String, Object>) firstSeenByName.get(name);
            if (existing == null) {
                firstSeenByName.put(name, entry);
                types.add(entry);
            } else if (existing.equals(entry)) {
                // Exact duplicate -- drop silently, nothing lost.
            } else {
                renamedForCollision++;
                String disambiguated = name + "__dup" + renamedForCollision;
                System.err.println("WARNING: type name collision on '" + name
                    + "' with DIFFERING content -- keeping second copy as '" + disambiguated + "'");
                entry.put("name", disambiguated);
                types.add(entry);
            }
        }

        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("format_version", 1);
        doc.put("generator", "GenerateGdt --report-json (type-importer)");
        doc.put("runtime", runtimeDefine);
        doc.put("commonlib_commit", commonlibCommit);
        doc.put("gdt_sha256", gdtSha256);
        doc.put("primitives", primitives);
        doc.put("types", types);
        doc.put("unresolved", new ArrayList<>(unresolved.stream().sorted().toList()));

        try (PrintStream out = new PrintStream(new File(path))) {
            writeJsonValue(doc, out);
        }
        System.out.println("Wrote TIL-export JSON (" + types.size() + " type(s), "
            + primitives.size() + " primitive(s)) to " + path);
    }

    private static Map<String, Object> compositeToJson(Composite composite, Set<String> definedNames,
            Map<String, Object> primitives) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", composite.getName());
        entry.put("kind", composite instanceof Union ? "union" : "struct");
        entry.put("size", composite.getLength());

        Map<String, Object> provenance = new LinkedHashMap<>();
        provenance.put("baseline_status", "NOT_CHECKED");
        String description = composite.getDescription();
        boolean tailPadded = description != null && description.startsWith("Widened from ");
        provenance.put("tail_padded", tailPadded);
        entry.put("provenance", provenance);

        List<Object> members = new ArrayList<>();
        // Ghidra's own struct model addresses components by offset, not
        // name, so it tolerates two components sharing a field name (seen in
        // practice on *_vtbl structs for overloaded virtual methods, e.g.
        // multiple "do_is" slots at different offsets). The schema intends
        // member names to be usable identifiers (IDA UDT members must be
        // unique), so a repeat within one struct is suffixed with its own
        // offset to stay both unique and traceable back to the source slot.
        Set<String> seenMemberNames = new LinkedHashSet<>();
        for (DataTypeComponent comp : composite.getComponents()) {
            Map<String, Object> member = new LinkedHashMap<>();
            String fieldName = comp.getFieldName();
            String name = (fieldName == null || fieldName.isEmpty())
                ? ("field_" + comp.getOffset()) : fieldName;
            if (!seenMemberNames.add(name)) {
                name = name + "_at_" + comp.getOffset();
                seenMemberNames.add(name);
            }
            member.put("name", name);
            member.put("offset", comp.getOffset());
            member.put("type", typeRefToJson(comp.getDataType(), definedNames, primitives));
            members.add(member);
        }
        entry.put("members", members);
        return entry;
    }

    private static Map<String, Object> enumToJson(ghidra.program.model.data.Enum enumType, Map<String, Object> primitives) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", enumType.getName());
        entry.put("kind", "enum");
        entry.put("size", enumType.getLength());
        String underlying = "int" + (enumType.getLength() * 8);
        registerPrimitive(primitives, underlying, enumType.getLength(), enumType.getLength(), "uint");
        entry.put("underlying", underlying);
        List<Object> members = new ArrayList<>();
        for (String name : enumType.getNames()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", name);
            m.put("value", enumType.getValue(name));
            members.add(m);
        }
        entry.put("members", members);
        return entry;
    }

    private static Map<String, Object> typeDefToJson(TypeDef typeDef, Set<String> definedNames,
            Map<String, Object> primitives) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", typeDef.getName());
        entry.put("kind", "typedef");
        Object target = typeRefToJson(typeDef.getDataType(), definedNames, primitives);
        // typedef's "to" is always a bare name per the schema, never a
        // ptr/array wrapper -- if the underlying type resolved to a wrapped
        // ref (e.g. the typedef's target is itself a pointer type), fall
        // back to registering it as an opaque primitive of the right size
        // rather than emit a shape the schema doesn't allow here.
        if (target instanceof String s) {
            entry.put("to", s);
        } else {
            String synthetic = typeDef.getName() + "_target";
            registerPrimitive(primitives, synthetic, typeDef.getLength(), typeDef.getLength(), "uint");
            entry.put("to", synthetic);
        }
        return entry;
    }

    /**
     * Resolves one field/typedef's type to one of the schema's four ref
     * shapes: a bare name string (for a primitive or another defined type),
     * {"kind":"ptr","to":N}, or {"kind":"array","of":N,"count":C}.
     */
    private static Object typeRefToJson(DataType dt, Set<String> definedNames, Map<String, Object> primitives) {
        if (dt instanceof Pointer ptr) {
            DataType pointee = ptr.getDataType();
            String to = (pointee == null) ? "void" : resolveOrRegister(pointee, definedNames, primitives);
            Map<String, Object> ref = new LinkedHashMap<>();
            ref.put("kind", "ptr");
            ref.put("to", to);
            return ref;
        }
        if (dt instanceof Array arr) {
            Map<String, Object> ref = new LinkedHashMap<>();
            ref.put("kind", "array");
            ref.put("of", resolveOrRegister(arr.getDataType(), definedNames, primitives));
            ref.put("count", arr.getNumElements());
            return ref;
        }
        return resolveOrRegister(dt, definedNames, primitives);
    }

    /** Bare-name reference: either an already-defined type, or a primitive registered on first sight. */
    private static String resolveOrRegister(DataType dt, Set<String> definedNames, Map<String, Object> primitives) {
        if (dt == null) {
            return "void";
        }
        String name = dt.getName();
        if (definedNames.contains(name)) {
            return name;
        }
        String kind;
        if (dt instanceof AbstractFloatDataType) {
            kind = "float";
        } else if (dt instanceof BooleanDataType) {
            kind = "bool";
        } else if (dt instanceof AbstractIntegerDataType intType) {
            kind = intType.isSigned() ? "int" : "uint";
        } else if (dt instanceof VoidDataType) {
            return "void";
        } else {
            // Opaque fallback (e.g. an unrecognized builtin) -- still
            // self-contained (registered in primitives), just without a
            // precise signed/float/etc. classification.
            kind = "uint";
        }
        int size = Math.max(dt.getLength(), 1);
        registerPrimitive(primitives, name, size, size, kind);
        return name;
    }

    private static void registerPrimitive(Map<String, Object> primitives, String name, int size, int align, String kind) {
        if (primitives.containsKey(name)) {
            return;
        }
        Map<String, Object> spec = new LinkedHashMap<>();
        spec.put("size", size);
        spec.put("align", Math.max(align, 1));
        spec.put("kind", kind);
        primitives.put(name, spec);
    }

    /** Minimal recursive JSON serializer -- Map/List/String/Number/Boolean/null, no external dependency. */
    private static void writeJsonValue(Object value, PrintStream out) {
        if (value == null) {
            out.print("null");
        } else if (value instanceof Map<?, ?> map) {
            out.print("{");
            boolean first = true;
            for (Map.Entry<?, ?> e : map.entrySet()) {
                if (!first) out.print(",");
                first = false;
                writeJsonString(String.valueOf(e.getKey()), out);
                out.print(":");
                writeJsonValue(e.getValue(), out);
            }
            out.print("}");
        } else if (value instanceof List<?> list) {
            out.print("[");
            boolean first = true;
            for (Object item : list) {
                if (!first) out.print(",");
                first = false;
                writeJsonValue(item, out);
            }
            out.print("]");
        } else if (value instanceof String s) {
            writeJsonString(s, out);
        } else if (value instanceof Boolean || value instanceof Number) {
            out.print(value);
        } else {
            writeJsonString(String.valueOf(value), out);
        }
    }

    private static void writeJsonString(String s, PrintStream out) {
        out.print('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.print("\\\"");
                case '\\' -> out.print("\\\\");
                case '\n' -> out.print("\\n");
                case '\r' -> out.print("\\r");
                case '\t' -> out.print("\\t");
                default -> {
                    if (c < 0x20) {
                        out.print(String.format("\\u%04x", (int) c));
                    } else {
                        out.print(c);
                    }
                }
            }
        }
        out.print('"');
    }

    /**
     * Post-processing step for the "invisible relocated member" pattern
     * (see DESIGN.md and type-importer/patches/0019-*.md): some classes'
     * real fields under a given runtime are accessed only via
     * {@code REL::RelocateMember[IfNewer]}, not declared as compiled
     * struct members, so libclang -- correctly, per the actual header
     * source -- resolves them as smaller than their true in-memory size
     * (in the worst case, a genuinely empty class). This widens a named
     * class's committed Structure with a trailing opaque byte array up to
     * an externally-supplied minimum size, mined from those
     * RelocateMember call sites by
     * scripts/mine_relocate_member_offsets.py.
     * <p>
     * This is a heuristic LOWER BOUND, not a proven exact size (there is
     * no static_assert or binary ground truth to check it against) --
     * the appended field is deliberately named/commented to make that
     * clear to anyone inspecting the resulting .gdt in Ghidra, per
     * DESIGN.md's option (b) ("flag as layout-incomplete") combined with
     * option (a) ("append the trailing bytes") rather than silently
     * picking one.
     *
     * @param hintsPath a CSV file of {@code ClassName,MinSizeInBytes} lines
     */
    private static void applyTailPaddingHints(FileDataTypeManager fileDtMgr, String hintsPath) throws Exception {
        List<String[]> hints = new ArrayList<>();
        for (String line : Files.readAllLines(new File(hintsPath).toPath())) {
            line = line.strip();
            if (line.isEmpty()) continue;
            String[] parts = line.split(",", 2);
            hints.add(new String[]{parts[0].strip(), parts[1].strip()});
        }

        int txId = fileDtMgr.startTransaction("Apply RelocateMember tail-padding hints");
        for (String[] hint : hints) {
            String className = hint[0];
            int minSize = Integer.parseInt(hint[1]);

            DataType found = null;
            java.util.Iterator<DataType> it = fileDtMgr.getAllDataTypes();
            while (it.hasNext()) {
                DataType d = it.next();
                if (d.getName().equals(className)) {
                    found = d;
                    break;
                }
            }

            if (found == null) {
                System.out.println("tail-padding-hints: '" + className + "' not found in resolved types, skipping");
                continue;
            }
            if (!(found instanceof Structure struct)) {
                System.out.println("tail-padding-hints: '" + className + "' is not a Structure ("
                    + found.getClass().getSimpleName() + "), skipping");
                continue;
            }

            // Ghidra reports getLength()==1 for a struct with zero real
            // components (its own "empty struct" convention, not an actual
            // occupied byte) -- adding a trailing field to such a struct
            // REPLACES that phantom byte rather than appending after it, so
            // the gap to fill is the full minSize, not minSize - 1.
            int currentSize = struct.getNumComponents() == 0 ? 0 : struct.getLength();
            int gap = minSize - currentSize;
            if (gap <= 0) {
                System.out.println("tail-padding-hints: '" + className + "' already >= " + minSize
                    + " bytes (actual " + currentSize + "), not padding");
                continue;
            }

            ArrayDataType padding = new ArrayDataType(ghidra.program.model.data.CharDataType.dataType, gap, 1);
            struct.add(padding, "inferred_tail__see_RelocateMember_offsets_not_asserted", null);
            struct.setDescription(
                "Widened from " + currentSize + " to " + minSize + " bytes: real fields beyond "
                + currentSize + " are accessed via REL::RelocateMember[IfNewer], not declared as "
                + "compiled struct members under this runtime. This is a heuristic lower bound "
                + "mined from those call sites (scripts/mine_relocate_member_offsets.py), NOT a "
                + "proven exact size -- see type-importer/DESIGN.md and patches/0019-*.md.");
            System.out.println("tail-padding-hints: widened '" + className + "' from " + currentSize
                + " to " + struct.getLength() + " bytes (target " + minSize + ")");
        }
        fileDtMgr.endTransaction(txId, true);
    }
}

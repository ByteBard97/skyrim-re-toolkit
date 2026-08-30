// Headless applier (FUNCTION_SIGNATURE_DESIGN.md, component D): create named,
// typed Function objects and data labels at Address-Library-resolved
// addresses in the user's own binary.
//
// Input: symbols.json from type-importer/scripts/mine_function_ids.py
//   {"version":1, "target":"ae", "symbols":[
//      {"n":"Actor::AddSpell","t":"func","src":"RE/Offsets.h","id":38716,"rva":7061328},
//      {"n":"VTABLE_Actor","t":"label","src":"RE/Offsets_VTABLE.h","id":...,"rva":...}]}
//
// Function signatures come from the program's DTM (populated beforehand by
// ApplyGdt.java): FunctionDefinition types named "Class::Method" under
// <category>/functions, emitted by the type-importer parser. If a matching
// FunctionDefinition is absent the function is still created and named --
// name and address never depend on the type archive.
//
// args: <symbols.json>
//
// Nothing from the game is redistributed: runs against a locally-owned
// binary inside a local Ghidra project.
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FunctionDefinition;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.CommentType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.FileReader;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

public class ApplySymbols extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: ApplySymbols.java <symbols.json>");
            return;
        }

        JsonObject doc = JsonParser.parseReader(new FileReader(args[0])).getAsJsonObject();
        JsonArray symbols = doc.getAsJsonArray("symbols");
        println("ApplySymbols: target=" + doc.get("target").getAsString()
            + ", " + symbols.size() + " symbols from " + args[0]);

        // Name -> FunctionDefinition map from the DTM (types applied by ApplyGdt).
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        Map<String, FunctionDefinition> funcDefs = new HashMap<>();
        Iterator<DataType> it = dtm.getAllDataTypes();
        while (it.hasNext()) {
            DataType dt = it.next();
            if (dt instanceof FunctionDefinition) {
                funcDefs.putIfAbsent(dt.getName(), (FunctionDefinition) dt);
            }
        }
        println("ApplySymbols: " + funcDefs.size() + " FunctionDefinitions available in DTM");

        Address imageBase = currentProgram.getImageBase();
        int labels = 0, funcsCreated = 0, funcsRenamed = 0, sigsApplied = 0, sigsMissing = 0, failures = 0;
        java.util.List<String> createFails = new java.util.ArrayList<>();
        java.util.List<String> sigFails = new java.util.ArrayList<>();

        for (int i = 0; i < symbols.size(); i++) {
            if (monitor.isCancelled()) break;
            JsonObject sym = symbols.get(i).getAsJsonObject();
            if (!sym.has("rva")) continue;
            String name = sym.get("n").getAsString();
            String kind = sym.get("t").getAsString();
            long rva = sym.get("rva").getAsLong();
            Address addr = imageBase.add(rva);
            String plate = String.format("REL::ID(%d)  [source: %s]",
                sym.get("id").getAsLong(), sym.get("src").getAsString());

            try {
                // Executable-block check: header conventions alone can't
                // distinguish function vs data addresses (e.g. Offsets.h
                // lists singleton data pointers alongside functions), so
                // verify against the binary itself.
                ghidra.program.model.mem.MemoryBlock block =
                    currentProgram.getMemory().getBlock(addr);
                boolean executable = block != null && block.isExecute();

                if ("label".equals(kind) || !executable) {
                    if (getSymbolAt(addr) == null || getSymbolAt(addr).isDynamic()) {
                        createLabel(addr, name, false, SourceType.USER_DEFINED);
                        labels++;
                    }
                    continue;
                }

                // function
                Function fn = getFunctionAt(addr);
                if (fn == null) {
                    new DisassembleCommand(addr, null, true).applyTo(currentProgram, monitor);
                    fn = createFunction(addr, name);
                    if (fn != null) funcsCreated++;
                }
                if (fn == null) {
                    failures++;
                    if (createFails.size() < 15) createFails.add(name + " @ " + addr);
                    continue;
                }
                if (fn.getSymbol().isDynamic() || fn.getName().startsWith("FUN_")) {
                    fn.setName(name, SourceType.USER_DEFINED);
                    funcsRenamed++;
                }
                writePlate(addr, plate);

                FunctionDefinition def = funcDefs.get(name);
                if (def != null) {
                    ApplyFunctionSignatureCmd cmd =
                        new ApplyFunctionSignatureCmd(addr, def, SourceType.USER_DEFINED, false, false);
                    if (cmd.applyTo(currentProgram)) {
                        sigsApplied++;
                    } else {
                        failures++;
                        if (sigFails.size() < 15) sigFails.add(name + " @ " + addr + " : " + cmd.getStatusMsg());
                    }
                } else {
                    sigsMissing++;
                }
            } catch (Exception e) {
                failures++;
                if (failures <= 10) printerr("ApplySymbols: " + name + " @ " + addr + ": " + e);
            }
            if (i % 5000 == 0 && i > 0) println("ApplySymbols: " + i + " symbols processed...");
        }

        println("=== ApplySymbols summary ===");
        println("  labels created     : " + labels);
        println("  functions created  : " + funcsCreated);
        println("  functions (re)named: " + funcsRenamed);
        println("  signatures applied : " + sigsApplied);
        println("  no signature in DTM: " + sigsMissing + " (named only)");
        println("  failures           : " + failures);
        int funcTotal = sigsApplied + sigsMissing;
        if (funcTotal > 0) {
            println(String.format("  signature coverage : %d/%d function symbols typed (%.1f%%)",
                sigsApplied, funcTotal, 100.0 * sigsApplied / funcTotal));
        }
        for (String s : createFails) println("  create-fail: " + s);
        for (String s : sigFails) println("  sig-fail   : " + s);
    }

    private void writePlate(Address addr, String comment) {
        CodeUnit cu = currentProgram.getListing().getCodeUnitAt(addr);
        if (cu != null) {
            cu.setComment(CommentType.PLATE, comment);
        }
    }
}

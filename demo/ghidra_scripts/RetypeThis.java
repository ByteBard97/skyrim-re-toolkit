// Demo helper: give a function a typed `this` parameter from the imported
// archive, so the decompiler renders member accesses through real struct
// fields. Run after ApplyGdt.java, in its OWN headless pass so the change
// commits before a separate decompile pass reads it.
//
// args: (<hex-func-addr> <struct-type-name>)...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Function.FunctionUpdateType;
import ghidra.program.model.listing.Parameter;
import ghidra.program.model.listing.ParameterImpl;
import ghidra.program.model.symbol.SourceType;
import java.util.ArrayList;
import java.util.List;

public class RetypeThis extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        for (int i = 0; i + 1 < args.length; i += 2) {
            var addr = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
            String typeName = args[i + 1];
            Function f = getFunctionContaining(addr);
            if (f == null) f = createFunction(addr, null);
            if (f == null) { printerr("no function at " + args[i]); continue; }

            List<DataType> hits = new ArrayList<>();
            currentProgram.getDataTypeManager().findDataTypes(typeName, hits);
            if (hits.isEmpty()) { printerr("type not found: " + typeName); continue; }

            var dtm = currentProgram.getDataTypeManager();
            DataType struct = dtm.resolve(hits.get(0), null);
            DataType ptr = dtm.getPointer(struct);
            // Do NOT use __thiscall: it makes `this` an AUTO parameter Ghidra
            // refuses to retype (it stays void*). On x64 the ABI is __fastcall
            // and `this` is simply the first arg (RCX), so an explicit formal
            // first parameter typed as the struct pointer is what we want.
            Parameter thisParam = new ParameterImpl("self", ptr, currentProgram);
            f.updateFunction("__fastcall", null, List.of(thisParam),
                FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS, true, SourceType.USER_DEFINED);
            println("RetypeThis: " + args[i] + " -> "
                + f.getParameter(0).getDataType().getName() + " " + f.getParameter(0).getName());
        }
    }
}

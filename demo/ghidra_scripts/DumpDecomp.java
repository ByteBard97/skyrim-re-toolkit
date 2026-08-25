// Headless helper for the demo (issue #1): decompile the function(s)
// containing the given address(es) and append the pseudo-C to a file.
//
// args: <output-file> <hex-address> [<hex-address> ...]
//
// Used twice per demo build: once on the freshly-analyzed (untyped) program
// for the "before", once after the .gdt types are applied for the "after".
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.FileWriter;
import java.io.PrintWriter;

public class DumpDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: DumpDecomp.java <output-file> <hex-address>...");
            return;
        }
        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            for (int i = 1; i < args.length; i++) {
                Address addr = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
                Function f = getFunctionContaining(addr);
                out.println("// ==== " + args[i] + " ====");
                if (f == null) {
                    // headless analysis of a 37MB stripped PE leaves most of
                    // the binary undisassembled -- create the target on demand
                    disassemble(addr);
                    f = createFunction(addr, null);
                }
                if (f == null) {
                    out.println("// no function at this address (creation failed)");
                    continue;
                }
                out.println("// function: " + f.getName() + " @ " + f.getEntryPoint());
                DecompileResults res = decomp.decompileFunction(f, 120, monitor);
                if (res.decompileCompleted()) {
                    out.println(res.getDecompiledFunction().getC());
                } else {
                    out.println("// decompilation failed: " + res.getErrorMessage());
                }
            }
        } finally {
            decomp.dispose();
        }
        println("DumpDecomp: wrote " + args[0]);
    }
}

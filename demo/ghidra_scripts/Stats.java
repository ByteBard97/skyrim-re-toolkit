// One-off diagnostic: function/symbol counts and spot-checks for the demo project.
// args: <output-file> [<hex-addr> ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.FileWriter;
import java.io.PrintWriter;

public class Stats extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            out.println("functions: " + currentProgram.getFunctionManager().getFunctionCount());
            out.println("instructions: " + currentProgram.getListing().getNumInstructions());
            out.println("defined data: " + currentProgram.getListing().getNumDefinedData());
            for (int i = 1; i < args.length; i++) {
                Address a = toAddr(Long.parseLong(args[i].replace("0x", ""), 16));
                Function f = getFunctionContaining(a);
                out.println(args[i] + " -> " + (f == null ? "no function"
                    : f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses()));
            }
        }
        println("Stats: done");
    }
}

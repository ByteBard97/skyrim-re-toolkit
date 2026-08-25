// Demo helper: find RTTI-recovered vftables for the named classes and dump
// their first few virtual-function slot addresses, so the demo can target
// real engine functions with known class context.
//
// args: <output-file> <class-name> [<class-name> ...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

public class ListVftables extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: ListVftables.java <output-file> <class-name>...");
            return;
        }
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            SymbolIterator it = currentProgram.getSymbolTable().getSymbolIterator("*vftable*", true);
            while (it.hasNext() && !monitor.isCancelled()) {
                Symbol s = it.next();
                String path = s.getParentNamespace() != null ? s.getParentNamespace().getName(true) : "";
                for (int i = 1; i < args.length; i++) {
                    if (path.contains(args[i]) || s.getName(true).contains(args[i])) {
                        out.println("vftable: " + s.getName(true) + " @ " + s.getAddress());
                        Address a = s.getAddress();
                        for (int slot = 0; slot < 8; slot++) {
                            try {
                                long ptr = currentProgram.getMemory().getLong(a.add(slot * 8L));
                                out.println("  slot" + slot + ": 0x" + Long.toHexString(ptr));
                            } catch (Exception e) {
                                break;
                            }
                        }
                        break;
                    }
                }
            }
        }
        println("ListVftables: done");
    }
}

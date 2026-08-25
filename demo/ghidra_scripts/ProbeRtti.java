// One-off diagnostic: does the analyzed program contain RTTI-derived class
// symbols/namespaces, and where do the raw MSVC type-descriptor strings for
// a target class live?
// args: <output-file> <class-name>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

public class ProbeRtti extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String cls = args[1];
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            int vft = 0, clsSyms = 0;
            SymbolIterator it = currentProgram.getSymbolTable().getAllSymbols(false);
            while (it.hasNext() && !monitor.isCancelled()) {
                Symbol s = it.next();
                String n = s.getName(true);
                if (n.contains("vftable") || n.contains("??_7")) vft++;
                if (n.contains(cls)) {
                    clsSyms++;
                    if (clsSyms <= 10) out.println("sym: " + n + " @ " + s.getAddress());
                }
            }
            out.println("total vftable-ish symbols: " + vft);
            out.println("symbols containing '" + cls + "': " + clsSyms);
            // raw type descriptor string
            Address a = find(".?AV" + cls + "@@");
            out.println("type-descriptor string '.?AV" + cls + "@@' at: " + a);
        }
        println("ProbeRtti: done");
    }
}

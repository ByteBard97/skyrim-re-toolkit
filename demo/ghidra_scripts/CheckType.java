// Diagnostic: confirm an imported struct exists with real fields in the
// program DTM. args: <output-file> <type-name>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.Structure;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

public class CheckType extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        List<DataType> hits = new ArrayList<>();
        currentProgram.getDataTypeManager().findDataTypes(args[1], hits);
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            out.println(args[1] + ": " + hits.size() + " match(es)");
            for (DataType dt : hits) {
                out.println("  " + dt.getPathName() + " len=" + dt.getLength()
                    + (dt instanceof Structure ? " fields=" + ((Structure) dt).getNumComponents() : ""));
                if (dt instanceof Structure) {
                    Structure st = (Structure) dt;
                    int shown = 0;
                    for (var c : st.getComponents()) {
                        if (c.getFieldName() == null) continue;
                        out.println(String.format("    +0x%x %s %s", c.getOffset(),
                            c.getDataType().getName(), c.getFieldName()));
                        if (++shown >= 8) break;
                    }
                }
            }
        }
        println("CheckType: done");
    }
}

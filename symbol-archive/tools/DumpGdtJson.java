// Dump every type in a .gdt archive to structured JSON, for the type-layout
// explorer (and any other consumer of the archive's contents).
//
// Run headless with NO program (uses an empty project):
//   analyzeHeadless <proj> Tmp -import <any-tiny-file> \
//     -postScript DumpGdtJson.java <archive.gdt> <out.json>
// or against an existing project with -process. Simplest: point it at the
// .gdt directly via the args and ignore currentProgram.
//
// args: <archive.gdt> <out.json>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.Iterator;

public class DumpGdtJson extends GhidraScript {
    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        return b.toString();
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: DumpGdtJson.java <archive.gdt> <out.json>");
            return;
        }
        FileDataTypeManager dtm = FileDataTypeManager.openFileArchive(new File(args[0]), false);
        int structs = 0, unions = 0, enums = 0, typedefs = 0;
        try (PrintWriter out = new PrintWriter(new FileWriter(args[1]))) {
            out.println("{");
            out.println("  \"source\": \"" + esc(new File(args[0]).getName()) + "\",");
            out.println("  \"types\": [");
            boolean first = true;
            Iterator<DataType> it = dtm.getAllDataTypes();
            while (it.hasNext()) {
                if (monitor.isCancelled()) break;
                DataType dt = it.next();
                String kind, body;
                if (dt instanceof Structure) {
                    kind = "struct"; structs++;
                    body = dumpComposite((Composite) dt);
                } else if (dt instanceof Union) {
                    kind = "union"; unions++;
                    body = dumpComposite((Composite) dt);
                } else if (dt instanceof ghidra.program.model.data.Enum) {
                    kind = "enum"; enums++;
                    body = dumpEnum((ghidra.program.model.data.Enum) dt);
                } else if (dt instanceof TypeDef) {
                    kind = "typedef"; typedefs++;
                    body = "\"underlying\": \"" + esc(((TypeDef) dt).getDataType().getName()) + "\"";
                } else {
                    continue;
                }
                if (!first) out.println(",");
                first = false;
                out.print("    {\"name\": \"" + esc(dt.getName())
                    + "\", \"kind\": \"" + kind + "\""
                    + ", \"category\": \"" + esc(dt.getCategoryPath().getPath()) + "\""
                    + ", \"size\": " + dt.getLength()
                    + ", " + body + "}");
            }
            out.println();
            out.println("  ]");
            out.println("}");
        } finally {
            dtm.close();
        }
        println("DumpGdtJson: " + structs + " structs, " + unions + " unions, "
            + enums + " enums, " + typedefs + " typedefs -> " + args[1]);
    }

    private String dumpComposite(Composite c) {
        StringBuilder b = new StringBuilder("\"fields\": [");
        boolean first = true;
        for (DataTypeComponent comp : c.getComponents()) {
            String fn = comp.getFieldName();
            if (!first) b.append(", ");
            first = false;
            b.append("{\"offset\": ").append(comp.getOffset())
             .append(", \"name\": \"").append(esc(fn == null ? "" : fn)).append("\"")
             .append(", \"type\": \"").append(esc(comp.getDataType().getName())).append("\"")
             .append(", \"size\": ").append(comp.getLength()).append("}");
        }
        b.append("]");
        return b.toString();
    }

    private String dumpEnum(ghidra.program.model.data.Enum e) {
        StringBuilder b = new StringBuilder("\"values\": [");
        boolean first = true;
        for (String name : e.getNames()) {
            if (!first) b.append(", ");
            first = false;
            b.append("{\"name\": \"").append(esc(name)).append("\", \"value\": ")
             .append(e.getValue(name)).append("}");
        }
        b.append("]");
        return b.toString();
    }
}

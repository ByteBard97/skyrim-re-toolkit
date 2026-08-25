// Headless helper for the demo (issue #1): import every type from a .gdt
// archive into the current program's data type manager, so subsequent
// decompilation (and manual retyping) can use the CommonLibSSE-NG-derived
// structs.
//
// args: <path-to-gdt>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FileDataTypeManager;
import java.io.File;
import java.util.Iterator;

public class ApplyGdt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: ApplyGdt.java <path-to-gdt>");
            return;
        }
        FileDataTypeManager archive = FileDataTypeManager.openFileArchive(new File(args[0]), false);
        try {
            DataTypeManager dtm = currentProgram.getDataTypeManager();
            int added = 0;
            Iterator<DataType> it = archive.getAllDataTypes();
            while (it.hasNext()) {
                if (monitor.isCancelled()) break;
                dtm.addDataType(it.next(), DataTypeConflictHandler.REPLACE_HANDLER);
                added++;
                if (added % 2000 == 0) println("ApplyGdt: " + added + " types...");
            }
            println("ApplyGdt: imported " + added + " data types from " + args[0]);
        } finally {
            archive.close();
        }
    }
}

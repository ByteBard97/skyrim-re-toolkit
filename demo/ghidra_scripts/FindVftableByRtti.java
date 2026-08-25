// Demo helper: locate a class's vftable(s) by walking MSVC RTTI manually
// (the headless run didn't produce RTTI symbols). 64-bit MSVC layout:
//   TypeDescriptor TD:   [vtable-ptr][spare][name ".?AVX@@"...]  (name at TD+0x10)
//   CompleteObjectLocator COL: {sig=1, offset, cdOffset, TD_rva, CHD_rva, COL_rva}
//   vftable slot0 sits 8 bytes after a pointer to the COL.
// args: <output-file> <class-name>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import java.io.FileWriter;
import java.io.PrintWriter;

public class FindVftableByRtti extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String cls = args[1];
        Memory mem = currentProgram.getMemory();
        long imageBase = currentProgram.getImageBase().getOffset();
        try (PrintWriter out = new PrintWriter(new FileWriter(args[0], true))) {
            Address nameAddr = find(".?AV" + cls + "@@");
            if (nameAddr == null) { out.println(cls + ": no type descriptor"); return; }
            long tdRva = nameAddr.getOffset() - 0x10 - imageBase;
            out.println(cls + ": TD RVA 0x" + Long.toHexString(tdRva));

            byte[] needle = new byte[] {
                (byte) tdRva, (byte) (tdRva >> 8), (byte) (tdRva >> 16), (byte) (tdRva >> 24) };
            Address cur = currentProgram.getMinAddress();
            int found = 0;
            while (found < 6 && !monitor.isCancelled()) {
                Address hit = mem.findBytes(cur, needle, null, true, monitor);
                if (hit == null) break;
                cur = hit.add(1);
                Address colAddr = hit.subtract(0xC);
                try {
                    if (mem.getInt(colAddr) != 1) continue;      // 64-bit COL signature
                    int colSelfRva = mem.getInt(colAddr.add(0x14));
                    if (colSelfRva != (int) (colAddr.getOffset() - imageBase)) continue;
                    int offsetInClass = mem.getInt(colAddr.add(4));
                    // find the vftable: a pointer to this COL, slot0 follows it
                    long colPtr = colAddr.getOffset();
                    byte[] pn = new byte[8];
                    for (int i = 0; i < 8; i++) pn[i] = (byte) (colPtr >> (8 * i));
                    Address metaHit = mem.findBytes(currentProgram.getMinAddress(), pn, null, true, monitor);
                    if (metaHit == null) continue;
                    Address vft = metaHit.add(8);
                    out.println("  COL @ " + colAddr + " offsetInClass=0x" + Integer.toHexString(offsetInClass)
                        + " vftable @ " + vft);
                    for (int slot = 0; slot < 10; slot++) {
                        long fp = mem.getLong(vft.add(slot * 8L));
                        out.println("    slot" + slot + ": 0x" + Long.toHexString(fp));
                    }
                    found++;
                } catch (Exception e) { /* not a COL, keep scanning */ }
            }
            out.println(cls + ": " + found + " COL(s) found");
        }
        println("FindVftableByRtti: done");
    }
}

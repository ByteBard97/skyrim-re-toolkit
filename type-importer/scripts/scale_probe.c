// Pure-C libclang probe: does template-arg/sizeof introspection become
// order-dependent at full-1630-header scale, with NO Java/Panama involved?
//
// Phase 1: minimal-traffic queries on target classes (the 10 patch-0007
//          regressions + hkRefPtr fields).
// Phase 2: sweep-like heavy traffic (sizeof + canonical + template args on
//          every record in the TU).
// Phase 3: identical re-queries; any diff vs phase 1 = libclang itself is
//          order-dependent at scale (H2). No diff = Java/FFM layer (H1).
#include <clang-c/Index.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const char *TARGETS[] = {
    "ArmorRatingVisitor", "BSStream", "Data190", "ExtraLinkedRef",
    "ExtraLinkedRefChildren", "LinkerProcessor", "LocalMapCamera",
    "NiStream", "RaceSexCamera", "TESCamera", NULL
};

#define MAX_MATCHES 64
static CXCursor g_matches[MAX_MATCHES];
static int g_nmatches = 0;

#define MAX_HKREF 8
static CXCursor g_hkref_fields[MAX_HKREF];
static int g_nhkref = 0;

static long g_traffic_records = 0;

static int is_target(const char *name) {
    for (int i = 0; TARGETS[i]; i++)
        if (strcmp(name, TARGETS[i]) == 0) return 1;
    return 0;
}

static enum CXChildVisitResult collect_visitor(CXCursor c, CXCursor parent, CXClientData d) {
    (void)parent; (void)d;
    enum CXCursorKind k = clang_getCursorKind(c);
    if (k == CXCursor_ClassDecl || k == CXCursor_StructDecl) {
        if (clang_isCursorDefinition(c)) {
            CXString sp = clang_getCursorSpelling(c);
            const char *name = clang_getCString(sp);
            if (is_target(name) && g_nmatches < MAX_MATCHES)
                g_matches[g_nmatches++] = c;
            clang_disposeString(sp);
        }
    } else if (k == CXCursor_FieldDecl && g_nhkref < MAX_HKREF) {
        CXType t = clang_getCursorType(c);
        CXString ts = clang_getTypeSpelling(t);
        const char *tn = clang_getCString(ts);
        if (strstr(tn, "hkRefPtr<") == tn || strstr(tn, "RE::hkRefPtr<") == tn)
            g_hkref_fields[g_nhkref++] = c;
        clang_disposeString(ts);
    }
    return CXChildVisit_Recurse;
}

static void dump_type_template_args(const char *label, CXType t) {
    CXString sp = clang_getTypeSpelling(t);
    int n = clang_Type_getNumTemplateArguments(t);
    printf("    %s: '%s' numTemplateArgs=%d\n", label, clang_getCString(sp), n);
    clang_disposeString(sp);
    for (int i = 0; i < n && i < 8; i++) {
        CXType a = clang_Type_getTemplateArgumentAsType(t, (unsigned)i);
        CXString as = clang_getTypeSpelling(a);
        printf("      arg[%d] = '%s' (kind=%d, sizeof=%lld)\n",
               i, clang_getCString(as), (int)a.kind,
               (long long)clang_Type_getSizeOf(a));
        clang_disposeString(as);
    }
}

static void query_targets(const char *phase) {
    printf("=== %s: target-class queries ===\n", phase);
    for (int i = 0; i < g_nmatches; i++) {
        CXCursor c = g_matches[i];
        CXString sp = clang_getCursorSpelling(c);
        CXType t = clang_getCursorType(c);
        long long sz = clang_Type_getSizeOf(t);
        CXSourceLocation loc = clang_getCursorLocation(c);
        CXFile file; unsigned line;
        clang_getFileLocation(loc, &file, &line, NULL, NULL);
        CXString fn = clang_getFileName(file);
        printf("  %-24s sizeof=%-6lld (%s:%u)\n", clang_getCString(sp), sz,
               clang_getCString(fn), line);
        clang_disposeString(fn);
        clang_disposeString(sp);
    }
    printf("=== %s: hkRefPtr field queries ===\n", phase);
    for (int i = 0; i < g_nhkref; i++) {
        CXType t = clang_getCursorType(g_hkref_fields[i]);
        CXString ts = clang_getTypeSpelling(t);
        printf("  field type '%s' sizeof=%lld\n", clang_getCString(ts),
               (long long)clang_Type_getSizeOf(t));
        clang_disposeString(ts);
        CXType canon = clang_getCanonicalType(t);
        dump_type_template_args("canonical", canon);
    }
    fflush(stdout);
}

static enum CXChildVisitResult arv_field_visitor(CXCursor c, CXCursor parent, CXClientData d) {
    (void)parent; (void)d;
    if (clang_getCursorKind(c) == CXCursor_FieldDecl) {
        CXString sp = clang_getCursorSpelling(c);
        CXType t = clang_getCursorType(c);
        CXString ts = clang_getTypeSpelling(t);
        printf("  field %s: '%s' sizeof=%lld\n", clang_getCString(sp),
               clang_getCString(ts), (long long)clang_Type_getSizeOf(t));
        clang_disposeString(ts);
        clang_disposeString(sp);
        dump_type_template_args("sugared", clang_getCursorType(c));
        dump_type_template_args("canonical", clang_getCanonicalType(clang_getCursorType(c)));
    }
    return CXChildVisit_Continue;
}

static void arv_deep_dive(const char *phase) {
    for (int i = 0; i < g_nmatches; i++) {
        CXString sp = clang_getCursorSpelling(g_matches[i]);
        int is_arv = strcmp(clang_getCString(sp), "ArmorRatingVisitor") == 0;
        clang_disposeString(sp);
        if (!is_arv) continue;
        printf("=== %s: ArmorRatingVisitor fields ===\n", phase);
        clang_visitChildren(g_matches[i], arv_field_visitor, NULL);
        break;
    }
    fflush(stdout);
}

// Phase 2: emulate the sweep's traffic — for EVERY record definition in the
// TU: sizeof, alignof, canonical type, template-arg enumeration.
static enum CXChildVisitResult traffic_visitor(CXCursor c, CXCursor parent, CXClientData d) {
    (void)parent; (void)d;
    enum CXCursorKind k = clang_getCursorKind(c);
    if ((k == CXCursor_ClassDecl || k == CXCursor_StructDecl) && clang_isCursorDefinition(c)) {
        CXType t = clang_getCursorType(c);
        clang_Type_getSizeOf(t);
        clang_Type_getAlignOf(t);
        CXType canon = clang_getCanonicalType(t);
        int n = clang_Type_getNumTemplateArguments(canon);
        for (int i = 0; i < n && i < 8; i++) {
            CXType a = clang_Type_getTemplateArgumentAsType(canon, (unsigned)i);
            clang_Type_getSizeOf(a);
        }
        g_traffic_records++;
    } else if (k == CXCursor_FieldDecl) {
        CXType t = clang_getCursorType(c);
        clang_Type_getSizeOf(t);
        CXType canon = clang_getCanonicalType(t);
        int n = clang_Type_getNumTemplateArguments(canon);
        for (int i = 0; i < n && i < 8; i++) {
            CXType a = clang_Type_getTemplateArgumentAsType(canon, (unsigned)i);
            clang_Type_getSizeOf(a);
        }
    }
    return CXChildVisit_Recurse;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s umbrella.hpp [clang args...]\n", argv[0]); return 2; }
    CXString ver = clang_getClangVersion();
    printf("libclang: %s\n", clang_getCString(ver));
    clang_disposeString(ver);

    CXIndex idx = clang_createIndex(1, 0);
    CXTranslationUnit tu = NULL;
    unsigned flags = CXTranslationUnit_Incomplete |
                     CXTranslationUnit_SkipFunctionBodies |
                     CXTranslationUnit_KeepGoing |
                     CXTranslationUnit_IncludeAttributedTypes |
                     CXTranslationUnit_VisitImplicitAttributes;
    enum CXErrorCode err = clang_parseTranslationUnit2(
        idx, argv[1], (const char *const *)(argv + 2), argc - 2,
        NULL, 0, flags, &tu);
    if (err != CXError_Success || !tu) { fprintf(stderr, "parse failed: %d\n", (int)err); return 1; }

    unsigned ndiag = clang_getNumDiagnostics(tu);
    unsigned nerr = 0;
    for (unsigned i = 0; i < ndiag; i++) {
        CXDiagnostic dg = clang_getDiagnostic(tu, i);
        if (clang_getDiagnosticSeverity(dg) >= CXDiagnostic_Error) nerr++;
        clang_disposeDiagnostic(dg);
    }
    printf("parsed OK, %u diagnostics (%u errors)\n", ndiag, nerr);
    fflush(stdout);

    CXCursor root = clang_getTranslationUnitCursor(tu);
    clang_visitChildren(root, collect_visitor, NULL);
    printf("collected %d target class definitions, %d hkRefPtr fields\n",
           g_nmatches, g_nhkref);

    query_targets("PHASE1");
    arv_deep_dive("PHASE1");

    printf("=== PHASE2: heavy sweep-like traffic over entire TU ===\n");
    fflush(stdout);
    clang_visitChildren(root, traffic_visitor, NULL);
    printf("traffic complete: %ld record definitions exercised\n", g_traffic_records);

    query_targets("PHASE3");
    arv_deep_dive("PHASE3");

    clang_disposeTranslationUnit(tu);
    clang_disposeIndex(idx);
    return 0;
}

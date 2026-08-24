// Diagnostic probe for the runner-only Directional::MaxMin<Color> EMPTY
// divergence (see patches/0012-*.md). Prints, for every field of every
// struct named by the -DPROBE_CLASS compile-time... (keep it simple: walks
// BGSDirectionalAmbientLightingColors and nested records), exactly what
// libclang reports: type kind, unwrapped kind, spelling, declaration cursor
// kind, sizeOf, and what clang_Type_visitFields finds on the field's type.
// Compares a GitHub runner's answers against a local machine's byte-for-byte.
#include <clang-c/Index.h>
#include <stdio.h>
#include <string.h>

static const char *kindName(enum CXCursorKind k) {
    CXString s = clang_getCursorKindSpelling(k);
    static char buf[128];
    snprintf(buf, sizeof(buf), "%s(%d)", clang_getCString(s), (int)k);
    clang_disposeString(s);
    return buf;
}

static enum CXVisitorResult countField(CXCursor c, CXClientData d) {
    int *n = (int *)d;
    (*n)++;
    CXString fn = clang_getCursorSpelling(c);
    CXString ft = clang_getTypeSpelling(clang_getCursorType(c));
    printf("        visitFields[%d]: %s : %s\n", *n, clang_getCString(fn), clang_getCString(ft));
    clang_disposeString(fn); clang_disposeString(ft);
    return CXVisit_Continue;
}

static enum CXChildVisitResult fieldVisitor(CXCursor c, CXCursor p, CXClientData d) {
    (void)p; (void)d;
    if (clang_getCursorKind(c) != CXCursor_FieldDecl) return CXChildVisit_Continue;
    CXString fn = clang_getCursorSpelling(c);
    CXType t = clang_getCursorType(c);
    CXString ts = clang_getTypeSpelling(t);
    printf("    field %s: spelling='%s' kind=%d\n", clang_getCString(fn), clang_getCString(ts), (int)t.kind);
    clang_disposeString(fn); clang_disposeString(ts);

    // unwrap elaborated/attributed like the Java layer's Type.unwrap()
    CXType u = t;
    for (int i = 0; i < 8; i++) {
        if (u.kind == CXType_Elaborated) u = clang_Type_getNamedType(u);
        else if (u.kind == CXType_Attributed) u = clang_Type_getModifiedType(u);
        else break;
    }
    printf("      unwrapped kind=%d sizeOf=%lld\n", (int)u.kind, (long long)clang_Type_getSizeOf(u));
    CXCursor decl = clang_getTypeDeclaration(u);
    printf("      decl kind=%s isDefinition=%d\n", kindName(clang_getCursorKind(decl)),
           clang_isCursorDefinition(decl));
    CXType canon = clang_getCanonicalType(u);
    CXString cs = clang_getTypeSpelling(canon);
    printf("      canonical='%s' canonSizeOf=%lld\n", clang_getCString(cs),
           (long long)clang_Type_getSizeOf(canon));
    clang_disposeString(cs);
    int nfields = 0;
    clang_Type_visitFields(u, countField, &nfields);
    printf("      visitFields total=%d\n", nfields);
    return CXChildVisit_Continue;
}

static enum CXChildVisitResult find(CXCursor c, CXCursor p, CXClientData d) {
    (void)p; (void)d;
    enum CXCursorKind k = clang_getCursorKind(c);
    if ((k == CXCursor_ClassDecl || k == CXCursor_StructDecl) && clang_isCursorDefinition(c)) {
        CXString sp = clang_getCursorSpelling(c);
        const char *n = clang_getCString(sp);
        if (strcmp(n, "BGSDirectionalAmbientLightingColors") == 0 || strcmp(n, "Directional") == 0) {
            printf("== %s ==\n", n);
            clang_visitChildren(c, fieldVisitor, NULL);
        }
        clang_disposeString(sp);
    }
    return CXChildVisit_Recurse;
}

int main(int argc, char **argv) {
    CXString ver = clang_getClangVersion();
    printf("libclang: %s\n", clang_getCString(ver));
    clang_disposeString(ver);
    CXIndex idx = clang_createIndex(1, 0);
    CXTranslationUnit tu = NULL;
    enum CXErrorCode err = clang_parseTranslationUnit2(
        idx, argv[1], (const char *const *)(argv + 2), argc - 2, NULL, 0,
        CXTranslationUnit_Incomplete | CXTranslationUnit_SkipFunctionBodies |
        CXTranslationUnit_KeepGoing | CXTranslationUnit_IncludeAttributedTypes |
        CXTranslationUnit_VisitImplicitAttributes, &tu);
    if (err != CXError_Success || !tu) { fprintf(stderr, "parse failed: %d\n", (int)err); return 1; }
    unsigned nd = clang_getNumDiagnostics(tu), ne = 0;
    for (unsigned i = 0; i < nd; i++) {
        CXDiagnostic dg = clang_getDiagnostic(tu, i);
        if (clang_getDiagnosticSeverity(dg) >= CXDiagnostic_Error) ne++;
        clang_disposeDiagnostic(dg);
    }
    printf("diagnostics=%u errors=%u\n", nd, ne);
    clang_visitChildren(clang_getTranslationUnitCursor(tu), find, NULL);
    return 0;
}

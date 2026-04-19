"""
backend/semantic.py
====================
Semantic analysis: builds symbol table, detects common issues.
Walks the token stream and AST to extract:
  - Variables (name, type, scope, line)
  - Functions (name, return type, params, line)
  - Classes / structs
  - Potential warnings (unused vars, shadowed names, etc.)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Symbol:
    name:        str
    kind:        str          # variable | function | class | parameter
    type_:       str          # int, string, void, etc.
    scope:       str          # global | ClassName | functionName
    line:        int
    params:      str  = ""    # for functions
    initialized: bool = False
    used:        bool = False

@dataclass
class SemanticWarning:
    kind:    str   # unused_var | shadow | missing_return | type_mismatch
    message: str
    line:    int

# ── Type extractors ───────────────────────────────────────────────────────────

_CPP_TYPES = r"(?:int|float|double|char|bool|void|string|auto|long|short|unsigned|size_t)"
_JAVA_TYPES = r"(?:int|float|double|char|boolean|void|String|long|short|byte|Object)"

_VAR_CPP  = re.compile(
    rf"(?P<type>{_CPP_TYPES}(?:\s*[*&])?)\s+(?P<name>[A-Za-z_]\w*)"
    r"\s*(?:=\s*(?P<val>[^;,)]+))?[;,)]", re.MULTILINE
)
_VAR_JAVA = re.compile(
    rf"(?P<type>{_JAVA_TYPES}(?:\[\])?)\s+(?P<name>[A-Za-z_]\w*)"
    r"\s*(?:=\s*(?P<val>[^;]+))?;", re.MULTILINE
)

_FUNC_CPP = re.compile(
    r"(?P<ret>(?:(?:int|float|double|char|bool|void|string|auto|long|short|unsigned|\w+)\s*[*&]?\s+))"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*(?:const\s*)?\{"
)
_FUNC_JAVA = re.compile(
    r"(?:public|private|protected|static|final|\s)+"
    r"(?P<ret>\w+(?:\[\])?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*\{"
)

_CLASS_RE = re.compile(r"\b(?:class|struct)\s+(?P<name>[A-Za-z_]\w*)")

_INCLUDE_RE = re.compile(r"#\s*include\s*[<\"]([^>\"]+)[>\"]")
_IMPORT_RE  = re.compile(r"^\s*import\s+([\w.*]+);", re.MULTILINE)


def analyse(source: str, lang: str = "cpp") -> dict:
    symbols:  List[Symbol]         = []
    warnings: List[SemanticWarning] = []
    seen: Dict[str, Symbol]        = {}

    clean = re.sub(r"//[^\n]*", "", source)
    clean = re.sub(r"/\*[\s\S]*?\*/", "", clean)

    # ── Classes ──────────────────────────────────────────────────────────────
    for m in _CLASS_RE.finditer(clean):
        name = m.group("name")
        line = source[:m.start()].count("\n") + 1
        sym  = Symbol(name=name, kind="class", type_="class",
                      scope="global", line=line)
        symbols.append(sym)
        seen[name] = sym

    # ── Functions ─────────────────────────────────────────────────────────────
    pat = _FUNC_CPP if lang == "cpp" else _FUNC_JAVA
    for m in pat.finditer(clean):
        name   = m.group("name")
        ret    = m.group("ret").strip()
        params = m.group("params").strip()
        line   = source[:m.start()].count("\n") + 1
        sym    = Symbol(name=name, kind="function", type_=ret,
                        scope="global", line=line, params=params)
        symbols.append(sym)
        seen[name] = sym

        # Extract parameters as symbols
        for p in params.split(","):
            p = p.strip()
            if not p:
                continue
            parts = p.rsplit(None, 1)
            if len(parts) == 2:
                ptype, pname = parts
                pname = pname.lstrip("*&").split("=")[0].strip()
                if re.match(r"[A-Za-z_]\w*$", pname):
                    symbols.append(Symbol(name=pname, kind="parameter",
                                          type_=ptype.strip(), scope=name, line=line))

    # ── Variables ─────────────────────────────────────────────────────────────
    var_pat = _VAR_CPP if lang == "cpp" else _VAR_JAVA
    for m in var_pat.finditer(clean):
        name   = m.group("name")
        typ    = m.group("type").strip()
        val    = m.group("val")
        line   = source[:m.start()].count("\n") + 1

        if name in ("return", "if", "else", "for", "while", "class", "struct"):
            continue
        if name in {s.name for s in symbols if s.kind == "function"}:
            continue

        # Shadow check
        if name in seen:
            warnings.append(SemanticWarning(
                kind="shadow",
                message=f"'{name}' shadows an outer declaration (line {seen[name].line})",
                line=line,
            ))

        sym = Symbol(name=name, kind="variable", type_=typ,
                     scope="global", line=line, initialized=val is not None)
        symbols.append(sym)
        seen[name] = sym

    # ── Usage check ───────────────────────────────────────────────────────────
    ident_uses: Dict[str, int] = {}
    for m in re.finditer(r"\b([A-Za-z_]\w*)\b", clean):
        n = m.group(1)
        ident_uses[n] = ident_uses.get(n, 0) + 1

    for sym in symbols:
        count = ident_uses.get(sym.name, 0)
        # Declared once + possibly assigned = 1 or 2 uses; if only 1, unused
        if sym.kind == "variable" and count <= 1:
            warnings.append(SemanticWarning(
                kind="unused_var",
                message=f"Variable '{sym.name}' is declared but may not be used",
                line=sym.line,
            ))
        else:
            sym.used = True

    # ── Void function return check ────────────────────────────────────────────
    for sym in symbols:
        if sym.kind == "function" and sym.type_ not in ("void", ""):
            # Check if the function body has a return statement
            # Find function in source
            fn_pat = re.compile(
                r"\b" + re.escape(sym.name) + r"\s*\([^)]*\)\s*(?:const\s*)?\{",
                re.MULTILINE
            )
            fm = fn_pat.search(clean)
            if fm:
                bstart = fm.end() - 1
                depth  = 0
                bend   = bstart
                for i in range(bstart, len(clean)):
                    if clean[i] == "{": depth += 1
                    elif clean[i] == "}":
                        depth -= 1
                        if depth == 0:
                            bend = i
                            break
                body = clean[bstart:bend]
                if "return" not in body:
                    warnings.append(SemanticWarning(
                        kind="missing_return",
                        message=f"Function '{sym.name}' returns '{sym.type_}' but may have no return statement",
                        line=sym.line,
                    ))

    # ── Imports / includes ────────────────────────────────────────────────────
    imports = []
    if lang == "cpp":
        imports = [m.group(1) for m in _INCLUDE_RE.finditer(source)]
    else:
        imports = [m.group(1) for m in _IMPORT_RE.finditer(source)]

    return {
        "symbols":  [_sym_to_dict(s) for s in symbols],
        "warnings": [_warn_to_dict(w) for w in warnings],
        "imports":  imports,
    }


def _sym_to_dict(s: Symbol) -> dict:
    return {
        "name":        s.name,
        "kind":        s.kind,
        "type":        s.type_,
        "scope":       s.scope,
        "line":        s.line,
        "params":      s.params,
        "initialized": s.initialized,
        "used":        s.used,
    }

def _warn_to_dict(w: SemanticWarning) -> dict:
    return {"kind": w.kind, "message": w.message, "line": w.line}

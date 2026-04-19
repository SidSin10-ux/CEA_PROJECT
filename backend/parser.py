"""
backend/parser.py
==================
Builds a simplified Abstract Syntax Tree (AST) from the token stream.
Handles: functions, classes, variables, if/else, loops, return statements.
Output is a nested dict suitable for Mermaid diagram generation.
"""
from __future__ import annotations
import re
from typing import List, Optional

# ── AST node helpers ──────────────────────────────────────────────────────────

def node(kind: str, label: str = "", children: list = None, **meta) -> dict:
    n = {"kind": kind, "label": label, "children": children or []}
    n.update(meta)
    return n


# ── Regex-based structural parser ─────────────────────────────────────────────
# A full recursive-descent parser would be thousands of lines.
# This is a fast structural parser that identifies top-level constructs
# and their bodies, which is sufficient for a useful AST display.

def _strip_comments(source: str) -> str:
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return source

def _find_block_end(source: str, start: int) -> int:
    """Find the matching closing } for the { at source[start]."""
    depth = 0
    i = start
    in_str = False
    str_char = None
    while i < len(source):
        c = source[i]
        if in_str:
            if c == "\\" : i += 1
            elif c == str_char: in_str = False
        else:
            if c in ('"', "'"):
                in_str = True; str_char = c
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: return i
        i += 1
    return len(source) - 1

def _line_of(source: str, pos: int) -> int:
    return source[:pos].count("\n") + 1

# ── Pattern matchers ──────────────────────────────────────────────────────────

# Function / method
_FUNC = re.compile(
    r"(?:(?:public|private|protected|static|inline|virtual|override|final|abstract|const)\s+)*"
    r"(?:(?:\w+(?:<[^>]*>)?)\s+)+"          # return type (possibly templated)
    r"(?P<name>\w+)\s*"
    r"\((?P<params>[^)]*)\)\s*"
    r"(?:const\s*)?(?:override\s*)?(?::\s*[^{]*)?"
    r"\{"
)

# Class / struct
_CLASS = re.compile(
    r"\b(?:class|struct)\s+(?P<name>\w+)\s*"
    r"(?:(?:public|private|protected|:|\s+\w+)*\s*)?\{"
)

# Variable declaration
_VAR = re.compile(
    r"^\s*(?:(?:int|float|double|char|bool|void|auto|long|short|string|String|var"
    r"|boolean|byte|final|static|const)\s+)+"
    r"(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<val>[^;]+))?;"
    , re.MULTILINE
)

# If statement
_IF = re.compile(r"\bif\s*\((?P<cond>[^)]+)\)\s*\{")

# For loop
_FOR = re.compile(r"\bfor\s*\((?P<header>[^)]+)\)\s*\{")

# While loop
_WHILE = re.compile(r"\bwhile\s*\((?P<cond>[^)]+)\)\s*\{")

# Return
_RETURN = re.compile(r"\breturn\s+(?P<val>[^;]+);")

# Include / import
_INCLUDE = re.compile(r"#\s*include\s*[<\"]([^>\"]+)[>\"]")
_IMPORT  = re.compile(r"^\s*import\s+([\w.]+);", re.MULTILINE)


def parse(source: str, lang: str = "cpp") -> dict:
    clean = _strip_comments(source)
    root  = node("Program", "Program")

    # Includes / imports
    includes = node("Imports", "Imports / Headers")
    if lang == "cpp":
        for m in _INCLUDE.finditer(source):
            includes["children"].append(node("Include", f"#include <{m.group(1)}>"))
    else:
        for m in _IMPORT.finditer(source):
            includes["children"].append(node("Import", f"import {m.group(1)}"))
    if includes["children"]:
        root["children"].append(includes)

    # Classes
    for cm in _CLASS.finditer(clean):
        bstart = cm.end() - 1
        bend   = _find_block_end(clean, bstart)
        body   = clean[bstart+1:bend]
        cls_node = node("Class", f"class {cm.group('name')}")
        _parse_body(body, cls_node, lang, depth=1)
        root["children"].append(cls_node)

    # Top-level functions (not inside a class)
    _parse_functions_toplevel(clean, root, lang)

    # Top-level variables
    seen_vars = set()
    for vm in _VAR.finditer(clean):
        name = vm.group("name")
        if name not in seen_vars:
            label = f"var {name}"
            if vm.group("val"):
                label += f" = {vm.group('val').strip()[:20]}"
            root["children"].append(node("Variable", label, line=_line_of(clean, vm.start())))
            seen_vars.add(name)

    return root


def _parse_functions_toplevel(source: str, parent: dict, lang: str):
    """Extract top-level functions (heuristic: not inside a class body)."""
    class_ranges = []
    for cm in _CLASS.finditer(source):
        bstart = cm.end() - 1
        bend   = _find_block_end(source, bstart)
        class_ranges.append((bstart, bend))

    def in_class(pos):
        return any(s <= pos <= e for s, e in class_ranges)

    for fm in _FUNC.finditer(source):
        if in_class(fm.start()):
            continue
        name   = fm.group("name")
        params = fm.group("params").strip()
        bstart = fm.end() - 1
        bend   = _find_block_end(source, bstart)
        body   = source[bstart+1:bend]
        fn_node = node("Function", f"{name}({_short(params)})", line=_line_of(source, fm.start()))
        _parse_body(body, fn_node, lang, depth=1)
        parent["children"].append(fn_node)


def _parse_body(source: str, parent: dict, lang: str, depth: int = 0):
    if depth > 3:
        return
    added = set()

    # Variables
    for vm in _VAR.finditer(source):
        name = vm.group("name")
        if name not in added:
            label = f"var {name}"
            if vm.group("val"):
                label += f" = {_short(vm.group('val'))}"
            parent["children"].append(node("Variable", label))
            added.add(name)

    # If statements
    for im in _IF.finditer(source):
        cond = _short(im.group("cond"))
        if_node = node("If", f"if ({cond})")
        bstart = im.end() - 1
        bend   = _find_block_end(source, bstart)
        _parse_body(source[bstart+1:bend], if_node, lang, depth+1)
        parent["children"].append(if_node)

    # For loops
    for fm in _FOR.finditer(source):
        hdr = _short(fm.group("header"))
        for_node = node("For", f"for ({hdr})")
        bstart = fm.end() - 1
        bend   = _find_block_end(source, bstart)
        _parse_body(source[bstart+1:bend], for_node, lang, depth+1)
        parent["children"].append(for_node)

    # While loops
    for wm in _WHILE.finditer(source):
        cond = _short(wm.group("cond"))
        wh_node = node("While", f"while ({cond})")
        bstart = wm.end() - 1
        bend   = _find_block_end(source, bstart)
        _parse_body(source[bstart+1:bend], wh_node, lang, depth+1)
        parent["children"].append(wh_node)

    # Return statements
    for rm in _RETURN.finditer(source):
        parent["children"].append(node("Return", f"return {_short(rm.group('val'))}"))

    # Nested functions (methods)
    if depth == 0:
        _parse_functions_toplevel(source, parent, lang)


def _short(s: str, n: int = 25) -> str:
    s = s.strip().replace("\n", " ")
    return s[:n] + "…" if len(s) > n else s


# ── Mermaid generation ────────────────────────────────────────────────────────

_STYLE = {
    "Program":    "fill:#1e1e2e,stroke:#7c6af7,color:#e2e2f0",
    "Imports":    "fill:#1a1a2a,stroke:#4a9eff,color:#e2e2f0",
    "Include":    "fill:#141424,stroke:#4a9eff,color:#8888aa",
    "Import":     "fill:#141424,stroke:#4a9eff,color:#8888aa",
    "Class":      "fill:#1e2a1e,stroke:#3ddc84,color:#e2e2f0",
    "Function":   "fill:#1e1a2e,stroke:#a594f9,color:#e2e2f0",
    "Variable":   "fill:#2a1e1e,stroke:#f5a623,color:#e2e2f0",
    "If":         "fill:#2a2a1e,stroke:#febc2e,color:#e2e2f0",
    "For":        "fill:#1e2a2a,stroke:#4a9eff,color:#e2e2f0",
    "While":      "fill:#1e2a2a,stroke:#4a9eff,color:#e2e2f0",
    "Return":     "fill:#2a1a1a,stroke:#ff5f57,color:#e2e2f0",
}

def ast_to_mermaid(ast: dict, max_nodes: int = 60) -> str:
    lines  = ["graph TD"]
    styles = []
    counter = [0]

    def _id():
        counter[0] += 1
        return f"N{counter[0]}"

    def _label(n: dict) -> str:
        val = n.get("label", n.get("kind", "?"))
        val = val.replace('"', "'").replace("[", "(").replace("]", ")")
        return f'"{val}"'

    def walk(n: dict, parent_id: Optional[str] = None):
        if counter[0] >= max_nodes:
            return
        nid = _id()
        kind = n.get("kind", "Unknown")
        lines.append(f"  {nid}[{_label(n)}]")
        style = _STYLE.get(kind, "fill:#1a1a1a,stroke:#555,color:#aaa")
        styles.append(f"  style {nid} {style}")
        if parent_id:
            lines.append(f"  {parent_id} --> {nid}")
        for child in n.get("children", []):
            walk(child, nid)

    walk(ast)
    return "\n".join(lines + styles)

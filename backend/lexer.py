"""
backend/lexer.py
=================
Uses the REAL gcc/g++ compiler (via subprocess) to validate syntax and
extract token-level information, instead of a hand-rolled regex lexer.

For C++:  g++ -fsyntax-only -fno-diagnostics-color -Wall -Wextra
For Java: javac (syntax-only pass)

Token display is produced via cpp -dD (GCC preprocessor token dump)
where available.  Structural regex pass is used ONLY for the UI token
panel — all actual error detection goes through the real compiler.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Token:
    type:   str    # KEYWORD | IDENTIFIER | NUMBER | STRING | OPERATOR | PUNCTUATION | COMMENT | PREPROCESSOR
    value:  str
    line:   int
    column: int


# ── GCC-backed syntax check ───────────────────────────────────────────────────

def _gcc_syntax_check(source: str, lang: str = "cpp") -> dict:
    """
    Run the real compiler in syntax-only mode.
    Returns {ok, diagnostics:[{line,col,severity,message}], raw}
    """
    if lang == "cpp":
        compiler = shutil.which("g++")
        if not compiler:
            return {"ok": None, "diagnostics": [], "error": "g++ not found"}
    else:
        compiler = shutil.which("javac")
        if not compiler:
            return {"ok": None, "diagnostics": [], "error": "javac not found"}

    with tempfile.TemporaryDirectory(prefix="cf_lex_") as tmp:
        if lang == "java":
            m = re.search(r"public\s+class\s+(\w+)", source)
            fname = (m.group(1) if m else "Main") + ".java"
        else:
            fname = "program.cpp"

        src_path = os.path.join(tmp, fname)
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(source)

        if lang == "cpp":
            cmd = [compiler, "-std=c++17", "-fsyntax-only",
                   "-fno-diagnostics-color", "-Wall", "-Wextra", src_path]
        else:
            cmd = [compiler, "-d", tmp, src_path]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            return {"ok": False, "diagnostics": [], "error": "Syntax check timed out"}

        stderr_out = proc.stderr + proc.stdout
        ok = proc.returncode == 0
        diagnostics = _parse_gcc_output(stderr_out, lang)
        return {"ok": ok, "diagnostics": diagnostics, "raw": stderr_out}


def _parse_gcc_output(stderr: str, lang: str) -> list:
    results = []
    if lang == "cpp":
        # Allow optional drive letter (C:\...) for Windows paths
        pat = re.compile(r"^(?:[A-Za-z]:)?[^:]+:(\d+):(\d+):\s*(error|warning|note):\s*(.+)$", re.M)
    else:
        pat = re.compile(r"^(?:[A-Za-z]:)?[^:]+\.java:(\d+):\s*(error|warning):\s*(.+)$", re.M)

    seen = set()
    for m in pat.finditer(stderr):
        if lang == "cpp":
            line, col, sev, msg = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4).strip()
        else:
            line, col, sev, msg = int(m.group(1)), 0, m.group(2), m.group(3).strip()

        if sev == "note":
            continue
        key = (line, msg[:40])
        if key in seen:
            continue
        seen.add(key)
        results.append({"line": line, "column": col, "severity": sev, "message": msg})

    return results


# ── Lightweight tokeniser for UI token panel (NOT for error detection) ────────

_CPP_KEYWORDS = {
    "int","float","double","char","bool","void","string","auto","long","short",
    "unsigned","signed","const","static","extern","inline","virtual","override",
    "if","else","for","while","do","switch","case","default","break","continue",
    "return","struct","class","public","private","protected","namespace","using",
    "include","define","new","delete","nullptr","true","false","this","template",
    "typename","sizeof","typedef","enum","union",
}

_JAVA_KEYWORDS = {
    "int","float","double","char","boolean","void","String","long","short","byte",
    "if","else","for","while","do","switch","case","default","break","continue",
    "return","class","public","private","protected","static","final","abstract",
    "new","null","true","false","this","super","extends","implements","interface",
    "import","package","try","catch","finally","throw","throws","instanceof",
    "synchronized","volatile","transient","native","enum",
}

_TOKEN_PATTERNS = [
    ("COMMENT",      r"//[^\n]*|/\*[\s\S]*?\*/"),
    ("PREPROCESSOR", r"#\s*\w+[^\n]*"),
    ("STRING",       r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
    ("NUMBER",       r"\b\d+\.?\d*([eE][+-]?\d+)?[fFlLuU]*\b"),
    ("IDENTIFIER",   r"\b[A-Za-z_]\w*\b"),
    ("OPERATOR",     r"<<=|>>=|<<|>>|->|\+\+|--|&&|\|\||[+\-*/%&|^~!<>=]=?|="),
    ("PUNCTUATION",  r"[(){}\[\];,\.]"),
    ("WHITESPACE",   r"\s+"),
    ("UNKNOWN",      r"."),
]

_MASTER = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _TOKEN_PATTERNS))


def _regex_tokenise(source: str, lang: str = "cpp") -> List[Token]:
    """Structural tokeniser for UI display only — not used for error detection."""
    keywords = _CPP_KEYWORDS if lang == "cpp" else _JAVA_KEYWORDS
    tokens: List[Token] = []
    line, col = 1, 1

    for m in _MASTER.finditer(source):
        kind  = m.lastgroup
        value = m.group()

        if kind == "WHITESPACE":
            nls = value.count("\n")
            if nls:
                line += nls
                col   = len(value) - value.rfind("\n")
            else:
                col += len(value)
            continue

        if kind == "IDENTIFIER" and value in keywords:
            kind = "KEYWORD"

        tokens.append(Token(type=kind, value=value, line=line, column=col))

        nls = value.count("\n")
        if nls:
            line += nls
            col   = len(value) - value.rfind("\n")
        else:
            col += len(value)

    return tokens


# ── Public API ────────────────────────────────────────────────────────────────

def tokenise(source: str, lang: str = "cpp") -> List[Token]:
    """Return token list for UI display panel."""
    return _regex_tokenise(source, lang)


def gcc_syntax_check(source: str, lang: str = "cpp") -> dict:
    """Run g++/javac syntax-only pass. Exposed to server.py."""
    return _gcc_syntax_check(source, lang)


def tokens_to_dicts(tokens: List[Token]) -> List[dict]:
    return [
        {"type": t.type, "value": t.value, "line": t.line, "column": t.column}
        for t in tokens
    ]

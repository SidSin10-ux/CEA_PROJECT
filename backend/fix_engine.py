"""
backend/fix_engine.py — Fix suggestion engine for self-heal layer
Generates fix suggestions for each compiler error using:
  1. AI (Ollama or Claude) if available
  2. Rule-based transformers that can actually patch the broken line
"""
from __future__ import annotations
import re, json
from typing import List


# ── Rule-based fixes ──────────────────────────────────────────────────────────
# Each entry: (pattern, description, line_transformer or None)
# line_transformer: callable(original_line: str) -> fixed_line: str

def _add_semicolon(line: str) -> str:
    s = line.rstrip()
    return s + ";" if not s.endswith((";", "{", "}", ":")) else line

def _add_closing_brace(line: str) -> str:
    return line.rstrip() + "\n}"

def _fix_missing_return(line: str) -> str:
    # Find the return type from context — best we can do statically
    return line  # can't auto-fix without full context; description covers it

def _fix_endl(line: str) -> str:
    return re.sub(r"\bstd::endl\b", r"'\\n'", line)

def _fix_unordered_map(line: str) -> str:
    return re.sub(r"\bstd::map\b", "std::unordered_map", line)


_RULE_FIXES = [
    # (regex on error message, description, line_transformer)
    (
        r"expected.*[;,].*before|expected ';'",
        "Add a semicolon `;` at the end of the statement on the line above the error.",
        _add_semicolon,
    ),
    (
        r"was not declared in this scope|cannot find symbol|undeclared identifier",
        "Declare the variable before using it, e.g. `int x = 0;` above this line.",
        None,
    ),
    (
        r"invalid conversion|incompatible types|cannot convert|no viable conversion",
        "Make sure the value type matches the variable's declared type (e.g. use `static_cast<>`).",
        None,
    ),
    (
        r"expected.*\}|reached end of file|unmatched.*brace",
        "Add a closing brace `}` to close the open block.",
        None,
    ),
    (
        r"expected.*\)|missing '\)'|unmatched.*paren",
        "Add a closing parenthesis `)` to balance the open one.",
        None,
    ),
    (
        r"control reaches end of non-void function|missing return",
        "Add `return <value>;` at the end of the function so every path returns a value.",
        None,
    ),
    (
        r"undefined reference|unresolved external",
        "Either write the function body, or link the library it lives in (e.g. `-lm`).",
        None,
    ),
    (
        r"redefinition|already defined|duplicate",
        "Remove the duplicate definition. For header files, add `#pragma once` at the top.",
        None,
    ),
    (
        r"division by zero",
        "Guard the division: `if (divisor != 0) { result = a / divisor; }`",
        None,
    ),
    (
        r"array.*bound|index.*out of|subscript",
        "Make sure the index is between 0 and (array_size - 1) before accessing the array.",
        None,
    ),
    (
        r"use.*uninitialized|may be used uninitiali",
        "Initialise the variable when you declare it, e.g. `int x = 0;`",
        None,
    ),
    (
        r"no match for.*operator<<|no match for.*operator>>",
        "Make sure what you're printing has a printable type (int, string, double, etc.).",
        None,
    ),
    (
        r"too few arguments|too many arguments|no matching function",
        "Check the function definition and make sure the number and types of arguments match.",
        None,
    ),
    (
        r"cannot find.*header|no such file",
        "Add the missing `#include` at the top of the file (e.g. `#include <iostream>`).",
        None,
    ),
    (
        r"std::endl",
        "Replace `std::endl` with `'\\n'` to avoid flushing the output buffer every line.",
        _fix_endl,
    ),
]


class SuggestedFix:
    __slots__ = ("error_index", "error_raw", "description", "fixed_line",
                 "full_fixed_source", "confidence", "source")

    def __init__(self, error_index, error_raw, description,
                 fixed_line="", full_fixed_source="",
                 confidence="low", source="rules"):
        self.error_index       = error_index
        self.error_raw         = error_raw
        self.description       = description
        self.fixed_line        = fixed_line
        self.full_fixed_source = full_fixed_source
        self.confidence        = confidence
        self.source            = source

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


def _rule_fix(error: dict, idx: int, source_lines: List[str]) -> SuggestedFix:
    raw        = error.get("raw", "").lower()
    lineno     = error.get("line", 0)
    source_line = error.get("source_line", "")

    for pattern, description, transformer in _RULE_FIXES:
        if re.search(pattern, raw, re.IGNORECASE):
            fixed_line      = source_line
            full_fixed_src  = ""
            confidence      = "low"

            if transformer and source_line:
                try:
                    fixed_line = transformer(source_line)
                    if fixed_line != source_line and 0 < lineno <= len(source_lines):
                        patched = source_lines[:]
                        patched[lineno - 1] = fixed_line
                        full_fixed_src = "\n".join(patched)
                        confidence = "medium"
                except Exception:
                    pass

            return SuggestedFix(
                error_index       = idx,
                error_raw         = error.get("raw", ""),
                description       = description,
                fixed_line        = fixed_line,
                full_fixed_source = full_fixed_src,
                confidence        = confidence,
                source            = "rules",
            )

    return SuggestedFix(
        error_index = idx,
        error_raw   = error.get("raw", ""),
        description = "Review the flagged line carefully — check for typos or missing syntax.",
        fixed_line  = source_line,
        confidence  = "low",
        source      = "rules",
    )


# ── AI fix (Ollama → Claude) ──────────────────────────────────────────────────

def _build_fix_prompt(errors: List[dict], source: str, lang: str) -> str:
    lang_name   = "C++" if lang == "cpp" else "Java"
    errors_text = "\n".join(
        f"Error {i+1} (line {e.get('line','?')}): {e.get('raw','')}"
        + (f"\n  Source: `{e['source_line']}`" if e.get("source_line") else "")
        for i, e in enumerate(errors)
    )
    return (
        f"You are an expert {lang_name} self-healing compiler assistant.\n\n"
        f"Compiler errors:\n{errors_text}\n\n"
        f"Full source:\n```{lang}\n{source[:3000]}\n```\n\n"
        "Return ONLY a JSON array — one object per error — in this exact shape:\n"
        '[{"description":"what to fix and why","fixed_line":"corrected source line",'
        '"full_fixed_source":"complete corrected source if possible, else empty string"}]\n'
        "No markdown fences, no extra text."
    )


def _parse_ai_json(raw: str) -> "list | None":
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw)
    m = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        return None


def _try_ai_fixes(errors: List[dict], source: str, lang: str) -> "List[dict] | None":
    try:
        from backend.config import cfg
        prompt = _build_fix_prompt(errors, source, lang)

        # Try Ollama first (local, fast)
        try:
            import urllib.request
            payload = json.dumps({
                "model":   cfg.OLLAMA_MODEL,
                "prompt":  prompt,
                "stream":  False,
                "options": {"temperature": 0.1, "num_predict": 2000},
            }).encode()
            req = urllib.request.Request(
                f"{cfg.OLLAMA_HOST}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read())
            result = _parse_ai_json(body.get("response", ""))
            if result:
                return result
        except Exception:
            pass

        # Try Anthropic Claude
        if cfg.ANTHROPIC_API_KEY:
            try:
                import urllib.request
                payload = json.dumps({
                    "model":      "claude-sonnet-4-20250514",
                    "max_tokens": 2000,
                    "messages":   [{"role": "user", "content": prompt}],
                }).encode()
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=payload,
                    headers={
                        "Content-Type":    "application/json",
                        "x-api-key":       cfg.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read())
                result = _parse_ai_json(body["content"][0]["text"])
                if result:
                    return result
            except Exception:
                pass

    except Exception:
        pass
    return None


def generate_fixes(errors: List[dict], source: str, lang: str) -> List[dict]:
    """Generate fix suggestions. Never raises."""
    source_lines = source.splitlines()
    ai_results   = None

    try:
        ai_results = _try_ai_fixes(errors, source, lang)
    except Exception:
        pass

    suggestions = []
    for idx, error in enumerate(errors):
        if ai_results and idx < len(ai_results):
            ai = ai_results[idx]
            suggestions.append(SuggestedFix(
                error_index       = idx,
                error_raw         = error.get("raw", ""),
                description       = ai.get("description", ""),
                fixed_line        = ai.get("fixed_line", error.get("source_line", "")),
                full_fixed_source = ai.get("full_fixed_source", ""),
                confidence        = "high",
                source            = "ai",
            ))
        else:
            suggestions.append(_rule_fix(error, idx, source_lines))

    return [s.to_dict() for s in suggestions]

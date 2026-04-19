"""
backend/nlp_explainer.py
=========================
NLP-powered error explanation engine for CodeForge.

Priority chain  (tried in order, first success wins)
─────────────────────────────────────────────────────
1. Local Ollama            — if installed & running on this machine
2. Local Transformer       — pre-trained model via transformers library
                             (offline after first download, no API key needed)
3. HF Inference API        — FREE cloud API, just needs HF_TOKEN in .env
4. Anthropic Claude API    — cloud fallback if ANTHROPIC_API_KEY is set
5. Rule-based NLP          — always works, zero network, zero tokens

To enable the offline transformer (Tier 2):
    pip install transformers torch
The model (Phi-3-mini, ~2 GB) downloads automatically on first use
and is cached locally. All subsequent runs are fully offline.
"""
from __future__ import annotations
import re
import json
import urllib.request
import urllib.error
from typing import List

from backend.config import cfg


# ── Tier 5 — Rule-based NLP (always works offline) ───────────────────────────

_RULES = [
    (r"expected.*[;,].*before|expected ';'",
     "Missing Semicolon",
     "Every statement must end with `;`. You forgot one on this line.",
     "Add `;` at the end of the line above the error.",
     "Add `;` to terminate the statement before the next token."),
    (r"was not declared in this scope|cannot find symbol|undeclared identifier",
     "Unknown Name",
     "You used a variable or function name that C++/Java doesn't recognise. "
     "Either you haven't declared it, or it's spelled differently.",
     "Declare the variable first (e.g. `int x = 0;`) or check for typos. "
     "C++ is case-sensitive — `myVar` != `myvar`.",
     "Name lookup failed in current and enclosing scopes. Verify declaration, scope, and linkage."),
    (r"invalid conversion|incompatible types|cannot convert|no viable conversion",
     "Type Mismatch",
     "You're putting the wrong kind of value into a variable.",
     "Match the value type to the variable type. Use `std::string` for text, `int`/`double` for numbers.",
     "Implicit conversion rejected by the type system. Use static_cast<> or fix the declared type."),
    (r"expected.*\}|reached end of file|unmatched",
     "Missing Closing Brace `}`",
     "You opened a `{` but never closed it. Every `{` needs a matching `}`.",
     "Add `}` at the end of the unclosed block.",
     "Parser reached EOF or unexpected token while awaiting compound-statement terminator."),
    (r"expected.*\)|missing '\)'",
     "Missing Closing Parenthesis `)`",
     "You opened a `(` but never closed it with `)`. Count your parentheses.",
     "Find the opening `(` and add the missing `)` after the expression.",
     "Unbalanced parenthesis in expression or parameter list."),
    (r"too few arguments|too many arguments|no matching function|no match for call",
     "Wrong Number of Arguments",
     "You called a function with the wrong number of arguments.",
     "Look at the function definition and match the number and types of arguments.",
     "Arity mismatch at call site. No viable overload found for given argument list."),
    (r"no match for.*operator<<|no match for.*operator>>",
     "Can't Use << / >> With That Type",
     "You're trying to print a value that C++ doesn't know how to handle.",
     "Make sure what you're printing has a concrete type (int, string, double, etc.).",
     "ADL/overload resolution failed for operator<< / >>."),
    (r"undefined reference|unresolved external",
     "Missing Function Body (Linker Error)",
     "The compiler knows the function exists, but can't find its code.",
     "Write the function body, or link the library: `g++ file.cpp -lmylibrary`",
     "Undefined external symbol at link time. Symbol declared but no definition in translation unit."),
    (r"control reaches end of non-void function|missing return",
     "Function Might Not Return a Value",
     "Your function says it returns something but there's a path that never hits a `return`.",
     "Add a `return` statement at the bottom, and check all `if/else` branches.",
     "Control flow analysis: at least one path through function body has no return statement."),
    (r"redefinition|already defined|duplicate",
     "Name Defined Twice",
     "You've defined the same variable or function more than once in the same scope.",
     "Remove the duplicate definition. In headers, use `#pragma once`.",
     "ODR violation — multiple definitions in the same scope or translation unit."),
    (r"division by zero",
     "Division by Zero",
     "You're dividing by zero — this will crash your program.",
     "Add a guard: `if (divisor != 0) { result = a / divisor; }`",
     "Undefined behaviour: integer/float division by zero constant detected at compile time."),
    (r"array.*bound|index.*out of|subscript",
     "Array Index Out of Bounds",
     "You're trying to access an array element that doesn't exist.",
     "Check that your index is always between 0 and `array_size - 1`.",
     "Out-of-bounds array access — undefined behaviour."),
    (r"use.*uninitialized|may be used uninitiali",
     "Variable Used Before Being Set",
     "You declared a variable but never gave it a value before using it.",
     "Always initialise variables when you declare them: `int x = 0;`",
     "Uninitialized variable read — undefined behaviour per C++ standard."),
]


def explain_rules(errors: List[dict], lang: str = "cpp", level: str = "beginner") -> List[dict]:
    """Tier 5 — pure rule-based NLP. No network. No model. Always works."""
    result    = []
    level_idx = {"beginner": 0, "intermediate": 1, "expert": 2}.get(level, 0)
    for err in errors:
        raw     = err.get("raw", "").lower()
        matched = False
        for pattern, title, beg, mid, exp in _RULES:
            if re.search(pattern, raw, re.IGNORECASE):
                result.append({
                    "title":       title,
                    "explanation": [beg, mid, exp][level_idx],
                    "fix":         mid,
                    "fixed_line":  err.get("source_line", ""),
                })
                matched = True
                break
        if not matched:
            result.append({
                "title":       "Compiler Error",
                "explanation": f'The compiler says: "{err.get("raw", "")}"',
                "fix":         "Read the error carefully and check the flagged line for typos or missing syntax.",
                "fixed_line":  err.get("source_line", ""),
            })
    return result


# ── Shared prompt builder (cloud tiers) ───────────────────────────────────────

def _build_prompt(errors: List[dict], source: str, lang: str, level: str) -> str:
    lang_name = "C++" if lang == "cpp" else "Java"
    level_prompt = {
        "beginner":     "Explain as if to a total beginner who is frustrated. Use simple everyday words, no jargon. Be warm and encouraging. For 'explanation', give 1-2 sentences in plain English. For 'fix', give the exact characters to type or delete.",
        "intermediate": "Explain to someone who knows basic programming. Mention the concept briefly but keep it practical. For 'fix', be specific about what change to make.",
        "expert":       "Be concise and technical. Reference the language spec rule, type system behaviour, or linker mechanism. No hand-holding. For 'fix', show the corrected code fragment.",
    }.get(level, "")
    errors_text = "\n".join(
        f"Error {i+1} (line {e.get('line','?')}): {e.get('raw','')}"
        + (f"\n  Source line: `{e['source_line']}`" if e.get("source_line") else "")
        for i, e in enumerate(errors)
    )
    return (
        f"You are an expert {lang_name} compiler error explainer inside a code editor called CodeForge.\n\n"
        f"The user's code has these compiler errors:\n{errors_text}\n\n"
        f"Full source:\n```{lang}\n{source[:2000]}\n```\n\n"
        f"{level_prompt}\n\n"
        "Return ONLY a JSON array, one object per error, in order:\n"
        '[{"title":"4-6 word title","explanation":"Plain English explanation",'
        '"fix":"Specific actionable fix","fixed_line":"Corrected version of that source line"}]\n\n'
        "Return ONLY valid JSON. No markdown fences, no preamble, no commentary."
    )


def _parse_json_response(raw_text: str) -> list:
    raw_text = raw_text.strip()
    raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text)
    raw_text = re.sub(r"\n?```$",        "", raw_text)
    match = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
    if match:
        raw_text = match.group(0)
    return json.loads(raw_text)


# ── Tier 1: Local Ollama ──────────────────────────────────────────────────────

def ollama_status() -> dict:
    try:
        req = urllib.request.Request(
            f"{cfg.OLLAMA_HOST}/api/tags",
            headers={"Content-Type": "application/json"},
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            body   = json.loads(resp.read())
            models = [m["name"] for m in body.get("models", [])]
            return {"available": True,  "models": models, "model": cfg.OLLAMA_MODEL,
                    "hf_ready": cfg.hf_ready(), "hf_model": cfg.HF_MODEL}
    except Exception:
        return {"available": False, "models": [], "model": cfg.OLLAMA_MODEL,
                "hf_ready": cfg.hf_ready(), "hf_model": cfg.HF_MODEL}


def _explain_ollama(errors, source, lang, level, model=None):
    chosen  = model or cfg.OLLAMA_MODEL
    prompt  = _build_prompt(errors, source, lang, level)
    payload = json.dumps({"model": chosen, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.2, "num_predict": 1200}}).encode()
    req = urllib.request.Request(
        f"{cfg.OLLAMA_HOST}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
        return _parse_json_response(body.get("response", "")), True


# ── Tier 2: Local Transformer (offline pre-trained model) ────────────────────

def _explain_local_transformer(errors, source, lang, level):
    """
    Delegate to local_model.py. Imported here (not at module top) so that
    missing transformers/torch never crashes the rest of CodeForge.
    """
    from backend.local_model import explain_local
    return explain_local(errors, source, lang, level)


# ── Tier 3: Hugging Face Inference API ───────────────────────────────────────

HF_INFERENCE_URL      = "https://api-inference.huggingface.co/models/{model}"
HF_RECOMMENDED_MODELS = [
    ("mistralai/Mistral-7B-Instruct-v0.3",  "Mistral 7B — best quality"),
    ("HuggingFaceH4/zephyr-7b-beta",         "Zephyr 7B — great alternative"),
    ("microsoft/Phi-3-mini-4k-instruct",     "Phi-3 Mini — fastest"),
    ("google/gemma-2-2b-it",                 "Gemma 2B — lightweight"),
    ("Qwen/Qwen2.5-Coder-7B-Instruct",       "Qwen Coder — code-focused"),
]


def hf_status() -> dict:
    if not cfg.hf_ready():
        return {"ready": False, "model": cfg.HF_MODEL, "preview": "",
                "error": "No HF_TOKEN set — add it to your .env file."}
    try:
        probe = json.dumps({"inputs": "Hi", "parameters": {"max_new_tokens": 3},
                            "options": {"wait_for_model": False}}).encode()
        req = urllib.request.Request(
            HF_INFERENCE_URL.format(model=cfg.HF_MODEL), data=probe,
            headers={"Authorization": f"Bearer {cfg.HF_TOKEN}",
                     "Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
        return {"ready": True, "model": cfg.HF_MODEL,
                "preview": cfg.hf_token_preview(), "error": None}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ready": False, "model": cfg.HF_MODEL,
                    "preview": cfg.hf_token_preview(),
                    "error": "Token rejected — check your HF_TOKEN."}
        return {"ready": True, "model": cfg.HF_MODEL,
                "preview": cfg.hf_token_preview(), "error": None}
    except Exception as e:
        return {"ready": False, "model": cfg.HF_MODEL,
                "preview": cfg.hf_token_preview(), "error": str(e)}


def _explain_hf(errors, source, lang, level, model=None):
    if not cfg.hf_ready():
        raise RuntimeError("HF_TOKEN not set or invalid.")
    chosen  = model or cfg.HF_MODEL
    prompt  = _build_prompt(errors, source, lang, level)
    payload = json.dumps({
        "inputs":     prompt,
        "parameters": {"max_new_tokens": 1200, "temperature": 0.2,
                       "return_full_text": False, "do_sample": True},
        "options":    {"wait_for_model": True, "use_cache": False},
    }).encode()
    req = urllib.request.Request(
        HF_INFERENCE_URL.format(model=chosen), data=payload,
        headers={"Authorization": f"Bearer {cfg.HF_TOKEN}",
                 "Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read())
    if isinstance(body, list) and body:
        raw_text = body[0].get("generated_text", "")
    elif isinstance(body, dict):
        if "error" in body:
            raise RuntimeError(f"HF API error: {body['error']}")
        raw_text = body.get("generated_text", "")
    else:
        raise RuntimeError("Unexpected HF API response.")
    return _parse_json_response(raw_text), True


# ── Tier 4: Anthropic Claude API ─────────────────────────────────────────────

def _explain_claude(errors, source, lang, level):
    if not cfg.ANTHROPIC_API_KEY:
        raise RuntimeError("No ANTHROPIC_API_KEY set.")
    prompt  = _build_prompt(errors, source, lang, level)
    payload = json.dumps({"model": "claude-sonnet-4-20250514", "max_tokens": 1200,
                          "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=payload,
        headers={"Content-Type": "application/json", "x-api-key": cfg.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
        return _parse_json_response(body["content"][0]["text"]), True


# ── Public entry point ────────────────────────────────────────────────────────

def explain_ai(
    errors:        List[dict],
    source:        str,
    lang:          str = "cpp",
    level:         str = "beginner",
    prefer_ollama: bool = True,
    ollama_model:  str | None = None,
    hf_model:      str | None = None,
) -> tuple[List[dict], bool]:
    """
    Try each explanation tier in order. Returns first success.

    Priority:
        1. Ollama              (local, fastest if installed)
        2. Local Transformer   (offline after first model download)  ← NEW
        3. HF Inference API    (cloud, free, needs HF_TOKEN)
        4. Anthropic Claude    (cloud, needs ANTHROPIC_API_KEY)
        5. Rule-based NLP      (always works, no AI)
    """

    # Tier 1 — Ollama
    if prefer_ollama:
        try:
            return _explain_ollama(errors, source, lang, level, model=ollama_model)
        except Exception:
            pass

    # Tier 2 — Local Transformer (offline pre-trained model)
    if cfg.local_model_enabled:
        try:
            return _explain_local_transformer(errors, source, lang, level)
        except Exception:
            pass

    # Tier 3 — HF Inference API
    try:
        return _explain_hf(errors, source, lang, level, model=hf_model)
    except Exception:
        pass

    # Tier 4 — Anthropic Claude
    try:
        return _explain_claude(errors, source, lang, level)
    except Exception:
        pass

    # Tier 5 — Rule-based NLP (guaranteed fallback)
    return explain_rules(errors, lang, level), False

"""
backend/self_healer.py — Self-Healing orchestrator
Always active when called. Produces explanations + fix suggestions for
every compiler error using the fix_engine and error_repair modules.
"""
from __future__ import annotations
import sys


def heal(result: dict, source: str, lang: str) -> "dict | None":
    """
    Return self_heal metadata dict, or None if compilation succeeded.
    Never raises — all failures are caught and logged.
    """
    if result.get("success", True):
        return None

    errors: list = result.get("errors", [])
    if not errors:
        return None

    suggestions  = []
    explanations = []

    try:
        from backend.fix_engine import generate_fixes
        suggestions = generate_fixes(errors=errors, source=source, lang=lang)
    except Exception as exc:
        _log(f"fix_engine failed: {exc}")

    try:
        from backend.error_repair import explain_errors
        explanations = explain_errors(errors=errors, source=source, lang=lang)
    except Exception as exc:
        _log(f"error_repair failed: {exc}")

    # Guarantee one entry per error so navigation never breaks
    for i in range(len(suggestions), len(errors)):
        suggestions.append({
            "error_index":       i,
            "error_raw":         errors[i].get("raw", ""),
            "description":       "Review the flagged line carefully.",
            "fixed_line":        errors[i].get("source_line", ""),
            "full_fixed_source": "",
            "confidence":        "low",
            "source":            "rules",
        })
    for i in range(len(explanations), len(errors)):
        explanations.append({
            "title":       "Compiler Error",
            "explanation": errors[i].get("raw", "Unknown error"),
            "fix":         "Check the flagged line for typos or missing syntax.",
            "fixed_line":  errors[i].get("source_line", ""),
            "source":      "self_heal_fallback",
        })

    return {
        "enabled":      True,
        "error_count":  len(errors),
        "explanations": explanations,
        "suggestions":  suggestions,
        "applied":      False,
    }


def _log(msg: str) -> None:
    try:
        print(f"[self_healer] {msg}", file=sys.stderr)
    except Exception:
        pass

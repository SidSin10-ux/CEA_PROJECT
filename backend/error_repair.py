# backend/error_repair.py — Error explanations for self-heal panel
# BEGIN SELF-HEAL ADDITION
from __future__ import annotations
from typing import List


def explain_errors(errors: List[dict], source: str, lang: str) -> List[dict]:
    """Produce explanations for self-heal panel by delegating to existing nlp_explainer."""
    try:
        from backend.nlp_explainer import explain_ai, explain_rules

        try:
            explanations, _ = explain_ai(errors=errors, source=source, lang=lang,
                                         level="beginner", prefer_ollama=True)
        except Exception:
            explanations = explain_rules(errors, lang, "beginner")

        rule_fallbacks = explain_rules(errors, lang, "beginner")
        final: List[dict] = []
        for i, exp in enumerate(explanations):
            fb = rule_fallbacks[i] if i < len(rule_fallbacks) else {}
            entry = exp if exp and (exp.get("explanation") or exp.get("fix")) else fb
            entry["source"] = "self_heal"
            final.append(entry)
        for i in range(len(final), len(errors)):
            rb = rule_fallbacks[i] if i < len(rule_fallbacks) else {
                "title": "Compiler Error",
                "explanation": errors[i].get("raw", ""),
                "fix": "Check the flagged line.",
                "fixed_line": errors[i].get("source_line", ""),
            }
            rb["source"] = "self_heal"
            final.append(rb)
        return final

    except Exception:
        return [{"title": "Compiler Error", "explanation": e.get("raw", ""),
                 "fix": "Review the flagged line.", "fixed_line": e.get("source_line", ""),
                 "source": "self_heal_fallback"} for e in errors]
# END SELF-HEAL ADDITION

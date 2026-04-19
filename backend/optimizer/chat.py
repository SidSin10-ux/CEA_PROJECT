"""
backend/optimizer/chat.py
==========================
AI code optimization chatbot.

Uses the same priority chain as nlp_explainer:
  1. Local Ollama (if running)
  2. Hugging Face Inference API (needs HF_TOKEN in .env)
  3. Anthropic Claude API (needs ANTHROPIC_API_KEY in .env)
  4. Rule-based fallback (always works offline)

The `chat` function is imported by server.py as:
    from backend.optimizer.chat import chat as optimizer_chat
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
from typing import List, Optional

from backend.config import cfg


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are an expert code optimization assistant inside CodeForge, a smart IDE. "
    "Your job is to help users make their C++ and Java code faster, cleaner, and more efficient. "
    "When given code, suggest concrete improvements: algorithmic optimizations, memory usage, "
    "readability, best practices, and performance tips. "
    "Be concise, practical, and friendly. When showing code, use markdown code fences."
)


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_messages(message: str, code: Optional[str], history: List[dict]) -> List[dict]:
    """
    Returns a messages list compatible with Claude / chat-style APIs.
    history format: [{"role": "user"|"assistant", "content": str}, ...]
    """
    messages = []

    # Include conversation history (max last 10 turns to stay within token limits)
    for turn in history[-10:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Build the current user message
    user_content = message
    if code and code.strip():
        user_content = f"{message}\n\n```\n{code.strip()[:8000]}\n```"

    messages.append({"role": "user", "content": user_content})
    return messages


def _build_ollama_prompt(message: str, code: Optional[str], history: List[dict]) -> str:
    """Build a flat text prompt for Ollama (non-chat models)."""
    parts = [_SYSTEM_PROMPT, ""]
    for turn in history[-6:]:
        role = turn.get("role", "user").capitalize()
        parts.append(f"{role}: {turn.get('content', '')}")
    user_msg = message
    if code and code.strip():
        user_msg = f"{message}\n\nCode:\n```\n{code.strip()[:8000]}\n```"
    parts.append(f"User: {user_msg}")
    parts.append("Assistant:")
    return "\n".join(parts)


# ── Rule-based fallback ────────────────────────────────────────────────────────

_OPTIMIZATION_TIPS = [
    (r"\bvector\b",         "Consider reserving vector capacity with `.reserve()` if the final size is known."),
    (r"\bstring\b",         "Prefer `std::string_view` for read-only string parameters to avoid copies."),
    (r"for\s*\(",           "Check if you can replace raw loops with STL algorithms (`std::sort`, `std::find`, etc.)."),
    (r"\bsort\b",           "Ensure you're using `std::sort` (O(n log n)) rather than a manual bubble/selection sort."),
    (r"\brecursi",          "Deep recursion can cause stack overflows. Consider iterative or tail-recursive alternatives."),
    (r"\bnew\b",            "Prefer smart pointers (`std::unique_ptr`, `std::shared_ptr`) over raw `new`/`delete`."),
    (r"\bcout\b",           "For performance-critical output, use `printf` or disable sync: `ios::sync_with_stdio(false)`."),
    (r"\bmap\b",            "If order doesn't matter, `std::unordered_map` is O(1) average vs `std::map`'s O(log n)."),
    (r"\blist\b",           "Prefer `std::vector` over `std::list` for cache locality unless you need O(1) insert/remove."),
]


def _rule_based_reply(message: str, code: Optional[str]) -> str:
    tips = []
    if code:
        for pattern, tip in _OPTIMIZATION_TIPS:
            if re.search(pattern, code, re.IGNORECASE):
                tips.append(f"- {tip}")

    if tips:
        reply = (
            "Here are some optimization suggestions based on your code:\n\n"
            + "\n".join(tips)
            + "\n\n💡 For deeper AI-powered analysis, add your `HF_TOKEN` (free) to `.env`."
        )
    else:
        reply = (
            "**Code Optimization Tips (offline mode):**\n\n"
            "- Prefer `std::vector` over arrays for safer, more flexible storage.\n"
            "- Use `const` references for large objects passed to functions.\n"
            "- Avoid unnecessary copies — move semantics (`std::move`) can help.\n"
            "- Profile before optimizing: use `gprof` or `valgrind --tool=callgrind`.\n"
            "- Check algorithmic complexity first — O(n²) → O(n log n) beats micro-opts.\n\n"
            "💡 Connect an AI backend (HF_TOKEN or ANTHROPIC_API_KEY in `.env`) for personalized advice."
        )
    return reply


# ── 1. Ollama ─────────────────────────────────────────────────────────────────

def _chat_ollama(message: str, code: Optional[str], history: List[dict]) -> str:
    prompt = _build_ollama_prompt(message, code, history)
    payload = json.dumps({
        "model":   cfg.OLLAMA_MODEL,
        "prompt":  prompt,
        "stream":  False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }).encode()
    req = urllib.request.Request(
        f"{cfg.OLLAMA_HOST}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    return body.get("response", "").strip()


# ── 2. Hugging Face Inference API ─────────────────────────────────────────────

def _chat_hf(message: str, code: Optional[str], history: List[dict]) -> str:
    if not cfg.hf_ready():
        raise RuntimeError("HF_TOKEN not set.")
    prompt = _build_ollama_prompt(message, code, history)  # flat prompt works for HF too
    payload = json.dumps({
        "inputs":     prompt,
        "parameters": {
            "max_new_tokens":   1024,
            "temperature":      0.3,
            "return_full_text": False,
            "do_sample":        True,
        },
        "options": {"wait_for_model": True, "use_cache": False},
    }).encode()
    req = urllib.request.Request(
        f"https://api-inference.huggingface.co/models/{cfg.HF_MODEL}",
        data=payload,
        headers={"Authorization": f"Bearer {cfg.HF_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read())
    if isinstance(body, list) and body:
        return body[0].get("generated_text", "").strip()
    if isinstance(body, dict):
        if "error" in body:
            raise RuntimeError(f"HF API error: {body['error']}")
        return body.get("generated_text", "").strip()
    raise RuntimeError("Unexpected HF API response.")


# ── 3. Anthropic Claude API ───────────────────────────────────────────────────

def _chat_claude(message: str, code: Optional[str], history: List[dict]) -> str:
    if not cfg.ANTHROPIC_API_KEY:
        raise RuntimeError("No ANTHROPIC_API_KEY set.")
    messages = _build_messages(message, code, history)
    payload = json.dumps({
        "model":      "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system":     _SYSTEM_PROMPT,
        "messages":   messages,
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         cfg.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    return body["content"][0]["text"].strip()


# ── Public entry point ────────────────────────────────────────────────────────

def chat(
    message:  str,
    code:     Optional[str] = None,
    history:  Optional[List[dict]] = None,
) -> dict:
    """
    Main chat function called by server.py.

    Returns:
        { "reply": str, "ai": bool, "error": str | None }
    """
    if history is None:
        history = []

    # 1. Try Ollama (local, fast, free)
    try:
        reply = _chat_ollama(message, code, history)
        if reply:
            return {"reply": reply, "ai": True, "error": None}
    except Exception:
        pass

    # 2. Try HF Inference API (free cloud, just needs HF_TOKEN)
    try:
        reply = _chat_hf(message, code, history)
        if reply:
            return {"reply": reply, "ai": True, "error": None}
    except Exception:
        pass

    # 3. Try Anthropic Claude (needs ANTHROPIC_API_KEY)
    try:
        reply = _chat_claude(message, code, history)
        if reply:
            return {"reply": reply, "ai": True, "error": None}
    except Exception:
        pass

    # 4. Rule-based offline fallback
    reply = _rule_based_reply(message, code)
    return {"reply": reply, "ai": False, "error": None}

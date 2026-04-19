"""
backend/local_model.py
=======================
Offline, pre-trained transformer engine for CodeForge.

This module downloads a small instruction-tuned language model once
and then runs it entirely on your local machine — no internet, no API
key, no GPU required after the first download.

Model choice: microsoft/Phi-3-mini-4k-instruct
  • ~2.3 GB on disk (4-bit quantised with bitsandbytes → ~800 MB)
  • Runs on CPU in ~5-15 seconds per explanation
  • Strong code and error understanding out of the box
  • Free, open weights, Apache-2.0 licence

Download happens automatically on first use (one-time, needs internet).
After that the model is cached in:
    ~/.cache/huggingface/hub/   (Linux/Mac)
    C:\\Users\\<you>\\.cache\\huggingface\\hub\\   (Windows)

You can also pre-download manually and point LOCAL_MODEL_PATH in .env
to a local folder — useful for fully air-gapped environments.

How it fits in the priority chain (nlp_explainer.py):
    1. Ollama              — local, fastest if installed
    2. LOCAL TRANSFORMER   — this file  ← new tier
    3. HF Inference API    — cloud, needs internet + HF_TOKEN
    4. Anthropic Claude    — cloud, needs internet + key
    5. Rule-based NLP      — regex fallback, always works

Usage (called automatically by nlp_explainer.py):
    from backend.local_model import explain_local, local_model_status
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Default model — small, fast, excellent at code and instruction following.
# Override by setting LOCAL_MODEL_NAME in your .env file.
DEFAULT_MODEL_NAME = "microsoft/Phi-3-mini-4k-instruct"

# If you have downloaded the model manually to a local folder, set this in .env
# to an absolute path and the model will be loaded from disk (no internet at all).
# Example:  LOCAL_MODEL_PATH=/home/user/models/phi3-mini
DEFAULT_MODEL_PATH = ""

# Maximum new tokens to generate per explanation response.
MAX_NEW_TOKENS = 900

# Temperature — lower = more focused/deterministic answers.
TEMPERATURE = 0.2

# ── Module-level singleton — model is loaded once and reused ──────────────────

_pipeline   = None          # the transformers pipeline object
_load_lock  = threading.Lock()
_load_error: Optional[str] = None   # stores the error message if loading failed


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_model_id() -> str:
    """Return model name from env or default."""
    return os.environ.get("LOCAL_MODEL_NAME", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME


def _get_model_path() -> str:
    """Return local path override from env, or empty string (use HF hub)."""
    return os.environ.get("LOCAL_MODEL_PATH", DEFAULT_MODEL_PATH).strip()


def _load_pipeline():
    """
    Load the transformers pipeline into the module-level singleton.
    Called lazily on first use, protected by a lock so it only runs once
    even if multiple Flask worker threads call it simultaneously.
    """
    global _pipeline, _load_error

    # Already loaded or already failed — return immediately.
    if _pipeline is not None or _load_error is not None:
        return

    with _load_lock:
        # Double-checked locking — another thread may have loaded it while
        # we were waiting for the lock.
        if _pipeline is not None or _load_error is not None:
            return

        try:
            # Import here so that if transformers/torch are not installed the
            # rest of CodeForge still works — the module just won't be usable.
            from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM
            import torch

            model_source = _get_model_path() or _get_model_id()
            logger.info(f"[local_model] Loading model from: {model_source}")

            # Determine the best available device.
            # MPS = Apple Silicon GPU, cuda = NVIDIA GPU, cpu = fallback.
            if torch.cuda.is_available():
                device = "cuda"
                logger.info("[local_model] Using NVIDIA CUDA GPU")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
                logger.info("[local_model] Using Apple MPS (Metal) GPU")
            else:
                device = "cpu"
                logger.info("[local_model] Using CPU — inference will be slower")

            # Trust remote code is required for Phi-3 custom attention layers.
            # For other models you may set this to False.
            trust_remote = True

            # Load tokenizer
            tokenizer = AutoTokenizer.from_pretrained(
                model_source,
                trust_remote_code=trust_remote,
            )

            # Load model — use float16 on GPU, float32 on CPU for compatibility.
            dtype = "auto" if device in ("cuda", "mps") else None

            model = AutoModelForCausalLM.from_pretrained(
                model_source,
                trust_remote_code=trust_remote,
                torch_dtype=dtype,
                device_map=device if device != "cpu" else None,
                low_cpu_mem_usage=True,
            )

            # Build a text-generation pipeline for convenience.
            _pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                device=0 if device == "cuda" else (device if device == "mps" else -1),
                torch_dtype=dtype,
            )

            logger.info(f"[local_model] Model loaded successfully on {device}")

        except ImportError as exc:
            _load_error = (
                "transformers and/or torch are not installed. "
                "Run:  pip install transformers torch  to enable offline AI explanations. "
                f"Original error: {exc}"
            )
            logger.warning(f"[local_model] {_load_error}")

        except Exception as exc:
            _load_error = f"Failed to load local model: {exc}"
            logger.error(f"[local_model] {_load_error}", exc_info=True)


def _build_phi3_prompt(errors: list, source: str, lang: str, level: str) -> str:
    """
    Build a Phi-3 chat-formatted prompt.

    Phi-3 uses a special chat template:
        <|system|>...<|end|>
        <|user|>...<|end|>
        <|assistant|>

    Other models (TinyLlama, Mistral, etc.) use [INST]...[/INST].
    We detect which format to use based on the model name.
    """
    model_id = _get_model_id().lower()

    lang_name  = "C++" if lang == "cpp" else "Java"
    level_note = {
        "beginner":     "Use simple everyday language. Be encouraging. No jargon.",
        "intermediate": "Be practical and specific. Mention the relevant concept briefly.",
        "expert":       "Be concise and technical. Reference language spec behaviour.",
    }.get(level, "Use simple everyday language.")

    errors_block = "\n".join(
        f"Error {i+1} (line {e.get('line','?')}): {e.get('raw', '')}"
        + (f"\n  Source: `{e['source_line']}`" if e.get("source_line") else "")
        for i, e in enumerate(errors)
    )

    instruction = (
        f"You are a helpful {lang_name} compiler error explainer inside CodeForge IDE.\n"
        f"{level_note}\n\n"
        f"Compiler errors:\n{errors_block}\n\n"
        f"Source code:\n```{lang}\n{source[:1500]}\n```\n\n"
        "Return ONLY a valid JSON array — one object per error — like this:\n"
        '[{"title":"Short title","explanation":"Plain English explanation",'
        '"fix":"Specific fix instruction","fixed_line":"Corrected source line"}]\n\n'
        "No markdown fences. No preamble. Just the JSON array."
    )

    # Phi-3 family chat format
    if "phi" in model_id and "3" in model_id:
        return (
            f"<|system|>\nYou are a helpful coding assistant.<|end|>\n"
            f"<|user|>\n{instruction}<|end|>\n"
            f"<|assistant|>\n"
        )

    # Mistral / Zephyr / LLaMA-2 instruct format
    if any(k in model_id for k in ("mistral", "zephyr", "llama", "tinyllama")):
        return f"[INST] {instruction} [/INST]"

    # Generic fallback — works for most instruction-tuned models
    return f"### Instruction:\n{instruction}\n\n### Response:\n"


def _parse_json_from_text(raw: str) -> list:
    """
    Extract and parse a JSON array from the model output.
    Models sometimes wrap it in markdown fences or add extra commentary.
    """
    # Strip common markdown fences
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
    raw = raw.replace("```", "").strip()

    # Try to find the first [...] block
    match = re.search(r"\[\s*\{.*?\}\s*\]", raw, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    # Last resort — parse whatever is there
    return json.loads(raw)


# ── Public API ────────────────────────────────────────────────────────────────

def local_model_status() -> dict:
    """
    Return a status dict describing the current state of the local model.
    Called by the /api/local-model-status route in server.py.

    Returns:
        {
            "available":   bool,   # True if model is loaded and ready
            "model":       str,    # model name/path being used
            "device":      str,    # "cuda" | "mps" | "cpu" | "not loaded"
            "loaded":      bool,   # True if pipeline object exists
            "error":       str,    # error message if loading failed, else ""
            "install_cmd": str,    # pip command to install deps if missing
        }
    """
    model_source = _get_model_path() or _get_model_id()

    if _pipeline is not None:
        # Detect which device the model is sitting on
        try:
            device_str = str(next(_pipeline.model.parameters()).device)
        except Exception:
            device_str = "unknown"

        return {
            "available":   True,
            "model":       model_source,
            "device":      device_str,
            "loaded":      True,
            "error":       "",
            "install_cmd": "",
        }

    if _load_error:
        needs_install = "not installed" in _load_error
        return {
            "available":   False,
            "model":       model_source,
            "device":      "not loaded",
            "loaded":      False,
            "error":       _load_error,
            "install_cmd": "pip install transformers torch" if needs_install else "",
        }

    # Not yet attempted
    return {
        "available":   False,
        "model":       model_source,
        "device":      "not loaded",
        "loaded":      False,
        "error":       "Model not yet initialised — it loads on first use.",
        "install_cmd": "",
    }


def is_available() -> bool:
    """
    Quick check: is the local model loaded and ready to use?
    Does NOT trigger loading — use warmup_model() for that.
    """
    return _pipeline is not None


def warmup_model() -> bool:
    """
    Explicitly trigger model loading. Call this from server startup
    (see server.py) so the first real request is not slow.
    Returns True if the model loaded successfully, False otherwise.
    """
    _load_pipeline()
    return _pipeline is not None


def explain_local(
    errors: list,
    source: str,
    lang:   str = "cpp",
    level:  str = "beginner",
) -> tuple[list, bool]:
    """
    Generate error explanations using the local pre-trained transformer.

    This is Tier 2 in the priority chain (after Ollama, before HF API).
    The model is loaded lazily on first call and kept in memory after that.

    Args:
        errors:  list of error dicts from compiler.py / lexer.py
        source:  the full source code string
        lang:    "cpp" or "java"
        level:   "beginner" | "intermediate" | "expert"

    Returns:
        (explanations, True)  — list of explanation dicts, ai_used=True

    Raises:
        RuntimeError  — if model could not be loaded or inference failed.
                        The caller (nlp_explainer.py) catches this and falls
                        through to the next tier.
    """
    # Lazy load — safe to call multiple times
    _load_pipeline()

    if _load_error:
        raise RuntimeError(_load_error)

    if _pipeline is None:
        raise RuntimeError("Local model pipeline failed to initialise.")

    prompt = _build_phi3_prompt(errors, source, lang, level)

    outputs = _pipeline(
        prompt,
        max_new_tokens=MAX_NEW_TOKENS,
        temperature=TEMPERATURE,
        do_sample=True,
        pad_token_id=_pipeline.tokenizer.eos_token_id,
        return_full_text=False,   # return only the generated part, not the prompt
    )

    generated_text = outputs[0]["generated_text"]
    explanations   = _parse_json_from_text(generated_text)

    # Validate — must be a list with at least one explanation dict
    if not isinstance(explanations, list) or not explanations:
        raise RuntimeError("Local model returned an empty or invalid response.")

    # Ensure every item has the required keys with sensible defaults
    normalised = []
    for item in explanations:
        if not isinstance(item, dict):
            continue
        normalised.append({
            "title":       item.get("title",       "Compiler Error"),
            "explanation": item.get("explanation", ""),
            "fix":         item.get("fix",         "Check the flagged line carefully."),
            "fixed_line":  item.get("fixed_line",  ""),
        })

    if not normalised:
        raise RuntimeError("Local model returned no valid explanation objects.")

    return normalised, True

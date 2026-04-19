"""
backend/config.py
==================
Central configuration loader for CodeForge.

Loads from (in priority order):
  1. Real environment variables already set in the shell
  2. .env file in the project root

Usage anywhere in the backend:
    from backend.config import cfg
    token = cfg.HF_TOKEN
"""
from __future__ import annotations
import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Minimal .env parser — handles KEY=value lines, ignores comments."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# Load .env from project root (parent of backend/)
_ENV_PATH = Path(__file__).parent.parent / ".env"
_load_env_file(_ENV_PATH)


class _Config:

    # ── Hugging Face ──────────────────────────────────────────────────────────
    @property
    def HF_TOKEN(self) -> str:
        return os.environ.get("HF_TOKEN", "").strip()

    @property
    def HF_MODEL(self) -> str:
        return os.environ.get(
            "HF_MODEL",
            "mistralai/Mistral-7B-Instruct-v0.3"
        ).strip()

    def hf_ready(self) -> bool:
        t = self.HF_TOKEN
        return bool(t and t.startswith("hf_") and len(t) > 10)

    def hf_token_preview(self) -> str:
        t = self.HF_TOKEN
        return (t[:10] + "...") if self.hf_ready() else ""

    # ── Anthropic ─────────────────────────────────────────────────────────────
    @property
    def ANTHROPIC_API_KEY(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "").strip()

    # ── Ollama (local, optional) ──────────────────────────────────────────────
    @property
    def OLLAMA_HOST(self) -> str:
        return os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip()

    @property
    def OLLAMA_MODEL(self) -> str:
        return os.environ.get("OLLAMA_MODEL", "llama3").strip()

    # ── Local Transformer (offline pre-trained model) — NEW ──────────────────
    @property
    def LOCAL_MODEL_NAME(self) -> str:
        """
        HuggingFace model ID or local folder path for the offline transformer.
        Default: microsoft/Phi-3-mini-4k-instruct (small, fast, great at code).
        Override in .env:  LOCAL_MODEL_NAME=TinyLlama/TinyLlama-1.1B-Chat-v1.0
        """
        return os.environ.get(
            "LOCAL_MODEL_NAME",
            "microsoft/Phi-3-mini-4k-instruct"
        ).strip()

    @property
    def LOCAL_MODEL_PATH(self) -> str:
        """
        Optional absolute path to a pre-downloaded model folder.
        If set, the model is loaded from disk with zero internet access.
        Leave blank to use the HuggingFace Hub cache (downloads on first use).
        Example in .env:  LOCAL_MODEL_PATH=/home/user/models/phi3-mini
        """
        return os.environ.get("LOCAL_MODEL_PATH", "").strip()

    @property
    def local_model_enabled(self) -> bool:
        """
        True when the local transformer tier should be attempted.
        Set LOCAL_MODEL_ENABLED=false in .env to disable it entirely
        (e.g. on machines where you know transformers is not installed
        and want to skip the import attempt without waiting for it to fail).
        Defaults to True so the tier is always tried automatically.
        """
        val = os.environ.get("LOCAL_MODEL_ENABLED", "true").strip().lower()
        return val not in ("false", "0", "no", "off")

    # ── Runtime token/model save helpers ─────────────────────────────────────
    def save_hf_token(self, token: str) -> tuple[bool, str]:
        """Write a new HF token into .env without restarting the server."""
        token = token.strip()
        if not token:
            return False, "Token cannot be empty."
        if not token.startswith("hf_"):
            return False, "Invalid — Hugging Face tokens start with 'hf_'."
        try:
            lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() \
                    if _ENV_PATH.exists() else []
            updated, new_lines = False, []
            for line in lines:
                if line.strip().startswith("HF_TOKEN=") and not line.strip().startswith("#"):
                    new_lines.append(f"HF_TOKEN={token}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"HF_TOKEN={token}")
            _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.environ["HF_TOKEN"] = token
            return True, "Token saved — active immediately, no restart needed."
        except Exception as e:
            return False, f"Could not write .env: {e}"

    def save_hf_model(self, model: str) -> tuple[bool, str]:
        """Write a new HF model name into .env."""
        model = model.strip()
        if not model:
            return False, "Model name cannot be empty."
        try:
            lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() \
                    if _ENV_PATH.exists() else []
            updated, new_lines = False, []
            for line in lines:
                if line.strip().startswith("HF_MODEL=") and not line.strip().startswith("#"):
                    new_lines.append(f"HF_MODEL={model}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"HF_MODEL={model}")
            _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.environ["HF_MODEL"] = model
            return True, f"Model set to {model}."
        except Exception as e:
            return False, f"Could not write .env: {e}"


    # BEGIN SELF-HEAL ADDITION
    # ── Self-Healing Assistant (optional, disabled by default) ─────────────────
    @property
    def SELF_HEAL_ENABLED(self) -> bool:
        """
        Master toggle for the self-healing compiler assistant.
        Default: False  →  project behaves exactly as before.
        To enable: set  SELF_HEAL_ENABLED=true  in your .env file,
        or set it programmatically before starting the server.
        """
        val = os.environ.get("SELF_HEAL_ENABLED", "false").strip().lower()
        return val in ("true", "1", "yes", "on")
    # END SELF-HEAL ADDITION


cfg = _Config()

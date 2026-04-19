"""
server.py
==========
CodeForge Enhanced — main Flask server.

Original routes (unchanged)
────────────────────────────
  GET  /                       → IDE frontend
  POST /api/compile            → compile + error parse
  POST /api/explain            → AI / NLP error explanation
  POST /api/analyse            → lexer + parser + semantic analysis
  GET  /api/error-ref          → static error reference database
  GET  /api/hf-status          → Hugging Face token + model status
  POST /api/hf-settings        → save HF token / model to .env
  GET  /api/history            → all compilation snapshots
  GET  /api/history/<id>       → single snapshot with full source
  GET  /api/history/diff/a/b   → semantic diff between two snapshots
  POST /api/history/clear      → wipe history

New routes (AI Optimizer + Green Compiler)
───────────────────────────────────────────
  POST /api/optimizer/chat     → AI code optimization chatbot (Claude claude-sonnet-4-6)

  POST /api/green/profile      → full green profile (RAPL + Carbon + Pinpoint)
  GET  /api/green/chart        → energy visualization time-series data
  GET  /api/green/summary      → aggregate energy stats across all runs
  POST /api/green/clear        → reset energy history
"""
import os, sys, time
from functools import wraps
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify, send_from_directory, abort

# ── Original backend modules ──────────────────────────────────────────────────
from backend.compiler      import compile_cpp, compile_java, parse_errors
from backend.lexer         import tokenise, tokens_to_dicts, gcc_syntax_check
from backend.parser        import parse as parse_ast, ast_to_mermaid
from backend.semantic      import analyse
from backend.nlp_explainer import (
    explain_ai, explain_rules, ollama_status, hf_status, HF_RECOMMENDED_MODELS
)
from backend.config        import cfg
from backend.local_model   import local_model_status, warmup_model
from backend               import history as hist

# ── New feature modules ───────────────────────────────────────────────────────
from backend.optimizer.chat   import chat as optimizer_chat
from backend.green.rapl       import measure as rapl_measure, to_dict as rapl_to_dict
from backend.green.carbon     import estimate as carbon_estimate, to_dict as carbon_to_dict
from backend.green.pinpoint   import analyse as pinpoint_analyse, to_dict as hotspot_to_dict
from backend.green.energy_viz import (
    record as viz_record,
    get_chart_data,
    summary as viz_summary,
    clear as viz_clear,
)

app = Flask(__name__, static_folder="static")

# ── Security: max request size (2 MB) ────────────────────────────────────────
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB hard limit

# ── Security: safe response headers ──────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "SAMEORIGIN"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    return response

# ── Security: simple in-memory rate limiter ───────────────────────────────────
_rate_buckets = defaultdict(list)
_RATE_LIMIT    = 30   # max requests
_RATE_WINDOW   = 60   # per N seconds

def rate_limit(f):
    """Decorator: 30 compile/analyse requests per IP per minute."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip  = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        now = time.time()
        hits = _rate_buckets[ip]
        # Drop timestamps older than the window
        _rate_buckets[ip] = [t for t in hits if now - t < _RATE_WINDOW]
        if len(_rate_buckets[ip]) >= _RATE_LIMIT:
            return jsonify({
                "error": "rate_limit",
                "message": f"Too many requests — max {_RATE_LIMIT} per {_RATE_WINDOW}s. Please slow down."
            }), 429
        _rate_buckets[ip].append(now)
        return f(*args, **kwargs)
    return wrapper

# ── Security: input validation helpers ───────────────────────────────────────
MAX_CODE_CHARS = 50_000

def validate_code(source: str):
    """Return (ok, error_message). Checks size and basic sanity."""
    if not isinstance(source, str):
        return False, "Code must be a string."
    if len(source) > MAX_CODE_CHARS:
        return False, f"Code too large ({len(source):,} chars). Max is {MAX_CODE_CHARS:,}."
    return True, None

def validate_lang(lang: str):
    if lang not in ("cpp", "java"):
        return False, "Invalid language. Use 'cpp' or 'java'."
    return True, None


# ══════════════════════════════════════════════════════════════════════════════
# FRONTEND
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL ROUTES (preserved exactly)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/local-model-status")
def local_model_status_route():
    """
    Report the current state of the offline local transformer model (Tier 2).
    Returns: { available, model, device, loaded, error, install_cmd }
    """
    return jsonify(local_model_status())


@app.route("/api/local-model-warmup", methods=["POST"])
def local_model_warmup_route():
    """
    Trigger model loading explicitly (e.g. from a settings panel).
    Loading happens in the request thread so the response is delayed
    until the model is ready (~10-30 s on first load).
    Returns: { ok, loaded, model, device, error }
    """
    success = warmup_model()
    status  = local_model_status()
    return jsonify({
        "ok":     success,
        "loaded": status["loaded"],
        "model":  status["model"],
        "device": status["device"],
        "error":  status["error"],
    }), (200 if success else 503)


@app.route("/api/ollama-status")
def ollama_status_route():
    return jsonify(ollama_status())


@app.route("/api/hf-status")
def hf_status_route():
    status = hf_status()
    status["recommended_models"] = HF_RECOMMENDED_MODELS
    return jsonify(status)


@app.route("/api/hf-settings", methods=["POST"])
def hf_settings_route():
    data  = request.get_json(force=True)
    token = data.get("token", "").strip()
    model = data.get("model", "").strip()
    results = {}

    if token:
        ok, msg = cfg.save_hf_token(token)
        results["token"] = {"ok": ok, "message": msg}

    if model:
        ok, msg = cfg.save_hf_model(model)
        results["model"] = {"ok": ok, "message": msg}

    if not token and not model:
        return jsonify({"ok": False, "message": "Nothing to save."}), 400

    overall_ok = all(v["ok"] for v in results.values())
    return jsonify({"ok": overall_ok, "results": results}), (200 if overall_ok else 400)


@app.route("/api/compile", methods=["POST"])
@rate_limit
def compile_route():
    data   = request.get_json(force=True)
    lang   = data.get("lang", "cpp")
    source = data.get("code", "")
    lang   = data.get("lang", "cpp")

    ok, err = validate_code(source)
    if not ok: return jsonify({"error": "validation", "message": err}), 400
    ok, err = validate_lang(lang)
    if not ok: return jsonify({"error": "validation", "message": err}), 400

    raw_timeout = data.get("timeout")
    if raw_timeout is None:
        safe_timeout = 0
    else:
        safe_timeout = max(5, min(int(raw_timeout), 120))

    stdin = data.get("stdin", "") or ""

    result = (
        compile_cpp(source, timeout=safe_timeout, stdin=stdin)
        if lang == "cpp"
        else compile_java(source, timeout=safe_timeout, stdin=stdin)
    )

    errors = []
    if not result["success"] and result.get("stderr"):
        errors = parse_errors(result["stderr"], lang, result.get("source", source))

    try:
        sem = analyse(source, lang)
    except Exception:
        sem = {"symbols": [], "warnings": []}

    snapshot = hist.add_snapshot(
        lang=lang,
        source=source,
        success=result["success"],
        errors=errors,
        warnings=sem.get("warnings", []),
        symbols=sem.get("symbols", []),
    )

    return jsonify({
        "success":  result["success"],
        "output":   result.get("output", []),
        "stderr":   result.get("stderr", ""),
        "tool":     result.get("tool", ""),
        "errors":   errors,
        "source":   result.get("source", source),
        "snapshot": snapshot,
    })


@app.route("/api/explain", methods=["POST"])
@rate_limit
def explain_route():
    data   = request.get_json(force=True)
    errors = data.get("errors", [])
    source = data.get("source", "")
    level  = data.get("level", "beginner")
    lang   = data.get("lang", "cpp")

    prefer_ollama = data.get("prefer_ollama", True)
    ollama_model  = data.get("ollama_model", None)
    hf_model      = data.get("hf_model", None)

    if not errors:
        return jsonify({"explanations": [], "ai": False})

    try:
        explanations, used_ai = explain_ai(
            errors, source, lang, level,
            prefer_ollama=prefer_ollama,
            ollama_model=ollama_model,
            hf_model=hf_model,
        )
    except Exception:
        explanations, used_ai = explain_rules(errors, lang, level), False

    rule_fallbacks = explain_rules(errors, lang, level)
    final = []
    for i, exp in enumerate(explanations):
        fb = rule_fallbacks[i] if i < len(rule_fallbacks) else {}
        final.append(exp if exp and (exp.get("explanation") or exp.get("fix")) else fb)
    for i in range(len(final), len(errors)):
        final.append(rule_fallbacks[i] if i < len(rule_fallbacks) else {
            "title": "Compiler Error",
            "explanation": errors[i].get("raw", "Unknown error"),
            "fix": "Check the flagged line for typos or missing syntax.",
            "fixed_line": errors[i].get("source_line", ""),
        })

    return jsonify({"explanations": final, "ai": used_ai})


@app.route("/api/analyse", methods=["POST"])
@rate_limit
def analyse_route():
    data   = request.get_json(force=True)
    source = data.get("code", "")
    lang   = data.get("lang", "cpp")
    level  = data.get("level", "beginner")

    syntax = gcc_syntax_check(source, lang)
    src_lines = source.splitlines()
    gcc_errors = []
    for d in syntax.get("diagnostics", []):
        lineno = d.get("line", 0)
        src_line = src_lines[lineno - 1].strip() if 0 < lineno <= len(src_lines) else ""
        gcc_errors.append({
            "line":        lineno,
            "column":      d.get("col", 0),
            "severity":    d.get("severity", "error"),
            "raw":         d.get("message", ""),
            "source_line": src_line,
        })

    syntax_explanations = []
    used_ai = False
    if gcc_errors:
        try:
            syntax_explanations, used_ai = explain_ai(gcc_errors, source, lang, level, prefer_ollama=True)
        except Exception:
            syntax_explanations, used_ai = explain_rules(gcc_errors, lang, level), False

        rule_fb = explain_rules(gcc_errors, lang, level)
        filled = []
        for i, exp in enumerate(syntax_explanations):
            fb = rule_fb[i] if i < len(rule_fb) else {}
            filled.append(exp if exp and (exp.get("explanation") or exp.get("fix")) else fb)
        for i in range(len(filled), len(gcc_errors)):
            filled.append(rule_fb[i] if i < len(rule_fb) else {
                "title": "Compiler Error",
                "explanation": gcc_errors[i].get("raw", "Unknown error"),
                "fix": "Check the flagged line.",
                "fixed_line": gcc_errors[i].get("source_line", ""),
            })
        syntax_explanations = filled

    tokens   = tokens_to_dicts(tokenise(source, lang))
    ast      = parse_ast(source, lang)
    mermaid  = ast_to_mermaid(ast)
    semantic = analyse(source, lang)

    return jsonify({
        "tokens":              tokens,
        "ast":                 ast,
        "mermaid":             mermaid,
        "symbols":             semantic["symbols"],
        "warnings":            semantic["warnings"],
        "imports":             semantic["imports"],
        "syntax_ok":           syntax.get("ok"),
        "syntax_errors":       gcc_errors,
        "syntax_explanations": syntax_explanations,
        "syntax_ai":           used_ai,
        "gcc_available":       syntax.get("ok") is not None,
    })


@app.route("/api/error-ref")
def error_ref_route():
    return jsonify(ERROR_REFERENCE)


# ── Compilation History ───────────────────────────────────────────────────────

@app.route("/api/history")
def history_route():
    return jsonify(hist.get_history())

@app.route("/api/history/<run_id>")
def history_detail_route(run_id):
    snap = hist.get_snapshot(run_id)
    if snap is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(snap)

@app.route("/api/history/diff/<before_id>/<after_id>")
def history_diff_route(before_id, after_id):
    result = hist.compute_diff(before_id, after_id)
    if result is None:
        return jsonify({"error": "One or both snapshot IDs not found"}), 404
    return jsonify(result)

@app.route("/api/history/clear", methods=["POST"])
def history_clear_route():
    hist.clear_history()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# AI OPTIMIZER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/optimizer/chat", methods=["POST"])
@rate_limit
def optimizer_chat_route():
    """
    AI code optimization chatbot.

    Request JSON:
      {
        "message":  str,
        "code":     str | null,
        "history":  [{"role": "user"|"assistant", "content": str}]
      }

    Response JSON:
      { "reply": str, "ai": bool, "error": str|null }
    """
    data    = request.get_json(force=True)
    message = data.get("message", "").strip()
    code    = data.get("code",    None)
    history = data.get("history", [])

    if not message:
        return jsonify({"reply": "", "ai": False, "error": "empty_message"}), 400

    result = optimizer_chat(message=message, code=code, history=history)
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════════════════
# GREEN COMPILER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/green/profile", methods=["POST"])
def green_profile_route():
    """
    Full green profile: RAPL + Carbon + Pinpoint hotspots + chart data.

    Request JSON:
      { "source": str, "lang": str, "runtime_ms": float, "country": str }

    Response JSON:
      { "rapl": {...}, "carbon": {...}, "hotspots": [...], "chart": {...} }
    """
    data       = request.get_json(force=True)
    source     = data.get("source",     "")
    lang       = data.get("lang",       "cpp")
    runtime_ms = float(data.get("runtime_ms", 100.0))
    country    = data.get("country",    "IN")

    rapl     = rapl_measure(source, lang, max(runtime_ms, 50.0))
    carbon   = carbon_estimate(rapl, country_code=country)
    hotspots = pinpoint_analyse(source, lang)
    viz_record(rapl)

    return jsonify({
        "rapl":     rapl_to_dict(rapl),
        "carbon":   carbon_to_dict(carbon),
        "hotspots": [hotspot_to_dict(h) for h in hotspots[:8]],
        "chart":    get_chart_data(),
    })


@app.route("/api/green/chart")
def green_chart_route():
    return jsonify(get_chart_data())


@app.route("/api/green/summary")
def green_summary_route():
    return jsonify(viz_summary())


@app.route("/api/green/clear", methods=["POST"])
def green_clear_route():
    viz_clear()
    return jsonify({"ok": True})


# BEGIN SELF-HEAL ADDITION
@app.route("/api/self-heal-status")
def self_heal_status_route():
    return jsonify({"enabled": True})


@app.route("/api/self-heal", methods=["POST"])
@rate_limit
def self_heal_route():
    data   = request.get_json(force=True)
    source = data.get("code", "")
    lang   = data.get("lang", "cpp")

    ok, err = validate_code(source)
    if not ok:
        return jsonify({"error": "validation", "message": err}), 400
    ok, err = validate_lang(lang)
    if not ok:
        return jsonify({"error": "validation", "message": err}), 400

    result = (
        compile_cpp(source, timeout=30)
        if lang == "cpp"
        else compile_java(source, timeout=30)
    )
    errors = []
    if not result.get("success") and result.get("stderr"):
        errors = parse_errors(result["stderr"], lang, result.get("source", source))
    result["errors"] = errors

    try:
        from backend.self_healer import heal
        sh = heal(result=result, source=source, lang=lang)
    except Exception:
        sh = None

    return jsonify({"self_heal": sh, "enabled": cfg.SELF_HEAL_ENABLED})
# END SELF-HEAL ADDITION


# ══════════════════════════════════════════════════════════════════════════════
# ERROR REFERENCE
# ══════════════════════════════════════════════════════════════════════════════

ERROR_REFERENCE = [
    {
        "id": "E001", "tag": "Missing Semicolon",
        "pattern": "expected ';' before",
        "languages": ["C++", "Java"],
        "description": "Every statement must end with a semicolon `;`.",
        "example_bad":  "int x = 5\ncout << x;",
        "example_good": "int x = 5;\ncout << x;",
        "tip": "The error is reported one line AFTER the missing semicolon.",
    },
    {
        "id": "E002", "tag": "Undeclared Identifier",
        "pattern": "was not declared in this scope",
        "languages": ["C++"],
        "description": "You used a name that hasn't been declared.",
        "example_bad":  "cout << myVariable;",
        "example_good": "int myVariable = 42;\ncout << myVariable;",
        "tip": "Declare variables before you use them. Check for typos — C++ is case-sensitive.",
    },
    {
        "id": "E003", "tag": "Type Mismatch",
        "pattern": "invalid conversion from / incompatible types",
        "languages": ["C++", "Java"],
        "description": "You assigned the wrong type of value to a variable.",
        "example_bad":  'int x = "hello";',
        "example_good": 'string x = "hello";',
        "tip": "Use int/double for numbers, string/String for text, bool/boolean for true/false.",
    },
    {
        "id": "E004", "tag": "Missing Closing Brace",
        "pattern": "expected '}' at end / reached end of file",
        "languages": ["C++", "Java"],
        "description": "An opened `{` block was never closed with `}`.",
        "example_bad":  "int main() {\n    cout << 1;\n// missing }",
        "example_good": "int main() {\n    cout << 1;\n}",
        "tip": "Count your { and } — they must be equal.",
    },
    {
        "id": "E005", "tag": "Wrong Argument Count",
        "pattern": "too few / too many arguments",
        "languages": ["C++", "Java"],
        "description": "You called a function with the wrong number of arguments.",
        "example_bad":  "int add(int a, int b) {...}\nadd(1);",
        "example_good": "add(1, 2);",
        "tip": "Count the parameters in the function definition and match them in the call.",
    },
    {
        "id": "E006", "tag": "Undefined Reference",
        "pattern": "undefined reference to",
        "languages": ["C++"],
        "description": "A function is declared but its body is never defined.",
        "example_bad":  "void foo();\nint main() { foo(); }",
        "example_good": "void foo() { cout << 42; }\nint main() { foo(); }",
        "tip": "Make sure every declared function also has a body, or link the correct library.",
    },
    {
        "id": "E007", "tag": "Missing Return Value",
        "pattern": "control reaches end of non-void function",
        "languages": ["C++"],
        "description": "A function declared to return a value doesn't always do so.",
        "example_bad":  "int getX() {\n    int x = 5;\n    // forgot return\n}",
        "example_good": "int getX() {\n    int x = 5;\n    return x;\n}",
        "tip": "Every code path through a non-void function must have a return statement.",
    },
    {
        "id": "E008", "tag": "Cannot Find Symbol (Java)",
        "pattern": "cannot find symbol",
        "languages": ["Java"],
        "description": "Java can't find a variable, method, or class you referenced.",
        "example_bad":  'System.out.println(messge);',
        "example_good": 'System.out.println(message);',
        "tip": "Check for typos. Java is case-sensitive. Make sure imports are correct.",
    },
    {
        "id": "E009", "tag": "Array Out of Bounds",
        "pattern": "array subscript / index out of range",
        "languages": ["C++", "Java"],
        "description": "You're accessing an array index that doesn't exist.",
        "example_bad":  "int arr[3] = {1,2,3};\ncout << arr[5];",
        "example_good": "cout << arr[2]; // last valid index is size-1",
        "tip": "Valid indices are 0 to (array_size - 1). Never access beyond that.",
    },
    {
        "id": "E010", "tag": "Division by Zero",
        "pattern": "division by zero",
        "languages": ["C++", "Java"],
        "description": "Dividing by zero is undefined and will crash your program.",
        "example_bad":  "int result = 10 / 0;",
        "example_good": "if (divisor != 0) result = 10 / divisor;",
        "tip": "Always guard divisions with a zero-check.",
    },
]


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n⚡ CodeForge Enhanced → http://localhost:{port}\n")
    print("  New routes: /api/optimizer/chat  /api/green/profile  /api/green/chart")
    print("  Offline AI:  /api/local-model-status  /api/local-model-warmup\n")
    # Optional: warm up local transformer in background so first request is fast
    if cfg.local_model_enabled:
        import threading
        t = threading.Thread(target=warmup_model, daemon=True)
        t.start()
        print("  [local_model] Warming up offline transformer in background...\n")
    app.run(debug=True, port=port, use_reloader=False)
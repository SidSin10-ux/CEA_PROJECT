# CodeForge

A browser-based C++ / Java IDE with real compiler integration and AI-powered error explanations.

## What's new (v5)

### 1. GCC replaces the custom lexer
`backend/lexer.py` no longer defines tokens by hand. It now calls the **real `g++` compiler** via `subprocess` with `-fsyntax-only` to validate syntax. This means:
- Errors come straight from GCC — 100% accurate diagnostics.
- The Symbols pane shows a **GCC Syntax Check** banner with every error before you even hit Run.
- Token display (for the Tokens panel) is still rendered as a fast structural pass but error *detection* is fully GCC-backed.

### 2. NLP / AI explanations are now live
`backend/nlp_explainer.py` calls the **Anthropic Claude API** with the correct `x-api-key` and `anthropic-version` headers. When an `ANTHROPIC_API_KEY` env var is set, every compiler error gets a beginner-friendly (or expert-level) plain-English explanation + specific fix suggestion. Without the key it falls back to a built-in rule-based explainer.

## Setup

```bash
pip install flask
export ANTHROPIC_API_KEY=sk-ant-...   # enables AI explanations
python server.py
# open http://localhost:5000
```

`g++` (GCC) must be installed for C++ support. `javac` for Java.

## Architecture

| File | Role |
|------|------|
| `backend/lexer.py` | Runs `g++ -fsyntax-only` via subprocess; structural token display |
| `backend/compiler.py` | Full compile + run via `g++` / `javac` |
| `backend/parser.py` | Regex AST → Mermaid diagram |
| `backend/semantic.py` | Symbol table + warnings |
| `backend/nlp_explainer.py` | AI error explanations via Claude API (falls back to rules) |
| `server.py` | Flask API server |
| `static/index.html` | Single-file IDE frontend (CodeMirror + Mermaid) |
 v2 ⚡

A standalone compiler IDE with real g++/javac, AI error explanations, AST viewer, symbol table, and token stream.

## Project Structure

```
codeforge_v2/
  server.py               ← Flask entry point (routes)
  backend/
    compiler.py           ← Real g++ / javac compilation
    lexer.py              ← Tokeniser (C++ and Java)
    parser.py             ← AST builder + Mermaid diagram generator
    semantic.py           ← Symbol table + semantic warnings
    nlp_explainer.py      ← AI error explanations (Claude API + rule-based fallback)
  static/
    index.html            ← Complete IDE frontend
```

## Setup & Run

```powershell
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python server.py
```

```bash
# Mac / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
python3 server.py
```

Open **http://localhost:5000**

## Requirements
- Python 3.8+, Flask (`pip install flask`)
- `g++` for C++ — Windows: install MinGW or MSYS2; Linux: `sudo apt install build-essential`
- `javac` for Java — `sudo apt install default-jdk` (optional)
- Anthropic API key for AI explanations (falls back to rule-based NLP if not set)

## Keyboard Shortcuts
- `Ctrl+Enter` / `Cmd+Enter` — Run
- `Ctrl+/` — Toggle comment
- `Tab` — Indent 4 spaces


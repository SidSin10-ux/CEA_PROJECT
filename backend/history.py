"""
backend/history.py
===================
Compilation history store — saves snapshots of each run and computes
semantic diffs between any two snapshots.

Each snapshot stores:
  - id          : unique run ID (e.g. "run_003")
  - timestamp   : ISO-8601 UTC string
  - lang        : "cpp" | "java"
  - source      : full source code
  - success     : bool (did it compile?)
  - errors      : list of error dicts  {line, column, severity, raw}
  - warnings    : list of semantic warning dicts {kind, message, line}
  - symbols     : list of symbol dicts {name, kind, type, scope, line}
  - error_count : int  (len(errors))
  - warning_count: int (len(warnings))
  - label       : short human-readable label (e.g. "Run 3 — 2 errors")

The store is kept in memory (a plain Python list) and is bounded to
MAX_HISTORY snapshots so it never grows unboundedly.

Diff output (compute_diff) returns:
  - errors_fixed    : errors present in 'before' but gone in 'after'
  - errors_new      : errors that appeared in 'after' but not in 'before'
  - errors_common   : errors present in both
  - warnings_fixed  : warnings resolved between runs
  - warnings_new    : new warnings
  - symbols_added   : symbols that appeared in 'after'
  - symbols_removed : symbols that disappeared
  - symbols_changed : symbols whose type or scope changed
  - lines_changed   : (before_lines, after_lines) — raw line count delta
  - summary         : human-readable one-line summary string
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import List, Optional

MAX_HISTORY = 30  # keep the last 30 snapshots per server session

_lock    = threading.Lock()
_history: List[dict] = []
_counter = 0  # monotonically increasing run counter


# ── Public API ────────────────────────────────────────────────────────────────

def add_snapshot(
    lang: str,
    source: str,
    success: bool,
    errors: list,
    warnings: list,
    symbols: list,
) -> dict:
    """
    Create and store a new snapshot.  Returns the saved snapshot dict
    (including its assigned id and label) so the caller can include it
    in the API response.
    """
    global _counter
    with _lock:
        _counter += 1
        run_num = _counter

        err_count  = len(errors)
        warn_count = len(warnings)

        if success:
            label = f"Run {run_num} — compiled OK"
        elif err_count == 1:
            label = f"Run {run_num} — 1 error"
        else:
            label = f"Run {run_num} — {err_count} errors"

        snapshot = {
            "id":            f"run_{run_num:03d}",
            "run_num":       run_num,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
            "lang":          lang,
            "source":        source,
            "success":       success,
            "errors":        errors,
            "warnings":      warnings,
            "symbols":       symbols,
            "error_count":   err_count,
            "warning_count": warn_count,
            "label":         label,
            "line_count":    len(source.splitlines()),
        }

        _history.append(snapshot)
        # Trim oldest entries if we exceed the cap
        if len(_history) > MAX_HISTORY:
            _history.pop(0)

        return snapshot


def get_history() -> List[dict]:
    """Return snapshots newest-first, with source omitted to keep payload small."""
    with _lock:
        return [_slim(s) for s in reversed(_history)]


def get_snapshot(run_id: str) -> Optional[dict]:
    """Return a single snapshot by id (includes full source)."""
    with _lock:
        for s in _history:
            if s["id"] == run_id:
                return s
    return None


def compute_diff(before_id: str, after_id: str) -> Optional[dict]:
    """
    Compute a semantic diff between two snapshots.
    Returns None if either id is not found.
    """
    with _lock:
        before = next((s for s in _history if s["id"] == before_id), None)
        after  = next((s for s in _history if s["id"] == after_id),  None)

    if not before or not after:
        return None

    return _diff(before, after)


def clear_history() -> None:
    global _counter
    with _lock:
        _history.clear()
        _counter = 0


# ── Diff logic ────────────────────────────────────────────────────────────────

def _error_key(e: dict) -> str:
    """Stable key for deduplicating errors across runs."""
    # Normalise the message slightly so minor GCC wording changes don't
    # prevent matching the "same" error across two compilations.
    msg = e.get("raw", e.get("message", "")).strip().lower()
    return f"{e.get('line', 0)}:{msg[:60]}"


def _warn_key(w: dict) -> str:
    msg = w.get("message", "").strip().lower()
    return f"{w.get('line', 0)}:{msg[:60]}"


def _sym_key(s: dict) -> str:
    return f"{s.get('name', '')}:{s.get('scope', '')}"


def _diff(before: dict, after: dict) -> dict:
    # ── Errors ────────────────────────────────────────────────────────────────
    before_err = {_error_key(e): e for e in before.get("errors", [])}
    after_err  = {_error_key(e): e for e in after.get("errors",  [])}

    errors_fixed  = [before_err[k] for k in before_err if k not in after_err]
    errors_new    = [after_err[k]  for k in after_err  if k not in before_err]
    errors_common = [after_err[k]  for k in after_err  if k in before_err]

    # ── Warnings ──────────────────────────────────────────────────────────────
    before_warn = {_warn_key(w): w for w in before.get("warnings", [])}
    after_warn  = {_warn_key(w): w for w in after.get("warnings",  [])}

    warnings_fixed = [before_warn[k] for k in before_warn if k not in after_warn]
    warnings_new   = [after_warn[k]  for k in after_warn  if k not in before_warn]

    # ── Symbols ───────────────────────────────────────────────────────────────
    before_sym = {_sym_key(s): s for s in before.get("symbols", [])}
    after_sym  = {_sym_key(s): s for s in after.get("symbols",  [])}

    symbols_added   = [after_sym[k]  for k in after_sym  if k not in before_sym]
    symbols_removed = [before_sym[k] for k in before_sym if k not in after_sym]

    symbols_changed = []
    for k in before_sym:
        if k in after_sym:
            b, a = before_sym[k], after_sym[k]
            changed_fields = {}
            for field in ("type", "scope", "kind"):
                bv, av = b.get(field, ""), a.get(field, "")
                if bv != av:
                    changed_fields[field] = {"before": bv, "after": av}
            if changed_fields:
                symbols_changed.append({
                    "name":    a.get("name"),
                    "changes": changed_fields,
                })

    # ── Lines ─────────────────────────────────────────────────────────────────
    lines_before = before.get("line_count", 0)
    lines_after  = after.get("line_count",  0)
    line_delta   = lines_after - lines_before

    # ── Summary ───────────────────────────────────────────────────────────────
    parts = []
    if errors_fixed:
        parts.append(f"{len(errors_fixed)} error{'s' if len(errors_fixed)!=1 else ''} fixed")
    if errors_new:
        parts.append(f"{len(errors_new)} new error{'s' if len(errors_new)!=1 else ''}")
    if not errors_fixed and not errors_new and not before["success"] and not after["success"]:
        parts.append("same errors persist")
    if after["success"] and not before["success"]:
        parts.append("now compiles successfully")
    if before["success"] and not after["success"]:
        parts.append("introduced compilation errors")
    if symbols_added:
        parts.append(f"{len(symbols_added)} symbol{'s' if len(symbols_added)!=1 else ''} added")
    if symbols_removed:
        parts.append(f"{len(symbols_removed)} symbol{'s' if len(symbols_removed)!=1 else ''} removed")
    if line_delta:
        parts.append(f"{abs(line_delta)} line{'s' if abs(line_delta)!=1 else ''} {'added' if line_delta>0 else 'removed'}")

    summary = "; ".join(parts) if parts else "No meaningful changes"

    return {
        "before":          _slim(before),
        "after":           _slim(after),
        "errors_fixed":    errors_fixed,
        "errors_new":      errors_new,
        "errors_common":   errors_common,
        "warnings_fixed":  warnings_fixed,
        "warnings_new":    warnings_new,
        "symbols_added":   symbols_added,
        "symbols_removed": symbols_removed,
        "symbols_changed": symbols_changed,
        "lines_before":    lines_before,
        "lines_after":     lines_after,
        "line_delta":      line_delta,
        "summary":         summary,
    }


def _slim(s: dict) -> dict:
    """Strip source code from snapshot for list views (keeps payload small)."""
    return {k: v for k, v in s.items() if k != "source"}

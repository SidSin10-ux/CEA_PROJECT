"""
backend/green/pinpoint.py — code hotspot analyser
Field names match what the frontend JS reads:
  h.line, h.heat ("high"|"med"|"low"), h.label, h.desc, h.fix
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List


@dataclass
class Hotspot:
    line:  int  = 0
    code:  str  = ""
    heat:  str  = "low"    # "high" | "med" | "low"  — JS uses h.heat
    label: str  = ""       # JS uses h.label
    desc:  str  = ""       # JS uses h.desc
    fix:   str  = ""       # JS uses h.fix


# (regex, label, heat, desc, fix)
_PATTERNS = [
    (
        r"\bfor\s*\(.*\bsize\(\)\b",
        "Loop calls .size() each iteration",
        "med",
        "Calling .size() on every iteration adds unnecessary overhead.",
        "Cache the size before the loop: `size_t n = v.size(); for (size_t i = 0; i < n; i++)`",
    ),
    (
        r"\bpush_back\s*\(",
        "Repeated push_back (possible reallocation)",
        "med",
        "push_back can trigger expensive memory copies if capacity is exceeded.",
        "Call `v.reserve(n)` before your push_back loop to pre-allocate memory.",
    ),
    (
        r"\bnew\s+\w+\s*\[",
        "Raw heap array allocation",
        "med",
        "Manual new[] requires matching delete[] and risks memory leaks.",
        "Use `std::vector<T>` instead of `new T[]` for automatic memory management.",
    ),
    (
        r"\bstd::endl\b",
        "std::endl flushes the output buffer",
        "low",
        "std::endl forces a buffer flush on every call, which is slow in loops.",
        "Replace `std::endl` with `'\\n'` to avoid unnecessary buffer flushes.",
    ),
    (
        r"(?:for|while)\s*\(.*\)\s*\{?\s*\n.*(?:cout|printf)",
        "I/O inside a loop",
        "high",
        "Console output inside a loop is thousands of times slower than computation.",
        "Accumulate output in a string or buffer, then print once after the loop.",
    ),
    (
        r"(?:for|while)\s*\([^)]*\)[^{]*\{[^}]*(?:for|while)\s*\(",
        "Nested loops detected",
        "high",
        "Nested loops often mean O(n²) or worse — a common performance killer.",
        "Consider using hash maps, sorting + binary search, or a sliding window to reduce complexity.",
    ),
    (
        r"\brecursive\b|\brecursi",
        "Recursive function (deep stack risk)",
        "med",
        "Deep recursion uses stack memory per call and can cause stack overflow.",
        "For deep recursion, use memoization or convert to an iterative approach.",
    ),
    (
        r"\bsleep\s*\(|\bSleep\s*\(",
        "Busy-wait / sleep in code",
        "low",
        "sleep() wastes CPU cycles without doing useful work.",
        "Use event-driven patterns or condition variables instead of polling with sleep.",
    ),
    (
        r"\bmap<|std::map<",
        "std::map uses O(log n) lookups",
        "low",
        "std::map is a sorted tree with O(log n) access — slower than a hash map.",
        "If key order doesn't matter, use `std::unordered_map` for O(1) average access.",
    ),
    (
        r"\bstring\s+\w+\s*=\s*\w+\s*\+",
        "String concatenation with +",
        "med",
        "Repeated + concatenation builds a new string each time — O(n²) overall.",
        "Use `std::ostringstream` or `std::string::append()` to build strings efficiently.",
    ),
    (
        r"\bgetline\s*\(|cin\s*>>",
        "Console input reads",
        "low",
        "Unoptimised I/O can be slow for large inputs.",
        "Add `ios::sync_with_stdio(false); cin.tie(nullptr);` at the start of main for faster I/O.",
    ),
    (
        r"\bthread\b|pthread",
        "Thread creation overhead",
        "med",
        "Creating and destroying threads repeatedly is expensive.",
        "Use a thread pool (`std::async`, OpenMP) to reuse threads instead of recreating them.",
    ),
]


def analyse(source: str, lang: str = "cpp") -> List[Hotspot]:
    lines    = source.splitlines()
    hotspots: List[Hotspot] = []
    seen_lines = set()

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        if lineno in seen_lines:
            continue

        for pattern, label, heat, desc, fix in _PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                hotspots.append(Hotspot(
                    line  = lineno,
                    code  = stripped[:120],
                    heat  = heat,
                    label = label,
                    desc  = desc,
                    fix   = fix,
                ))
                seen_lines.add(lineno)
                break

    _order = {"high": 0, "med": 1, "low": 2}
    hotspots.sort(key=lambda h: _order.get(h.heat, 3))
    return hotspots


def to_dict(h: Hotspot) -> dict:
    # Names must match JS: h.line, h.heat, h.label, h.desc, h.fix
    return {
        "line":  h.line,
        "code":  h.code,
        "heat":  h.heat,
        "label": h.label,
        "desc":  h.desc,
        "fix":   h.fix,
    }

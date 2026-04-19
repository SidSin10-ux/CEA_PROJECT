"""
backend/compiler.py
====================
Real compiler integration: g++ for C++, javac/java for Java.
Handles header injection, compilation, execution, and error parsing.
"""
from __future__ import annotations
import os, re, shutil, subprocess, tempfile
from typing import List

# ── Smart header injection ────────────────────────────────────────────────────

def inject_cpp_headers(source: str) -> str:
    norm    = re.sub(r"#include\s*<", "#include <", source)
    prepend = []

    # I/O
    uses_io    = any(s in source for s in ("cout","cin","cerr","endl","printf","scanf","puts","gets","fgets","fprintf","fscanf","sprintf","sscanf"))
    # Strings
    uses_str   = ("string " in source or "std::string" in source or "getline(" in source)
    # Containers
    uses_vec   = ("vector<" in source or "std::vector" in source)
    uses_map   = ("map<" in source or "unordered_map<" in source or "std::map" in source)
    uses_set   = ("set<" in source or "unordered_set<" in source or "std::set" in source)
    uses_deque = ("deque<" in source or "std::deque" in source)
    uses_list  = ("list<" in source or "std::list" in source or "forward_list<" in source)
    uses_stack = ("stack<" in source or "std::stack" in source)
    uses_queue = ("queue<" in source or "priority_queue<" in source or "std::queue" in source or "std::priority_queue" in source)
    uses_pair  = ("pair<" in source or "make_pair(" in source or "std::pair" in source)
    uses_tuple = ("tuple<" in source or "make_tuple(" in source or "std::tuple" in source)
    uses_arr   = ("array<" in source or "std::array" in source)
    # Algorithms / numeric
    uses_alg   = any(s in source for s in ("sort(","find(","max(","min(","reverse(","count(","lower_bound(","upper_bound(","binary_search(","accumulate(","fill(","copy(","transform(","unique(","next_permutation(","prev_permutation("))
    uses_num   = ("accumulate(" in source or "iota(" in source)
    uses_cmath = any(s in source for s in ("sqrt(","pow(","abs(","floor(","ceil(","sin(","cos(","tan(","log(","log2(","log10(","exp(","fabs(","round(","fmod("))
    # Utilities
    uses_func  = ("function<" in source or "std::function" in source)
    uses_mem   = ("shared_ptr<" in source or "unique_ptr<" in source or "weak_ptr<" in source or "make_shared<" in source or "make_unique<" in source)
    uses_iter  = ("iterator" in source or "begin(" in source or "end(" in source or "rbegin(" in source or "rend(" in source)
    uses_chrono= ("chrono::" in source or "high_resolution_clock" in source)
    uses_thread= ("thread" in source and "std::" in source)
    uses_mutex = ("mutex" in source or "lock_guard" in source)
    uses_fstream=("fstream" in source or "ifstream" in source or "ofstream" in source)
    uses_sstream=("stringstream" in source or "istringstream" in source or "ostringstream" in source)
    uses_limits= ("numeric_limits" in source or "INT_MAX" in source or "INT_MIN" in source or "LLONG_MAX" in source or "DBL_MAX" in source)
    uses_cassert=("assert(" in source)
    uses_cstring=("strlen(" in source or "strcpy(" in source or "strcmp(" in source or "strcat(" in source or "memset(" in source or "memcpy(" in source or "strchr(" in source or "strstr(" in source)
    uses_cstdlib=("malloc(" in source or "free(" in source or "calloc(" in source or "realloc(" in source or "exit(" in source or "rand(" in source or "srand(" in source or "atoi(" in source or "atof(" in source)
    uses_regex = ("regex" in source and "std::" in source)
    uses_bits  = ("#include <bits/stdc++.h>" in source)

    has_using  = "using namespace std" in source

    # Only inject if not already present and not using bits/stdc++
    if not uses_bits:
        if uses_io      and "#include <iostream>"    not in norm: prepend.append("#include <iostream>")
        if uses_str     and "#include <string>"      not in norm: prepend.append("#include <string>")
        if uses_vec     and "#include <vector>"      not in norm: prepend.append("#include <vector>")
        if uses_map     and "#include <map>"         not in norm: prepend.append("#include <map>")
        if uses_set     and "#include <set>"         not in norm: prepend.append("#include <set>")
        if uses_deque   and "#include <deque>"       not in norm: prepend.append("#include <deque>")
        if uses_list    and "#include <list>"        not in norm: prepend.append("#include <list>")
        if uses_stack   and "#include <stack>"       not in norm: prepend.append("#include <stack>")
        if uses_queue   and "#include <queue>"       not in norm: prepend.append("#include <queue>")
        if uses_pair    and "#include <utility>"     not in norm: prepend.append("#include <utility>")
        if uses_tuple   and "#include <tuple>"       not in norm: prepend.append("#include <tuple>")
        if uses_arr     and "#include <array>"       not in norm: prepend.append("#include <array>")
        if uses_alg     and "#include <algorithm>"   not in norm: prepend.append("#include <algorithm>")
        if uses_num     and "#include <numeric>"     not in norm: prepend.append("#include <numeric>")
        if uses_cmath   and "#include <cmath>"       not in norm: prepend.append("#include <cmath>")
        if uses_func    and "#include <functional>"  not in norm: prepend.append("#include <functional>")
        if uses_mem     and "#include <memory>"      not in norm: prepend.append("#include <memory>")
        if uses_iter    and "#include <iterator>"    not in norm: prepend.append("#include <iterator>")
        if uses_chrono  and "#include <chrono>"      not in norm: prepend.append("#include <chrono>")
        if uses_thread  and "#include <thread>"      not in norm: prepend.append("#include <thread>")
        if uses_mutex   and "#include <mutex>"       not in norm: prepend.append("#include <mutex>")
        if uses_fstream and "#include <fstream>"     not in norm: prepend.append("#include <fstream>")
        if uses_sstream and "#include <sstream>"     not in norm: prepend.append("#include <sstream>")
        if uses_limits  and "#include <climits>"     not in norm: prepend.append("#include <climits>")
        if uses_limits  and "#include <cfloat>"      not in norm: prepend.append("#include <cfloat>")
        if uses_cassert and "#include <cassert>"     not in norm: prepend.append("#include <cassert>")
        if uses_cstring and "#include <cstring>"     not in norm: prepend.append("#include <cstring>")
        if uses_cstdlib and "#include <cstdlib>"     not in norm: prepend.append("#include <cstdlib>")
        if uses_regex   and "#include <regex>"       not in norm: prepend.append("#include <regex>")

    if (uses_io or uses_str or uses_vec or uses_map or uses_set) and not has_using:
        prepend.append("using namespace std;")

    return ("\n".join(prepend) + "\n" + source) if prepend else source


# ── Error parser ──────────────────────────────────────────────────────────────

# Windows paths contain a drive letter colon (C:\...) so we allow one optional
# single-letter drive prefix before the first colon, e.g. "C:\path\file.cpp:6:5:"
_GCC_DIAG   = re.compile(r"^(?:[A-Za-z]:)?[^:]+:(?P<l>\d+):(?P<c>\d+):\s*(?P<s>error|warning|note):\s*(?P<m>.+)$")
_JAVAC_DIAG = re.compile(r"^(?:[A-Za-z]:)?[^:]+\.java:(?P<l>\d+):\s*(?P<s>error|warning):\s*(?P<m>.+)$")

def parse_errors(stderr: str, lang: str, source: str) -> List[dict]:
    src_lines = source.splitlines()
    pat    = _GCC_DIAG if lang == "cpp" else _JAVAC_DIAG
    errors = []
    seen   = set()

    for line in stderr.splitlines():
        m = pat.match(line)
        if not m:
            continue
        sev = m.group("s")
        if sev == "note":
            continue
        lineno = int(m.group("l"))
        col    = int(m.group("c")) if "c" in m.groupdict() and m.group("c") else 0
        raw    = m.group("m").strip()

        key = (lineno, raw[:40])
        if key in seen:
            continue
        seen.add(key)

        src_line = src_lines[lineno - 1].strip() if 0 < lineno <= len(src_lines) else ""
        errors.append({
            "line":        lineno,
            "column":      col,
            "severity":    sev,
            "raw":         raw,
            "source_line": src_line,
        })

    return errors[:8]


# ── C++ compilation ───────────────────────────────────────────────────────────

def compile_cpp(source: str, timeout: int = 30, stdin: str = "") -> dict:
    """
    Compiles and runs C++ source using g++.

    - compile_timeout: max seconds for g++ to compile (30 s)
    - run timeout: passed-in `timeout` parameter (default 30 s)
      Program runs until it exits naturally or the timeout is hit.
      Set timeout=0 to disable the run timeout entirely (infinite).
    """
    gpp = shutil.which("g++")
    if not gpp:
        return {"success": False, "output": [], "stderr": "g++ not found.", "tool": "g++", "source": source}

    try:
        ver = subprocess.check_output([gpp, "--version"], text=True, timeout=5).splitlines()[0]
    except Exception:
        ver = "g++"

    enriched = inject_cpp_headers(source)

    with tempfile.TemporaryDirectory(prefix="cf_cpp_") as tmp:
        src_path = os.path.join(tmp, "program.cpp")
        exe_path = os.path.join(tmp, "program")
        open(src_path, "w", encoding="utf-8").write(enriched)

        # Compile step — always up to 30 s
        comp = subprocess.run(
            [gpp, "-std=c++17", "-O0", "-Wall", "-Wextra", "-o", exe_path, src_path],
            capture_output=True, text=True, timeout=30
        )
        if comp.returncode != 0:
            return {
                "success": False, "output": [],
                "stderr":  comp.stderr, "stdout": comp.stdout,
                "tool":    ver, "source": enriched,
            }

        # Run step — use caller-supplied timeout (0 = no limit)
        run_timeout = timeout if timeout and timeout > 0 else None
        try:
            run = subprocess.run(
                [exe_path],
                input=stdin,
                capture_output=True, text=True,
                timeout=run_timeout
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False, "output": [],
                "stderr":  f"⏱ Program exceeded {run_timeout}s execution time limit.",
                "tool": ver, "source": enriched
            }

        return {
            "success": run.returncode == 0,
            "output":  run.stdout.splitlines(),
            "stderr":  (comp.stderr + "\n" + run.stderr).strip(),
            "tool":    ver, "source": enriched,
        }


# ── Java compilation ──────────────────────────────────────────────────────────

def compile_java(source: str, timeout: int = 30, stdin: str = "") -> dict:
    javac = shutil.which("javac")
    java  = shutil.which("java")

    if not javac:
        return {
            "success": False, "output": [],
            "stderr": (
                "javac not installed on this server.\n"
                "To run locally:\n"
                "  1. Save as YourClassName.java\n"
                "  2. javac YourClassName.java\n"
                "  3. java YourClassName"
            ),
            "tool": "javac (unavailable)", "source": source,
        }

    m = re.search(r"public\s+class\s+(\w+)", source)
    classname = m.group(1) if m else "Main"

    try:
        ver = subprocess.check_output([javac, "-version"], stderr=subprocess.STDOUT,
                                       text=True, timeout=5).strip()
    except Exception:
        ver = "javac"

    with tempfile.TemporaryDirectory(prefix="cf_java_") as tmp:
        src_path = os.path.join(tmp, f"{classname}.java")
        open(src_path, "w", encoding="utf-8").write(source)

        comp = subprocess.run([javac, src_path], capture_output=True, text=True, timeout=30)
        if comp.returncode != 0:
            return {
                "success": False, "output": [],
                "stderr":  comp.stderr, "stdout": comp.stdout,
                "tool":    ver, "source": source,
            }

        run_timeout = timeout if timeout and timeout > 0 else None
        try:
            run = subprocess.run(
                [java, "-cp", tmp, classname],
                input=stdin,
                capture_output=True, text=True,
                timeout=run_timeout
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False, "output": [],
                "stderr":  f"⏱ Program exceeded {run_timeout}s execution time limit.",
                "tool": ver, "source": source
            }

        return {
            "success": run.returncode == 0,
            "output":  run.stdout.splitlines(),
            "stderr":  (comp.stderr + "\n" + run.stderr).strip(),
            "tool":    ver, "source": source,
        }

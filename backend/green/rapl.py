"""
backend/green/rapl.py  — energy profiling with field names that match the frontend
"""
from __future__ import annotations
import re, time
from dataclasses import dataclass, field


@dataclass
class RaplResult:
    runtime_ms:       float = 0.0
    cpu_energy_j:     float = 0.0
    dram_energy_j:    float = 0.0
    gpu_energy_j:     float = 0.0
    total_energy_j:   float = 0.0
    power_w:          float = 0.0
    complexity_score: float = 0.0
    lang:             str   = "cpp"
    source_lines:     int   = 0
    source:           str   = "estimated"
    timestamp:        float = field(default_factory=time.time)


_EXPENSIVE_PATTERNS = [
    (r"\bfor\s*\(",          1.5),
    (r"\bwhile\s*\(",        1.5),
    (r"\bdo\s*\{",           1.5),
    (r"\bnew\b",             2.0),
    (r"\bmalloc\s*\(",       2.0),
    (r"\brecursi",           3.0),
    (r"\bsort\s*\(",         2.5),
    (r"\bmap\b|\bset\b",     1.8),
    (r"\bthread\b",          3.5),
    (r"cout\s*<<|printf\s*\(", 0.5),
]

_CPU_BASELINE_W  = 15.0
_DRAM_BASELINE_W =  3.0
_GPU_BASELINE_W  =  0.5


def _complexity_score(source: str) -> float:
    score = 0.0
    for pattern, weight in _EXPENSIVE_PATTERNS:
        score += len(re.findall(pattern, source, re.IGNORECASE)) * weight
    score += max(1, len(source.splitlines())) * 0.1
    return min(score, 100.0)


def measure(source: str, lang: str, runtime_ms: float) -> RaplResult:
    complexity  = _complexity_score(source)
    load_factor = 0.3 + (complexity / 100.0) * 0.7
    runtime_s   = runtime_ms / 1000.0

    cpu_power  = _CPU_BASELINE_W  * load_factor
    dram_power = _DRAM_BASELINE_W * (0.5 + load_factor * 0.5)
    gpu_power  = _GPU_BASELINE_W  * load_factor

    cpu_e  = cpu_power  * runtime_s
    dram_e = dram_power * runtime_s
    gpu_e  = gpu_power  * runtime_s

    return RaplResult(
        runtime_ms       = round(runtime_ms, 2),
        cpu_energy_j     = round(cpu_e,  6),
        dram_energy_j    = round(dram_e, 6),
        gpu_energy_j     = round(gpu_e,  6),
        total_energy_j   = round(cpu_e + dram_e + gpu_e, 6),
        power_w          = round(cpu_power + dram_power + gpu_power, 3),
        complexity_score = round(complexity, 2),
        lang             = lang,
        source_lines     = len(source.splitlines()),
        source           = "estimated",
    )


def to_dict(result: RaplResult) -> dict:
    # Field names must match exactly what the JS reads:
    # r.cpu_joules, r.dram_joules, r.gpu_joules, r.total_joules, r.source
    return {
        "cpu_joules":       result.cpu_energy_j,
        "dram_joules":      result.dram_energy_j,
        "gpu_joules":       result.gpu_energy_j,
        "total_joules":     result.total_energy_j,
        "runtime_ms":       result.runtime_ms,
        "power_w":          result.power_w,
        "complexity_score": result.complexity_score,
        "source":           result.source,
        "lang":             result.lang,
        "source_lines":     result.source_lines,
        "timestamp":        result.timestamp,
    }

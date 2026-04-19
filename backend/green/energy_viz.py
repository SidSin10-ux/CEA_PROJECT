"""
backend/green/energy_viz.py — energy time-series store
Returns chart data in the format the JS reads:
  chart.datasets.cpu, chart.datasets.dram, chart.datasets.gpu
"""
from __future__ import annotations
import datetime, time
from typing import List
from .rapl import RaplResult

_MAX_ENTRIES = 200
_history: List[dict] = []


def record(rapl: RaplResult) -> None:
    global _history
    _history.append({
        "timestamp":        rapl.timestamp,
        "runtime_ms":       rapl.runtime_ms,
        "cpu_energy_j":     rapl.cpu_energy_j,
        "dram_energy_j":    rapl.dram_energy_j,
        "gpu_energy_j":     rapl.gpu_energy_j,
        "total_energy_j":   rapl.total_energy_j,
        "power_w":          rapl.power_w,
        "complexity_score": rapl.complexity_score,
        "lang":             rapl.lang,
        "source_lines":     rapl.source_lines,
    })
    if len(_history) > _MAX_ENTRIES:
        _history = _history[-_MAX_ENTRIES:]


def get_chart_data() -> dict:
    """
    Return data in exactly the shape the JS reads:
        chart.labels            — time labels
        chart.datasets.cpu      — CPU energy array
        chart.datasets.dram     — DRAM energy array
        chart.datasets.gpu      — GPU energy array
    """
    labels = []
    cpu    = []
    dram   = []
    gpu    = []

    for entry in _history:
        labels.append(_fmt_ts(entry["timestamp"]))
        cpu.append(entry["cpu_energy_j"])
        dram.append(entry["dram_energy_j"])
        gpu.append(entry["gpu_energy_j"])

    return {
        "labels":   labels,
        "datasets": {
            "cpu":  cpu,
            "dram": dram,
            "gpu":  gpu,
        },
        "count": len(_history),
    }


def summary() -> dict:
    if not _history:
        return {
            "count": 0,
            "total_energy_j":   0.0,
            "avg_energy_j":     0.0,
            "avg_runtime_ms":   0.0,
            "avg_power_w":      0.0,
            "avg_complexity":   0.0,
            "most_expensive_j": 0.0,
        }
    total_e   = sum(e["total_energy_j"]   for e in _history)
    avg_rt    = sum(e["runtime_ms"]        for e in _history) / len(_history)
    avg_pwr   = sum(e["power_w"]           for e in _history) / len(_history)
    avg_cmplx = sum(e["complexity_score"]  for e in _history) / len(_history)
    max_e     = max(e["total_energy_j"]    for e in _history)
    return {
        "count":            len(_history),
        "total_energy_j":   round(total_e,   6),
        "avg_energy_j":     round(total_e / len(_history), 6),
        "avg_runtime_ms":   round(avg_rt,    2),
        "avg_power_w":      round(avg_pwr,   3),
        "avg_complexity":   round(avg_cmplx, 2),
        "most_expensive_j": round(max_e,     6),
    }


def clear() -> None:
    global _history
    _history = []


def _fmt_ts(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")

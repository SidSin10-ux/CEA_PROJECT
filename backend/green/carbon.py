"""
backend/green/carbon.py — carbon footprint estimation
Field names match what the frontend JS reads:
  c.co2_grams, c.kwh_used, c.runtime_ms, c.grade, c.equivalent
"""
from __future__ import annotations
from dataclasses import dataclass
from .rapl import RaplResult

_CARBON_INTENSITY: dict[str, float] = {
    "IN":  713.0, "CN":  555.0, "US":  386.0, "AU":  538.0,
    "DE":  350.0, "GB":  233.0, "FR":   58.0, "BR":   91.0,
    "CA":  130.0, "JP":  463.0, "KR":  415.0, "SE":   13.0,
    "NO":   29.0, "ZA":  740.0, "SG":  408.0, "NL":  283.0,
    "IT":  233.0, "ES":  168.0, "PL":  635.0, "RU":  322.0,
    "WORLD": 436.0,
}

_COUNTRY_NAMES = {
    "IN": "India", "CN": "China", "US": "United States", "AU": "Australia",
    "DE": "Germany", "GB": "United Kingdom", "FR": "France", "BR": "Brazil",
    "CA": "Canada", "JP": "Japan", "KR": "South Korea", "SE": "Sweden",
    "NO": "Norway", "ZA": "South Africa", "SG": "Singapore", "NL": "Netherlands",
    "IT": "Italy", "ES": "Spain", "PL": "Poland", "RU": "Russia",
    "WORLD": "Global Average",
}


@dataclass
class CarbonResult:
    country_code:    str   = "IN"
    country_name:    str   = "India"
    intensity_g_kwh: float = 713.0
    energy_kwh:      float = 0.0
    co2_grams:       float = 0.0
    co2_mg:          float = 0.0
    runtime_ms:      float = 0.0
    grade:           str   = "A+"
    equivalent:      str   = ""


def _grade(co2_grams: float) -> str:
    """Letter grade for carbon footprint — A+ (greenest) to F (most expensive)."""
    if co2_grams < 0.000001:   return "A+"
    if co2_grams < 0.00001:    return "A"
    if co2_grams < 0.0001:     return "B"
    if co2_grams < 0.001:      return "C"
    if co2_grams < 0.01:       return "D"
    return "F"


def _human_equivalent(co2_grams: float) -> str:
    if co2_grams < 0.000001:
        return "Less than sending one email"
    elif co2_grams < 0.001:
        return f"≈ {co2_grams * 1000:.4f} mg CO₂ — like leaving an LED on for a second"
    elif co2_grams < 1.0:
        return f"≈ {co2_grams * 1000:.2f} mg CO₂ — like browsing 1–2 web pages"
    else:
        return f"≈ {co2_grams:.4f} g CO₂ — like watching ~30 seconds of video"


def estimate(rapl: RaplResult, country_code: str = "IN") -> CarbonResult:
    code      = country_code.upper()
    intensity = _CARBON_INTENSITY.get(code, _CARBON_INTENSITY["WORLD"])
    name      = _COUNTRY_NAMES.get(code, code)

    kwh       = rapl.total_energy_j / 3_600_000.0
    co2_grams = kwh * intensity
    co2_mg    = co2_grams * 1000.0

    return CarbonResult(
        country_code    = code,
        country_name    = name,
        intensity_g_kwh = intensity,
        energy_kwh      = round(kwh,       12),
        co2_grams       = round(co2_grams,  8),
        co2_mg          = round(co2_mg,     6),
        runtime_ms      = rapl.runtime_ms,
        grade           = _grade(co2_grams),
        equivalent      = _human_equivalent(co2_grams),
    )


def to_dict(result: CarbonResult) -> dict:
    # Names must match JS: c.co2_grams, c.kwh_used, c.runtime_ms, c.grade, c.equivalent
    return {
        "country_code":    result.country_code,
        "country_name":    result.country_name,
        "intensity_g_kwh": result.intensity_g_kwh,
        "co2_grams":       result.co2_grams,
        "co2_mg":          result.co2_mg,
        "kwh_used":        result.energy_kwh,   # JS reads c.kwh_used
        "runtime_ms":      result.runtime_ms,   # JS reads c.runtime_ms
        "grade":           result.grade,        # JS reads c.grade
        "equivalent":      result.equivalent,   # JS reads c.equivalent
    }

"""Emission factor library: match a factor to a place, a time and a caliber.

Different databases publish different factors for the same electricity.
Picking one silently is the most common error in carbon accounting, so this
module returns the ranked candidates and the spread between them, not just a
single number.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "samples" / "factors.json"

# 越靠前越优先：地理越贴近、时间粒度越细，越可信
_REGION_RANK = {"CN-SC": 0, "CN-CSG": 1, "CN": 2}


def _load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def match(region: str, hour_start: str, *, scope: str = "average") -> dict:
    """Rank the factors applicable to one region and hour.

    Preference order: same region before parent grid; hourly before annual;
    same year before older. Every candidate is returned so the caller can see
    what was rejected and by how much the choices differ.
    """
    year = datetime.fromisoformat(hour_start).year
    lib = _load()["factors"]

    scored = []
    for f in lib:
        if f["region"] not in _REGION_RANK:
            continue
        if f["scope"] != scope:
            continue
        scored.append({
            **f,
            "_region_rank": _REGION_RANK[f["region"]],
            "_year_gap": abs(f["year"] - year),
            "_is_hourly": f["granularity_s"] <= 3600,
        })

    if not scored:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": f"no factor for region={region} scope={scope}"}

    scored.sort(key=lambda f: (f["_region_rank"], not f["_is_hourly"],
                               f["_year_gap"]))
    best = scored[0]
    values = [f["ef_gco2e_per_kwh"] for f in scored]
    spread = max(values) - min(values)

    candidates = [{
        "factor_id": f["factor_id"], "region": f["region"],
        "region_name": f["region_name"], "year": f["year"],
        "granularity_s": f["granularity_s"],
        "ef_gco2e_per_kwh": f["ef_gco2e_per_kwh"],
        "source": f["source"], "status": f["status"],
        "selected": f["factor_id"] == best["factor_id"],
        "delta_vs_selected_pct": round(
            (f["ef_gco2e_per_kwh"] - best["ef_gco2e_per_kwh"])
            / best["ef_gco2e_per_kwh"] * 100, 1),
        "value_status": "measured",
    } for f in scored]

    return {
        "points": candidates,
        "selected_factor_id": best["factor_id"],
        "selected_ef_gco2e_per_kwh": best["ef_gco2e_per_kwh"],
        "spread_gco2e_per_kwh": round(spread, 1),
        "spread_pct_of_selected": round(spread / best["ef_gco2e_per_kwh"] * 100, 1),
        "selection_rule": "region proximity > time granularity > year gap",
        "all_placeholder": all(f["status"] == "placeholder" for f in scored),
        "expected": len(scored), "grade": "B",
    }

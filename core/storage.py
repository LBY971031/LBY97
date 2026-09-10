"""Net carbon effect of the battery.

A battery does not reduce carbon by existing. It shifts electricity in time
and loses a slice to round-trip inefficiency. If it charges when the grid is
clean and discharges when the grid is dirty, it can INCREASE emissions:

    net = E_out x (EF_discharge - EF_charge / efficiency)

The sign of that expression is the whole point, so this module never takes
the absolute value or clamps it at zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import factor as core_factor
from . import hour as core_hour


def net_carbon(hour_start: str, *, region: str = "CN-SC") -> dict:
    """Charge, discharge, losses and the resulting carbon change."""
    w_from = datetime.fromisoformat(hour_start)
    w_to = w_from + timedelta(hours=1)
    d = core_hour._load()
    st = d.get("storage")
    if not st:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": "no storage data"}

    samples = [s for s in st["samples"]
               if w_from <= datetime.fromisoformat(s["ts_start"]) < w_to]
    if not samples:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": "no storage samples in this hour"}

    step_h = ((datetime.fromisoformat(samples[0]["ts_end"])
               - datetime.fromisoformat(samples[0]["ts_start"])).total_seconds()
              / 3600)
    eta = st["round_trip_efficiency"]

    charged = round(sum(-s["power_kw"] * step_h
                        for s in samples if s["power_kw"] < 0), 4)
    discharged = round(sum(s["power_kw"] * step_h
                           for s in samples if s["power_kw"] > 0), 4)

    # 本小时内因子只有一个值，充放电因子相同；跨时段调度时两者会不同，
    # 那时这个公式才会显出储能可能增碳。
    fm = core_factor.match(region, hour_start)
    ef = fm.get("selected_ef_gco2e_per_kwh")
    if ef is None:
        return {"points": [], "expected": 1, "grade": "D",
                "reason": "no applicable emission factor"}
    ef_charge = ef_discharge = ef

    # 符号约定：正 = 净减碳，负 = 净增碳。
    #   放电抵消的排放  = E_out x EF_discharge
    #   为此充电的排放  = (E_out / eta) x EF_charge
    #   净减碳 = 前者 - 后者 = E_out x (EF_discharge - EF_charge / eta)
    # 因子相同时该式必为负：效率损失意味着充进去的电多于放出来的，
    # 储能在这种情形下是增碳的。这正是要算出来的东西，不能取绝对值。
    net_reduction = round(discharged * (ef_discharge - ef_charge / eta), 1)
    loss = round(charged * (1 - eta), 4)

    return {
        "points": [{**s, "energy_kwh": round(abs(s["power_kw"]) * step_h, 4)}
                   for s in samples],
        "charged_kwh": charged, "discharged_kwh": discharged,
        "round_trip_efficiency": eta,
        "loss_kwh": loss,
        "ef_charge_gco2e_per_kwh": ef_charge,
        "ef_discharge_gco2e_per_kwh": ef_discharge,
        "net_reduction_gco2e": net_reduction,
        "sign_convention": "positive = reduction, negative = increase",
        "is_net_increase": net_reduction < 0,
        "verdict": ("净增碳：因子相同，效率损失使充进的电多于放出的电"
                    if net_reduction < 0 else
                    "净减碳" if net_reduction > 0 else "无净效果"),
        "expected": len(samples), "grade": "B",
        "caliber": {"formula": "E_out x (EF_discharge - EF_charge / eta)",
                    "factor_id": fm.get("selected_factor_id"),
                    "same_hour_charge_and_discharge": True,
                    "note": "跨时段调度时充放电因子不同，需按各自时段取因子"},
    }

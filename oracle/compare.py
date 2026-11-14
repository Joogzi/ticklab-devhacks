"""Trace comparator: expected (oracle) vs actual (candidate) ticklab.trace/1 records."""
from __future__ import annotations

import math
import tomllib
from pathlib import Path

TOL_PATH = Path(__file__).resolve().parent / "tolerance.toml"


def load_tolerance(path: Path = TOL_PATH) -> dict:
    with open(path, "rb") as f:
        t = tomllib.load(f)
    return {"default": float(t["default"]["abs"]), "fields": {k: float(v) for k, v in t.get("fields", {}).items()},
            "exact": set(t.get("exact", {}).get("fields", []))}


def _records(trace: list[dict]) -> list[dict]:
    return [r for r in trace if "tick" in r]


def compare(expected: list[dict], actual: list[dict], tol: dict | None = None, fields: list[str] | None = None) -> dict:
    """Compare two traces (header lines are ignored). Returns a JSON-serializable result."""
    tol = tol or load_tolerance()
    exp, act = _records(expected), _records(actual)
    if fields is None:
        ef = set().union(*(r.keys() for r in exp)) if exp else set()
        af = set().union(*(r.keys() for r in act)) if act else set()
        fields = sorted((ef & af) - {"tick"})
    res = {"status": "match", "fields": fields, "ticks_expected": len(exp), "ticks_actual": len(act),
           "first_divergence": None, "max_delta": {f: 0.0 for f in fields if f not in tol["exact"]},
           "diverging_ticks": 0, "window": None, "problems": []}
    if len(exp) != len(act):
        res["problems"].append(f"length mismatch: expected {len(exp)} ticks, got {len(act)}")
    first, last = None, None
    for i, (e, a) in enumerate(zip(exp, act)):
        bad = False
        for f in fields:
            ev, av = e.get(f), a.get(f)
            if f in tol["exact"]:
                if ev != av:
                    bad = True
                    if first is None:
                        first = {"tick": e.get("tick", i), "field": f, "expected": ev, "actual": av, "delta": None}
                continue
            try:
                d = abs(float(av) - float(ev))
            except (TypeError, ValueError):
                d = math.inf
            if math.isnan(d):
                d = math.inf
            if d > res["max_delta"][f]:
                res["max_delta"][f] = d
            if d > tol["fields"].get(f, tol["default"]):
                bad = True
                if first is None:
                    first = {"tick": e.get("tick", i), "field": f, "expected": ev, "actual": av, "delta": d}
        if bad:
            res["diverging_ticks"] += 1
            last = e.get("tick", i)
    if first is not None:
        res["status"] = "diverge"
        res["first_divergence"] = first
        res["window"] = [first["tick"], last]
    elif res["problems"]:
        res["status"] = "diverge"
    res["max_delta"] = {k: (v if math.isfinite(v) else "inf") for k, v in res["max_delta"].items()}
    return res


def max_ratio(result: dict, tol: dict | None = None) -> float:
    """Largest (delta / tolerance) over numeric fields: how far beyond tolerance a divergence is."""
    tol = tol or load_tolerance()
    best = 0.0
    for f, d in result["max_delta"].items():
        d = math.inf if d == "inf" else d
        best = max(best, d / tol["fields"].get(f, tol["default"]))
    fd = result.get("first_divergence")
    if fd and fd["delta"] is None:  # exact-field (boolean/pose) mismatch
        best = max(best, math.inf)
    return best

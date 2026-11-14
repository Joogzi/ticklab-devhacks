"""`python -m factory devpost-fill`: substitute real numbers from results/summary.json into DEVPOST.md (and README.md).

Placeholders `{{key}}` become `<!--fill:key-->value<!--/fill-->`, so re-running refreshes them. Unknown keys are left
as-is and reported (never invent numbers).
"""
from __future__ import annotations

import re

from . import bench, util


def values() -> dict:
    s = bench.summarize()
    C = s.get("conditions", {})
    v = {}
    st = s.get("selftest") or {}
    v["selftest_passed"], v["selftest_total"] = st.get("passed"), st.get("total")
    o = s.get("oracle") or {}
    v["oracle_coverage"] = o.get("coverage_real_vanilla")
    v["oracle_mode"] = o.get("mode")
    for cond in ("baseline", "lab"):
        c = C.get(cond) or {}
        for k in ("runs", "accepted", "acceptance_rate", "false_done_attempts", "mean_attempts", "median_time_to_accept_s",
                  "mean_cost_usd", "total_cost_usd", "runs_with_false_done"):
            v[f"{cond}_{k}"] = c.get(k)
        v[f"{cond}_models"] = ",".join(c.get("models", []))
    if C:
        rows = ["| metric | baseline (no lab) | lab |", "|---|---|---|"]
        for k, label in [("accepted", "accepted by verifier"), ("runs", "runs"), ("false_done_attempts", "false 'done' claims"),
                         ("mean_attempts", "mean attempts"), ("median_time_to_accept_s", "median time to accept (s)"),
                         ("mean_cost_usd", "mean cost per run (USD)")]:
            rows.append(f"| {label} | {(C.get('baseline') or {}).get(k, '-')} | {(C.get('lab') or {}).get(k, '-')} |")
        v["results_table"] = "\n".join(rows)
    return v


def fill(path, vals: dict) -> list[str]:
    text = path.read_text(encoding="utf-8")
    missing = []

    def sub_place(m):
        k = m.group(1)
        if vals.get(k) is None:
            missing.append(k)
            return m.group(0)
        return f"<!--fill:{k}-->{vals[k]}<!--/fill-->"

    text = re.sub(r"\{\{(\w+)\}\}", sub_place, text)

    def sub_marker(m):
        k = m.group(1)
        return f"<!--fill:{k}-->{vals[k]}<!--/fill-->" if vals.get(k) is not None else m.group(0)

    text = re.sub(r"<!--fill:(\w+)-->.*?<!--/fill-->", sub_marker, text, flags=re.S)
    util.write_text(path, text)
    return missing


def main(argv) -> int:
    vals = values()
    for name in ("DEVPOST.md", "README.md"):
        p = util.ROOT / name
        if p.exists():
            miss = fill(p, vals)
            print(f"{name}: filled" + (f"; no data yet for {sorted(set(miss))}" if miss else ""))
    return 0

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
                  "mean_cost_usd", "total_cost_usd", "runs_with_false_done", "fixed_claims", "regressions_in_final_patch",
                  "tamper_suspect_runs", "mean_seconds"):
            v[f"{cond}_{k}"] = c.get(k)
        v[f"{cond}_models"] = ",".join(c.get("models", []))
    v["n_runs"] = s.get("n_records")
    v["n_invalidated"] = s.get("n_invalidated")
    v["n_cases"] = len(s.get("cases", {}))
    BM = s.get("by_model") or {}
    for m, mv in BM.items():
        for cond, c in (mv.get("conditions") or {}).items():
            for k in ("runs", "accepted", "false_done_attempts", "fixed_claims", "median_time_to_accept_s", "mean_cost_usd",
                      "regressions_in_final_patch", "tamper_suspect_runs", "total_cost_usd"):
                v[f"{m}_{cond}_{k}"] = c.get(k)
    v["models"] = " and ".join(BM) if BM else None
    disc = s.get("discovery") or {}
    v["discovery_found"], v["discovery_total"] = disc.get("found"), disc.get("total")
    if BM:
        hdr = "| metric | " + " | ".join(f"{m}: baseline | {m}: lab" for m in BM) + " |"
        rows = [hdr, "|---|" + "---|---|" * len(BM)]
        for k, label in [("accepted", "accepted by the verifier"), ("false_done_attempts", "wrong \"FIXED\" claims"),
                         ("median_time_to_accept_s", "median time to accept (s)"),
                         ("regressions_in_final_patch", "regressions shipped"), ("mean_cost_usd", "mean cost per run (USD)")]:
            cells = []
            for mv in BM.values():
                for cond in ("baseline", "lab"):
                    c = (mv.get("conditions") or {}).get(cond) or {}
                    den = {"accepted": "runs", "false_done_attempts": "fixed_claims"}.get(k)
                    cells.append(f"{c.get(k, '-')}" + (f" / {c.get(den)}" if den and c.get(den) is not None else ""))
            rows.append(f"| {label} | " + " | ".join(cells) + " |")
        v["results_table"] = "\n\n" + "\n".join(rows) + "\n\n"  # blank lines so Markdown renders the table
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

"""`python -m factory bench`: baseline vs lab on the same cases, judged by the same verifier.

  python -m factory bench [--cases a,b] [--conditions baseline,lab] [--trials 1] [--max-runs N] [--resume]
                          [--max-attempts 2] [--attempt-timeout 600] [--model haiku] [--workers 1]
  python -m factory bench --summarize          # (re)write results/summary.json from results/bench.jsonl

Appends one record per run to results/bench.jsonl (append-only; merge files from several machines by concatenation).
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor

from . import bugs, driver, loop, util

BUDGET_CASES = ["b2_sprint_stop_late", "b3_jump_cooldown", "b5_diagonal_input", "b6_air_acceleration",
                "b8_air_friction_timing", "c9_compound_sprint_jump"]
BENCH = util.RESULTS / "bench.jsonl"
_lock = threading.Lock()


def load_all() -> list[dict]:
    return util.read_jsonl(BENCH) if BENCH.exists() else []


def load_records() -> list[dict]:
    """Run records minus any run invalidated by a later append-only {"invalidate": run_id, "reason": ...} line."""
    allr = load_all()
    bad = {r["invalidate"] for r in allr if "invalidate" in r}
    return [r for r in allr if "run_id" in r and r["run_id"] not in bad]


def invalidate(run_id: str, reason: str) -> None:
    with open(BENCH, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"invalidate": run_id, "reason": reason}) + "\n")


def to_record(rec: dict, settings: dict) -> dict:
    atts = rec["attempts"]
    last = atts[-1] if atts else {}
    return {"run_id": rec["run_id"], "case": rec["case"], "condition": rec["condition"], "trial": rec["trial"],
            "model": rec["model"], "accepted": rec["accepted"], "attempts_used": rec["attempts_used"],
            "max_attempts": rec["max_attempts"],
            "claims": [a["claim"] for a in atts], "verdicts": [a["verdict"] for a in atts],
            "failing_gates": [a["failing_gate"] for a in atts],
            "false_done_attempts": sum(1 for a in atts if a["false_done"]),
            "seconds": rec["seconds"], "attempt_seconds": [a["seconds"] for a in atts],
            "time_to_accept_s": round(sum(a["seconds"] for a in atts), 1) if rec["accepted"] else None,
            "cost_usd": rec["cost_usd"], "num_turns": [a.get("num_turns") for a in atts],
            "tokens": [((a.get("usage") or {}).get("output_tokens")) for a in atts],
            "diff_lines": (last.get("diff") or {}).get("added", 0) + (last.get("diff") or {}).get("removed", 0),
            "tamper_suspect": any(a["tamper_suspect"] for a in atts),
            "regressions_final": len(last.get("regressions") or []), "lab_tool_calls": [a.get("lab_tool_calls") for a in atts],
            "timed_out": [a.get("timed_out") for a in atts], "settings": settings}


def summarize(records: list[dict] | None = None) -> dict:
    recs = records if records is not None else load_records()
    out = {"n_records": len(recs), "n_invalidated": sum(1 for r in load_all() if "invalidate" in r),
           "conditions": {}, "cases": {}}
    for cond in ("baseline", "lab"):
        rs = [r for r in recs if r["condition"] == cond]
        if not rs:
            continue
        acc = [r for r in rs if r["accepted"]]
        fixed_claims = sum(c == "FIXED" for r in rs for c in r["claims"])
        false_done = sum(r["false_done_attempts"] for r in rs)
        tta = [r["time_to_accept_s"] for r in acc if r["time_to_accept_s"] is not None]
        out["conditions"][cond] = {
            "runs": len(rs), "accepted": len(acc), "acceptance_rate": round(len(acc) / len(rs), 3),
            "fixed_claims": fixed_claims, "false_done_attempts": false_done,
            "false_done_rate": round(false_done / fixed_claims, 3) if fixed_claims else None,
            "runs_with_false_done": sum(1 for r in rs if r["false_done_attempts"]),
            "mean_attempts": round(statistics.mean(r["attempts_used"] for r in rs), 2),
            "median_time_to_accept_s": round(statistics.median(tta), 1) if tta else None,
            "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rs), 3),
            "mean_cost_usd": round(statistics.mean(r["cost_usd"] or 0 for r in rs), 4),
            "mean_seconds": round(statistics.mean(r["seconds"] for r in rs), 1),
            "regressions_in_final_patch": sum(r["regressions_final"] for r in rs),
            "tamper_suspect_runs": sum(1 for r in rs if r["tamper_suspect"]),
            "models": sorted({r["model"] for r in rs})}
    for r in recs:
        c = out["cases"].setdefault(r["case"], {})
        c.setdefault(r["condition"], []).append({"accepted": r["accepted"], "attempts": r["attempts_used"],
                                                 "gates": r["failing_gates"], "claims": r["claims"], "run_id": r["run_id"]})
    sel = util.RESULTS / "selftest.json"
    if sel.exists():
        s = util.read_json(sel)
        out["selftest"] = {"passed": s["passed"], "total": s["total"]}
    cal = util.RESULTS / "calibration.json"
    if cal.exists():
        c = util.read_json(cal)
        out["oracle"] = {"mode": c["mode"], "coverage_real_vanilla": c["oracle_coverage"], "corpus_matched": c["corpus_matched"],
                         "dev_goldens_matched": c["dev_goldens_matched"]}
    util.write_json(util.RESULTS / "summary.json", out)
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="factory bench")
    ap.add_argument("--cases", default=",".join(BUDGET_CASES))
    ap.add_argument("--conditions", default="baseline,lab")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--max-runs", type=int, default=0)
    ap.add_argument("--resume", action="store_true", help="skip (case, condition, trial, model) already in bench.jsonl")
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--attempt-timeout", type=float, default=600)
    ap.add_argument("--budget-usd", type=float, default=2.0)
    ap.add_argument("--model", default=driver.DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--invalidate", nargs=2, metavar=("RUN_ID", "REASON"), help="append an invalidation record")
    a = ap.parse_args(argv)
    if a.invalidate:
        invalidate(*a.invalidate)
        print(f"invalidated {a.invalidate[0]}")
        return 0
    if a.summarize:
        print(json.dumps(summarize(), indent=2))
        return 0
    cases = [c for c in a.cases.split(",") if c]
    for c in cases:
        if c not in bugs.case_ids():
            raise SystemExit(f"unknown case {c}")
    done = {(r["case"], r["condition"], r["trial"], r["model"]) for r in load_records()} if a.resume else set()
    todo = [(c, cond, t) for t in range(1, a.trials + 1) for c in cases for cond in a.conditions.split(",")
            if (c, cond, t, a.model) not in done]
    if a.max_runs:
        todo = todo[: a.max_runs]
    settings = {"max_attempts": a.max_attempts, "attempt_timeout": a.attempt_timeout, "budget_usd": a.budget_usd}
    print(f"bench: {len(todo)} run(s) to do: {todo}", flush=True)

    def one(job):
        c, cond, t = job
        rec = loop.run(c, cond, t, a.max_attempts, a.attempt_timeout, a.model, False, [], a.budget_usd, tag="__bench")
        r = to_record(rec, settings)
        with _lock:
            with open(BENCH, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(r) + "\n")
        return r

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for r in ex.map(one, todo):
            print(f"bench: {r['case']} {r['condition']} -> {'ACCEPTED' if r['accepted'] else 'rejected'} "
                  f"in {r['attempts_used']} attempt(s), ${r['cost_usd']}", flush=True)
    s = summarize()
    print(json.dumps(s["conditions"], indent=2))
    return 0

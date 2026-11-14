"""Lab MCP server (stdio, FastMCP), harness-owned, running outside the agent workspace.

Launched by the driver: <venv python> factory/labtools_mcp.py --case <id> --workspace <ws> --store <dir>
Tools run the agent's *current* workspace code (in a subprocess) and compare against the oracle. It never
reveals holdout inputs or whole oracle traces: comparisons return the divergence summary and a small window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from factory import bugs, scenarios, util  # noqa: E402
from oracle import compare  # noqa: E402
from oracle.adapters import scenario_hash  # noqa: E402
from oracle.oracle import Oracle  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--case", required=True)
ap.add_argument("--workspace", required=True)
ap.add_argument("--store", required=True)
ARGS, _ = ap.parse_known_args()
WS = Path(ARGS.workspace)
STORE = Path(ARGS.store)
(STORE / "traces").mkdir(parents=True, exist_ok=True)
(STORE / "repros").mkdir(parents=True, exist_ok=True)
CASE = bugs.load_case(ARGS.case)
ORACLE = Oracle()
RESERVED = {scenario_hash(s) for s in bugs.holdout_corpus() + CASE["hidden"]}
VISIBLE = bugs.visible_corpus()
mcp = FastMCP("lab")


def _log(tool: str, args: dict, result: dict, t0: float) -> None:
    with open(STORE / "tool_calls.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "tool": tool, "args": args, "secs": round(time.time() - t0, 3),
                            "result_status": result.get("status") or result.get("error")}, default=str) + "\n")


def _coerce(scenario) -> tuple[dict | None, str | None]:
    if isinstance(scenario, str):
        try:
            scenario = json.loads(scenario)
        except json.JSONDecodeError as e:
            return None, f"scenario is not valid JSON: {e}"
    if isinstance(scenario, dict):
        scenario = dict(scenario)
        scenario.setdefault("schema_version", 1)
        scenario.setdefault("fixture", "flat_stone_v1")
        scenario.setdefault("actions", [])
        scenario.setdefault("name", "adhoc")
        scenario["actions"] = sorted(scenario["actions"], key=lambda a: a.get("at", 0)) if isinstance(scenario["actions"], list) else scenario["actions"]
    probs = scenarios.validate(scenario)
    return (None, "invalid scenario: " + "; ".join(probs)) if probs else (scenario, None)


def _run_ws(s: dict, init: dict | None = None):
    r = util.run_sims(WS / "sim", [{"scenario": s, "initial_state": init}], timeout=60)[0]
    if not r["ok"]:
        return None, r["error"][-1500:]
    tid = hashlib.sha256(json.dumps(r["trace"], sort_keys=True).encode()).hexdigest()[:10]
    util.write_text(STORE / "traces" / f"{tid}.jsonl", "".join(json.dumps(x) + "\n" for x in r["trace"]))
    return (tid, r["trace"]), None


def _row(r: dict) -> dict:
    return {k: (round(v, 10) if isinstance(v, float) else v) for k, v in r.items()}


@mcp.tool()
def describe_lab() -> str:
    """Explain the lab: oracle, provenance, scenario format, tick semantics and the available tools."""
    n_van = sum(1 for s in [r["scenario"] for r in scenarios.corpus_table()] if ORACLE.has_vanilla(s))
    return (f"TickLab lab for case {CASE['id']}. ORACLE COVERAGE: {n_van} real vanilla scenarios in the corpus.\n"
            "The oracle answers any valid scenario on the flat_stone_v1 fixture (flat stone floor at y=100, player starts at "
            "(0.5,100,0.5), yaw 0 faces +Z, settled on the ground). Answers carry provenance 'vanilla' (recorded from the real "
            "game) or 'reference' (a validated reference model, used where no recording exists).\n"
            "Tick semantics: at the start of tick t, actions with at==t apply; record t = state after tick t.\n"
            "Fields: x,y,z, vx,vy,vz (velocity after the tick), on_ground, yaw, pitch, pose, sprinting, sneaking.\n"
            "Tools: run_scenario, get_trace, compare_with_oracle, save_repro, list_repros, run_regressions. "
            "They always run your CURRENT code in the workspace (sim/src). Tolerance: 1e-7 absolute on positions/velocities.")


@mcp.tool()
def run_scenario(scenario: dict) -> dict:
    """Run your current simulator code on a scenario. Returns a trace id, tick count, final state and a sample of rows."""
    t0 = time.time()
    s, err = _coerce(scenario)
    if err:
        return {"error": err}
    out, err = _run_ws(s)
    if err:
        res = {"error": "simulator crashed", "detail": err}
        _log("run_scenario", {"name": s.get("name")}, res, t0)
        return res
    tid, tr = out
    recs = tr[1:]
    step = max(1, len(recs) // 8)
    res = {"status": "ok", "trace_id": tid, "ticks": len(recs), "final": _row(recs[-1]),
           "sample": [_row(r) for r in recs[::step]][:10]}
    _log("run_scenario", {"name": s.get("name")}, res, t0)
    return res


@mcp.tool()
def get_trace(trace_id: str, start: int = 0, limit: int = 20) -> dict:
    """Return per-tick records [start, start+limit) of a trace produced by run_scenario/compare_with_oracle (your code)."""
    p = STORE / "traces" / f"{Path(trace_id).name}.jsonl"
    if not p.exists():
        return {"error": f"unknown trace id {trace_id}"}
    recs = util.read_jsonl(p)[1:]
    limit = max(1, min(int(limit), 60))
    return {"trace_id": trace_id, "ticks": len(recs), "records": [_row(r) for r in recs[int(start):int(start) + limit]]}


def _compare(s: dict) -> dict:
    if scenario_hash(s) in RESERVED:
        return {"error": "this exact scenario is reserved for verification; vary it (timings/inputs) to investigate"}
    exp, prov, init = ORACLE.expected(s)
    out, err = _run_ws(s, init)
    if err:
        return {"error": "simulator crashed", "detail": err}
    tid, tr = out
    c = compare.compare(exp, tr)
    res = {"status": c["status"], "provenance": prov, "trace_id": tid, "first_divergence": c["first_divergence"],
           "diverging_ticks": c["diverging_ticks"], "window": c["window"],
           "max_delta": {k: (v if isinstance(v, str) else float(f"{v:.3g}")) for k, v in c["max_delta"].items()},
           "problems": c["problems"]}
    if c["first_divergence"]:
        t = c["first_divergence"]["tick"]
        e_rows, a_rows = exp[1:], tr[1:]
        lo, hi = max(0, t - 2), min(len(e_rows), t + 3)
        res["context"] = [{"tick": i, "expected": _row(e_rows[i]), "actual": _row(a_rows[i])} for i in range(lo, hi) if i < len(a_rows)]
    return res


@mcp.tool()
def compare_with_oracle(scenario: dict) -> dict:
    """Run your current code on a scenario and diff against the oracle: first divergence, per-field max deltas,
    diverging window, provenance, and expected-vs-actual rows for a few ticks around the first divergence."""
    t0 = time.time()
    s, err = _coerce(scenario)
    if err:
        return {"error": err}
    res = _compare(s)
    _log("compare_with_oracle", {"name": s.get("name"), "scenario": s}, res, t0)
    return res


@mcp.tool()
def save_repro(name: str, scenario: dict, note: str = "") -> dict:
    """Save a scenario that reproduces the bug. It is stored by the harness (not in your workspace) and the verifier
    will also check it. Returns the current comparison for it."""
    t0 = time.time()
    s, err = _coerce(scenario)
    if err:
        return {"error": err}
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "_-")[:48] or "repro"
    s["name"] = safe
    cmp_ = _compare(s)
    if "error" in cmp_:
        return cmp_
    util.write_json(STORE / "repros" / f"{safe}.json", {"name": safe, "scenario": s, "note": str(note)[:500],
                                                         "status_at_save": cmp_["status"], "first_divergence": cmp_["first_divergence"]})
    res = {"saved": safe, "status": cmp_["status"], "first_divergence": cmp_["first_divergence"], "provenance": cmp_["provenance"]}
    _log("save_repro", {"name": safe, "note": note}, res, t0)
    return res


@mcp.tool()
def list_repros() -> list:
    """List saved reproductions."""
    out = []
    for p in sorted((STORE / "repros").glob("*.json")):
        r = util.read_json(p)
        out.append({"name": r["name"], "note": r["note"], "status_at_save": r["status_at_save"]})
    return out


@mcp.tool()
def run_regressions() -> dict:
    """Run the visible regression suite (visible corpus scenarios + your saved repros) and the unit tests on your current code."""
    t0 = time.time()
    from factory.check import run_unit_tests
    scens = VISIBLE + [util.read_json(p)["scenario"] for p in sorted((STORE / "repros").glob("*.json"))]
    exp = ORACLE.expected_many(scens)
    runs = util.run_sims(WS / "sim", [{"scenario": s, "initial_state": e[2]} for s, e in zip(scens, exp)], timeout=120)
    fails = []
    for s, (etr, prov, _), r in zip(scens, exp, runs):
        if not r["ok"]:
            fails.append({"scenario": s["name"], "error": r["error"][-300:]})
            continue
        c = compare.compare(etr, r["trace"])
        if c["status"] != "match":
            fails.append({"scenario": s["name"], "provenance": prov, "first_divergence": c["first_divergence"]})
    ok, tail = run_unit_tests(WS / "sim")
    res = {"status": "pass" if not fails and ok else "fail", "scenarios": len(scens), "failing": fails[:10],
           "failing_count": len(fails), "unit_tests": "pass" if ok else f"fail: {tail}"}
    _log("run_regressions", {}, res, t0)
    return res


if __name__ == "__main__":
    mcp.run()

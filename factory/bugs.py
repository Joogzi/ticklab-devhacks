"""Seeded-bug cases (harness-private): materialize buggy/fixed/trap sims and check construction rules.

  python -m factory bugs list
  python -m factory bugs check          # every bug passes unit tests yet diverges >= 100x tolerance
  python -m factory bugs show <id>
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from oracle import compare
from oracle.oracle import Oracle

from . import patchutil, scenarios, util

RATIO_MIN = 100.0


def case_ids() -> list[str]:
    return util.read_json(util.BUGS / "cases.json")["cases"]


def load_case(cid: str) -> dict:
    d = util.BUGS / cid
    c = util.read_json(d / "case.json")
    c["dir"] = d
    c["bug_patch"] = (d / "bug.patch").read_text(encoding="utf-8")
    c["fix_patch"] = (d / "fix.patch").read_text(encoding="utf-8")
    c["trap_patch"] = (d / "trap.patch").read_text(encoding="utf-8") if (d / "trap.patch").exists() else None
    c["hidden"] = [util.read_json(p) for p in sorted((d / "hidden").glob("*.json"))]
    return c


def copy_pristine_sim(dest_root: Path) -> Path:
    """Copy sim/ (src + tests, no caches) to dest_root/sim; returns the sim dir."""
    dst = Path(dest_root) / "sim"
    shutil.copytree(util.SIM, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "target"))
    return dst


def materialize(cid: str, dest_root: Path, extra_patch: str | None = None) -> Path:
    """dest_root/sim = pristine + bug patch (+ extra patch, e.g. fix or trap). Returns sim dir."""
    c = load_case(cid)
    sim = copy_pristine_sim(dest_root)
    patchutil.apply(dest_root, c["bug_patch"])
    if extra_patch:
        patchutil.apply(dest_root, extra_patch)
    return sim


def visible_corpus() -> list[dict]:
    split = util.read_json(util.ORACLE / "split.json")
    vis = {s["name"] for s in split["scenarios"] if s["split"] == "visible"}
    return [r["scenario"] for r in scenarios.corpus_table() if r["name"] in vis]


def holdout_corpus() -> list[dict]:
    split = util.read_json(util.ORACLE / "split.json")
    hold = {s["name"] for s in split["scenarios"] if s["split"] == "holdout"}
    return [r["scenario"] for r in scenarios.corpus_table() if r["name"] in hold]


def divergences(sim_dir: Path, scens: list[dict], oracle: Oracle) -> dict:
    """name -> {status, ratio, first_divergence, provenance} comparing a sim against the oracle."""
    exp = oracle.expected_many(scens)
    runs = util.run_sims(sim_dir, [{"scenario": s, "initial_state": e[2]} for s, e in zip(scens, exp)])
    tol = compare.load_tolerance()
    out = {}
    for s, (etr, prov, _), r in zip(scens, exp, runs):
        if not r["ok"]:
            out[s["name"]] = {"status": "error", "ratio": float("inf"), "error": r["error"][-300:], "provenance": prov}
            continue
        res = compare.compare(etr, r["trace"], tol)
        out[s["name"]] = {"status": res["status"], "ratio": compare.max_ratio(res, tol),
                          "first_divergence": res["first_divergence"], "provenance": prov}
    return out


def check_case(cid: str, oracle: Oracle) -> dict:
    from .check import run_unit_tests

    c = load_case(cid)
    rep = {"id": cid, "problems": []}
    all_corpus = [r["scenario"] for r in scenarios.corpus_table()]
    with tempfile.TemporaryDirectory(prefix="tlb_") as td:
        sim = materialize(cid, Path(td) / "bug")
        ok, tail = run_unit_tests(sim)
        rep["unit_tests_pass"] = ok
        if not ok:
            rep["problems"].append(f"buggy sim fails visible unit tests: {tail}")
        repro = [s for s in all_corpus if s["name"] in c["repro_scenarios"]]
        div = divergences(sim, all_corpus + c["hidden"], oracle)
        rep["repro"] = {n: div[n]["ratio"] for n in c["repro_scenarios"]}
        for n, r in rep["repro"].items():
            if not r >= RATIO_MIN:
                rep["problems"].append(f"repro {n} diverges only {r:.1f}x tolerance (< {RATIO_MIN}x)")
        if len(repro) != len(c["repro_scenarios"]):
            rep["problems"].append("repro scenario not in corpus table")
        rep["corpus_hits"] = sorted(n for n in div if div[n]["ratio"] >= RATIO_MIN and n in {s["name"] for s in all_corpus})
        rep["hidden_hits"] = sorted(n for n in div if div[n]["ratio"] >= RATIO_MIN and n in c["hidden_variants"])
        rep["vanilla_hits"] = sorted(n for n in rep["corpus_hits"] if div[n]["provenance"] == "vanilla")
        # the reference fix must restore the pristine sources exactly
        fixed = materialize(cid, Path(td) / "fix", c["fix_patch"])
        for p in sorted((util.SIM / "src").rglob("*.py")):
            q = fixed / "src" / p.relative_to(util.SIM / "src")
            if not q.exists() or q.read_bytes().replace(b"\r\n", b"\n") != p.read_bytes().replace(b"\r\n", b"\n"):
                rep["problems"].append(f"fix.patch does not restore {p.relative_to(util.ROOT)}")
        if c["trap_patch"]:
            trap = materialize(cid, Path(td) / "trap", c["trap_patch"])
            tdiv = divergences(trap, all_corpus + c["hidden"], oracle)
            rep["trap_hits"] = sorted(n for n in tdiv if tdiv[n]["ratio"] >= RATIO_MIN)
            rep["trap_repro_ok"] = all(tdiv[n]["status"] == "match" for n in c["repro_scenarios"])
            if not rep["trap_hits"]:
                rep["problems"].append("trap patch is indistinguishable from the oracle (not a trap)")
    util.write_json(c["dir"] / "coverage.json", {k: v for k, v in rep.items() if k not in ("problems",)})
    return rep


def check_all(verbose=True) -> list[dict]:
    o = Oracle()
    reps = [check_case(cid, o) for cid in case_ids()]
    if verbose:
        print(f"{'case':28} {'unit':5} {'repro ratio':>12} {'corpus hits':>11} {'vanilla':>7} {'hidden':>6}  trap")
        for r in reps:
            rr = min(r["repro"].values()) if r["repro"] else 0
            trap = "-" if "trap_hits" not in r else f"{len(r['trap_hits'])} hits, passes repro={r['trap_repro_ok']}"
            print(f"{r['id']:28} {'ok' if r['unit_tests_pass'] else 'FAIL':5} {rr:12.3g} {len(r['corpus_hits']):11} "
                  f"{len(r['vanilla_hits']):7} {len(r['hidden_hits']):6}  {trap}")
            for p in r["problems"]:
                print("   PROBLEM:", p)
    return reps


def check_gate():
    reps = check_all(verbose=False)
    bad = [(r["id"], r["problems"][0]) for r in reps if r["problems"]]
    if bad:
        return "FAIL", f"{len(bad)} case(s) violate construction rules: {bad[:2]}"
    plaus = sum(1 for c in case_ids() if load_case(c).get("plausible"))
    traps = sum(1 for r in reps if "trap_hits" in r)
    return "PASS", (f"{len(reps)} cases: all pass unit tests, repros diverge >= {RATIO_MIN:.0f}x; "
                    f"{plaus} plausible-looking, {traps} traps")


def main(argv) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for cid in case_ids():
            c = load_case(cid)
            print(f"{cid:28} {c['name']}  families={c['families']} trap={c['trap']}")
        return 0
    if cmd == "check":
        reps = check_all()
        return 1 if any(r["problems"] for r in reps) else 0
    if cmd == "show":
        c = load_case(argv[1])
        print(json.dumps({k: v for k, v in c.items() if k not in ("dir", "hidden")}, indent=2, default=str))
        return 0
    print(__doc__)
    return 2

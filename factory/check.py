"""`python -m factory check`: fast, LLM-free, network-free health check. One table; non-zero exit on any FAIL.

A gate whose component does not exist yet reports SKIPPED, never PASS.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time

from . import util


def run_unit_tests(sim_dir) -> tuple[bool, str]:
    cmd, env = util.sim_cmd(sim_dir)
    p = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=sim_dir, env=env,
                       capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=120)
    tail = (p.stderr or p.stdout).strip().splitlines()
    return p.returncode == 0, " / ".join(l for l in tail[-3:] if l.strip())


def g_tools():
    from . import doctor
    i = doctor.gather()
    missing = [k for k in ("python", "git") if not i.get(k)]
    note = f"python {i['python']}, mcp {i['mcp']}, claude {i['claude_version']}, javac={'yes' if i['javac'] else 'no'}"
    if not missing and not (i.get("mcp") and i.get("claude")):
        note += " (agent runs need the claude CLI + `mcp`; everything else works without them)"
    return ("FAIL", f"missing {missing}; {note}") if missing else ("PASS", note)


def g_sim_tests():
    ok, tail = run_unit_tests(util.SIM)
    return ("PASS" if ok else "FAIL", tail)


def g_scenarios():
    from . import scenarios
    rows = scenarios.corpus_table()
    bad = [(r["name"], scenarios.validate(r["scenario"])) for r in rows if scenarios.validate(r["scenario"])]
    if bad:
        return "FAIL", f"invalid: {bad[:2]}"
    on_disk = util.read_json(util.ORACLE / "corpus_scenarios.json")["scenarios"] if (util.ORACLE / "corpus_scenarios.json").exists() else None
    if on_disk != rows:
        return "FAIL", "oracle/corpus_scenarios.json is stale (run python -m factory.scenarios)"
    sys.path.insert(0, str(util.SIM / "src"))
    from mcsim.main import simulate  # pristine sim, in-process for speed
    off = []
    for r in rows:
        recs = simulate(r["scenario"])[1:]
        if any(t["y"] < 100 - 1e-6 or abs(t["x"]) > 47 or abs(t["z"]) > 47 for t in recs):
            off.append(r["name"])
    if off:
        return "FAIL", f"pristine sim leaves the floor in {off}"
    return "PASS", f"{len(rows)} scenarios valid; pristine stays on the floor"


def g_calibrate():
    from . import calibrate
    r = calibrate.run(verbose=False)
    n_c, n_g = len(r["corpus"]), len(r["dev_goldens"])
    if n_c == 0 and n_g == 0:
        prev = util.RESULTS / "calibration.json"
        note = ""
        if prev.exists():
            c = util.read_json(prev)
            note = f"; committed evidence results/calibration.json: dev goldens {c.get('dev_goldens_matched')}/{len(c.get('dev_goldens', []))} matched"
        return "SKIPPED", "no real vanilla traces in this checkout (corpus not captured yet; dev goldens are not redistributed)" + note
    bad = [x["name"] for x in r["corpus"] + r["dev_goldens"] if x["status"] != "match"]
    msg = (f"ORACLE COVERAGE: {n_c} real vanilla scenarios ({r['mode']}); corpus {r['corpus_matched']}/{n_c}, "
           f"dev goldens {r['dev_goldens_matched']}/{n_g}")
    return ("FAIL", msg + f"; diverging: {bad[:4]}") if bad else ("PASS", msg)


def g_corpus_schema():
    files = sorted(util.CORPUS.glob("*.jsonl")) if util.CORPUS.exists() else []
    if not files:
        return "SKIPPED", "no corpus yet (thin mode)"
    from . import corpus_check
    probs = corpus_check.validate_corpus()
    return ("FAIL", "; ".join(probs[:3])) if probs else ("PASS", f"{len(files)} traces valid; INDEX.json consistent")


def _module(name):
    return importlib.util.find_spec(name) is not None


def g_bugs():
    if not (util.BUGS / "cases.json").exists() or not _module("factory.bugs"):
        return "SKIPPED", "seeded bugs not built yet (Phase 2)"
    from . import bugs
    return bugs.check_gate()


def g_selftest():
    if not _module("factory.selftest"):
        return "SKIPPED", "selftest not built yet (Phase 3)"
    from . import selftest
    return selftest.fast_gate()


def g_harness_tests():
    tdir = util.ROOT / "tests"
    if not tdir.exists():
        return "SKIPPED", "harness tests not written yet"
    p = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=util.ROOT,
                       capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=180)
    tail = (p.stderr or p.stdout).strip().splitlines()
    return ("PASS" if p.returncode == 0 else "FAIL", " / ".join(l for l in tail[-3:] if l.strip()))


DOCS = ["README.md"]


def g_docs():
    missing = [d if isinstance(d, str) else d[1] for d in DOCS
               if not any((util.ROOT / x).exists() for x in ((d,) if isinstance(d, str) else d))]
    if missing and not _module("factory.selftest"):  # drafts are due at the end of Phase 3
        return "SKIPPED", f"drafts not written yet: {missing}"
    return ("FAIL", f"missing {missing}") if missing else ("PASS", "all present")


def g_git():
    p = subprocess.run(["git", "status", "--porcelain"], cwd=util.ROOT, capture_output=True, stdin=subprocess.DEVNULL, text=True)
    if p.returncode != 0:
        return "FAIL", "not a git repository"
    n = len([l for l in p.stdout.splitlines() if l.strip()])
    head = subprocess.run(["git", "log", "--oneline", "-1"], cwd=util.ROOT, capture_output=True, stdin=subprocess.DEVNULL, text=True).stdout.strip()
    return "PASS", f"HEAD {head[:60]}; {n} uncommitted path(s)"


GATES = [("tools (doctor)", g_tools), ("sim unit tests", g_sim_tests), ("corpus scenarios", g_scenarios),
         ("calibrate", g_calibrate), ("corpus schema", g_corpus_schema), ("seeded bugs", g_bugs),
         ("selftest (fast)", g_selftest), ("harness tests", g_harness_tests), ("docs", g_docs), ("git", g_git)]


def main(argv) -> int:
    t0 = time.time()
    rows, fail = [], False
    for name, fn in GATES:
        t = time.time()
        try:
            st, why = fn()
        except Exception as e:  # a crashing gate is a failing gate
            st, why = "FAIL", f"{type(e).__name__}: {e}"
        fail |= st == "FAIL"
        rows.append((name, st, why, time.time() - t))
    print(f"{'gate':18} {'status':8} {'secs':>5}  reason")
    for name, st, why, dt in rows:
        print(f"{name:18} {st:8} {dt:5.1f}  {why}")
    print(f"overall: {'FAIL' if fail else 'PASS'} ({time.time() - t0:.1f}s)")
    return 1 if fail else 0

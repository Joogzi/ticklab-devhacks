"""`python -m factory run --case C --condition lab|baseline [--interactive | --note "..." | --notes-file F]`

Up to MAX_ATTEMPTS fresh agent invocations. After each: extract the diff, scan the tool log, run the verifier
(independent of the agent's STATUS claim), then accept or write identical feedback into CASE.md and retry.
--interactive (lab): pauses after an investigation phase (agent must save_repro), and after each rejection, for a
developer note on stdin. Benchmark runs receive no notes.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import bugs, driver, integrity, util, verifier, workspace

FIX_PROMPT = ("Read CASE.md in the current directory and fix the bug it describes. Follow its rules: edit only files "
              "under sim/src/, run the simulator and unit tests to check your work{lab}. When you are done, end your final "
              "message with exactly one line: STATUS: FIXED or STATUS: UNABLE.")
INVESTIGATE_PROMPT = ("Read CASE.md. This is the INVESTIGATION phase only: do not edit any files. Use the lab tools to "
                      "reproduce the reported problem, find a scenario that diverges from the oracle, save it with "
                      "save_repro, and summarize the divergence (tick, field, expected vs actual) and your hypothesis. "
                      "End with the line STATUS: UNABLE (the fix happens in the next phase).")


def agent_repros(run_dir: Path) -> list[dict]:
    d = run_dir / "store" / "repros"
    return [util.read_json(p)["scenario"] for p in sorted(d.glob("*.json"))] if d.exists() else []


def ask_note(prompt: str, args) -> str | None:
    if args.note_queue:
        return args.note_queue.pop(0)
    if not args.interactive:
        return None
    print("\n" + prompt + "\n(type a developer note and press Enter; empty = no note)", flush=True)
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return None
    return line.strip() or None


def run(case_id: str, condition: str, trial: int = 1, max_attempts: int = 3, attempt_timeout: float = 600,
        model: str | None = None, interactive: bool = False, notes: list[str] | None = None, budget_usd: float = 2.0,
        tag: str = "") -> dict:
    class A:  # tiny args holder
        pass
    args = A()
    args.interactive, args.note_queue = interactive, list(notes or [])
    case = bugs.load_case(case_id)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{case_id}__{condition}-{trial}__{stamp}{tag}"
    run_dir = util.RUNS / run_id
    run_dir.mkdir(parents=True)
    ws = workspace.create(case_id, condition, trial)
    protected = integrity.manifest()
    dev_notes: list[str] = []
    history: list[dict] = []
    rec = {"run_id": run_id, "case": case_id, "condition": condition, "trial": trial, "model": model or driver.DEFAULT_MODEL,
           "max_attempts": max_attempts, "workspace": str(ws), "started": stamp, "attempts": [], "accepted": False,
           "interactive": interactive, "notes": dev_notes}
    t_run = time.time()
    lab = " (and use the lab tools to compare against the oracle)" if condition == "lab" else ""

    if interactive and condition == "lab":
        workspace.write_case_md(ws, case, condition, 1, max_attempts, dev_notes, history)
        inv = driver.run_attempt(ws, INVESTIGATE_PROMPT, condition, case_id, run_dir, "investigate", model, attempt_timeout, budget_usd)
        reps = agent_repros(run_dir)
        print(f"\n=== investigation done ({inv['seconds']}s, {inv['lab_tool_calls']} lab calls); repros saved: {[r['name'] for r in reps]}")
        print(inv["final_text"][-1500:])
        rec["investigation"] = inv
        if workspace.extract_diff(ws).strip():
            print("(note: the agent edited files during investigation; edits are kept and verified later)")
        n = ask_note("Developer: any steering note for the fix phase?", args)
        if n:
            dev_notes.append(n)

    for attempt in range(1, max_attempts + 1):
        workspace.write_case_md(ws, case, condition, attempt, max_attempts, dev_notes, history)
        a = driver.run_attempt(ws, FIX_PROMPT.format(lab=lab), condition, case_id, run_dir, f"attempt{attempt}", model,
                               attempt_timeout, budget_usd)
        patch = workspace.extract_diff(ws)
        util.write_text(run_dir / f"attempt{attempt}.patch", patch)
        v = verifier.verify(case_id, patch, agent_repros=agent_repros(run_dir), protected_before=protected,
                            tool_scan=a["tool_scan"], out_path=run_dir / f"attempt{attempt}.verdict.json")
        fb = verifier.feedback(v)
        a.update({"attempt": attempt, "verdict": v["verdict"], "accepted": v["accepted"], "failing_gate": v["failing_gate"],
                  "gates": [{k: g[k] for k in ("gate", "status", "detail")} for g in v["gates"]], "diff": v["diff"],
                  "regressions": v["regressions"], "feedback": fb, "tamper_suspect": a["tool_scan"]["tamper_suspect"],
                  "false_done": a["claim"] == "FIXED" and not v["accepted"], "notes_so_far": list(dev_notes)})
        rec["attempts"].append(a)
        print(f"[{case_id} {condition}] attempt {attempt}: agent claimed {a['claim']}; {v['verdict']}"
              + (f" @ {v['failing_gate']}" if v["failing_gate"] else "") + f" ({a['seconds']}s, cost {a['cost_usd']})", flush=True)
        util.write_json(run_dir / "run.json", rec)
        if v["accepted"]:
            rec["accepted"] = True
            break
        history.append({"attempt": attempt, "claim": a["claim"], "feedback": fb})
        if attempt < max_attempts:
            print(v["summary"])
            n = ask_note("Developer: steering note for the next attempt?", args)
            if n:
                dev_notes.append(n)
    rec["seconds"] = round(time.time() - t_run, 1)
    rec["attempts_used"] = len(rec["attempts"])
    rec["cost_usd"] = round(sum((x.get("cost_usd") or 0) for x in rec["attempts"]) + ((rec.get("investigation") or {}).get("cost_usd") or 0), 4)
    rec["finished"] = datetime.now().strftime("%Y%m%d-%H%M%S")
    util.write_json(run_dir / "run.json", rec)
    print(f"=== {run_id}: {'ACCEPTED' if rec['accepted'] else 'NOT ACCEPTED'} after {rec['attempts_used']} attempt(s), "
          f"{rec['seconds']}s, cost ${rec['cost_usd']}")
    return rec


def main(argv) -> int:
    if argv and argv[0] == "--feature":
        feature(argv[1])
        return 0
    ap = argparse.ArgumentParser(prog="factory run")
    ap.add_argument("--case", required=True, choices=bugs.case_ids())
    ap.add_argument("--condition", required=True, choices=["lab", "baseline"])
    ap.add_argument("--trial", type=int, default=1)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--attempt-timeout", type=float, default=600, help="seconds per attempt (wall clock)")
    ap.add_argument("--budget-usd", type=float, default=2.0, help="--max-budget-usd per attempt")
    ap.add_argument("--model", default=None)
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--notes-file")
    a = ap.parse_args(argv)
    notes = list(a.note)
    if a.notes_file:
        notes += [l.strip() for l in Path(a.notes_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    rec = run(a.case, a.condition, a.trial, a.max_attempts, a.attempt_timeout, a.model, a.interactive, notes, a.budget_usd)
    return 0 if rec["accepted"] else 1


def feature(run_id: str) -> None:
    """Copy runs/<run_id> to results/featured/<run_id> (committed; replayed offline by the report/demo)."""
    import shutil
    src = util.RUNS / run_id
    dst = util.RESULTS / "featured" / run_id
    if dst.exists():
        util.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("traces"))
    print(f"featured: {dst}")

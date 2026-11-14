"""Build report/index.html: one self-contained offline file (inline JS/CSS, no CDN) from real data.

Data: runs/*/run.json and results/featured/*/run.json (agent runs), bugs/ (case gallery: buggy vs oracle),
results/{summary,selftest,calibration}.json. Candidate traces are recomputed deterministically from each
attempt's patch, so the report shows exactly what the verifier saw.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from factory import bugs, patchutil, scenarios, util  # noqa: E402
from oracle import compare  # noqa: E402
from oracle.oracle import Oracle  # noqa: E402

FIELDS = ["x", "y", "z", "vx", "vy", "vz", "on_ground", "sprinting", "sneaking", "pose", "yaw"]


def slim(trace: list[dict]) -> dict:
    recs = [r for r in trace if "tick" in r]
    return {f: [r.get(f) for r in recs] for f in FIELDS if recs and f in recs[0]}


def keys_timeline(s: dict) -> list[list[str]]:
    state, out = {}, []
    acts = sorted(s.get("actions", []), key=lambda a: a["at"])
    i = 0
    for t in range(s["duration"]):
        while i < len(acts) and acts[i]["at"] == t:
            if "key" in acts[i]:
                state[acts[i]["key"]] = acts[i]["down"]
            if "yaw" in acts[i]:
                state["yaw=" + str(acts[i]["yaw"])] = True
            i += 1
        out.append(sorted(k for k, v in state.items() if v and not k.startswith("yaw=")))
    return out


def replay_item(oracle: Oracle, s: dict, sims: dict[str, Path]) -> dict:
    exp, prov, init = oracle.expected(s)
    item = {"scenario": s["name"], "provenance": prov, "keys": keys_timeline(s), "oracle": slim(exp), "series": {}}
    for label, sim in sims.items():
        r = util.run_sims(sim, [{"scenario": s, "initial_state": init}])[0]
        if r["ok"]:
            c = compare.compare(exp, r["trace"])
            item["series"][label] = {"trace": slim(r["trace"]), "status": c["status"], "first": c["first_divergence"]}
    return item


def gather_runs() -> list[Path]:
    dirs = []
    for base in (util.RESULTS / "featured", util.RUNS):
        if base.exists():
            dirs += [p.parent for p in sorted(base.glob("*/run.json"))]
    seen, out = set(), []
    for d in dirs:
        if d.name not in seen:
            seen.add(d.name)
            out.append(d)
    return out


def build_runs(oracle: Oracle, limit: int = 40) -> list[dict]:
    out = []
    corpus = {r["name"]: r["scenario"] for r in scenarios.corpus_table()}
    for d in gather_runs()[-limit:]:
        rec = util.read_json(d / "run.json")
        case = bugs.load_case(rec["case"])
        run = {k: rec.get(k) for k in ("run_id", "case", "condition", "trial", "model", "accepted", "attempts_used", "seconds",
                                      "cost_usd", "notes", "interactive")}
        run["featured"] = "featured" in d.parts
        run["report_text"] = case["report"]
        run["attempts"] = []
        with tempfile.TemporaryDirectory(prefix="tlr_") as td:
            buggy = bugs.materialize(rec["case"], Path(td) / "buggy")
            for a in rec["attempts"]:
                n = a["attempt"]
                v = util.read_json(d / f"attempt{n}.verdict.json") if (d / f"attempt{n}.verdict.json").exists() else {}
                patch = (d / f"attempt{n}.patch").read_text(encoding="utf-8") if (d / f"attempt{n}.patch").exists() else ""
                att = {k: a.get(k) for k in ("attempt", "claim", "verdict", "accepted", "failing_gate", "seconds", "cost_usd",
                                             "num_turns", "tool_counts", "lab_tool_calls", "tamper_suspect", "false_done",
                                             "feedback", "diff", "regressions", "notes_so_far")}
                att["gates"] = [{k: g.get(k) for k in ("gate", "status", "detail")} for g in v.get("gates", a.get("gates", []))]
                att["patch"] = patch[:6000]
                names = list(case["repro_scenarios"])
                for g in v.get("gates", []):
                    for f in g.get("failures", []) or []:
                        if f.get("scenario") in corpus and f["scenario"] not in names:
                            names.append(f["scenario"])
                cand = None
                try:
                    root = Path(td) / f"cand{n}"
                    bugs.materialize(rec["case"], root)
                    patchutil.apply(root, patch)
                    cand = root / "sim"
                except Exception as e:
                    att["patch_error"] = str(e)
                sims = {"buggy (before)": buggy}
                if cand:
                    sims["candidate (attempt %d)" % n] = cand
                att["replay"] = [replay_item(oracle, corpus[x], sims) for x in names[:3] if x in corpus]
                run["attempts"].append(att)
        out.append(run)
    return out


def build_gallery(oracle: Oracle) -> list[dict]:
    corpus = {r["name"]: r["scenario"] for r in scenarios.corpus_table()}
    out = []
    with tempfile.TemporaryDirectory(prefix="tlg_") as td:
        for cid in bugs.case_ids():
            c = bugs.load_case(cid)
            sim = bugs.materialize(cid, Path(td) / cid)
            out.append({"case": cid, "name": c["name"], "report": c["report"], "families": c["families"],
                        "replay": [replay_item(oracle, corpus[n], {"buggy": sim}) for n in c["repro_scenarios"]]})
    return out


def main(argv=None) -> int:
    oracle = Oracle()
    data = {"runs": build_runs(oracle), "gallery": build_gallery(oracle),
            "summary": util.read_json(util.RESULTS / "summary.json") if (util.RESULTS / "summary.json").exists() else None,
            "selftest": util.read_json(util.RESULTS / "selftest.json") if (util.RESULTS / "selftest.json").exists() else None,
            "calibration": util.read_json(util.RESULTS / "calibration.json") if (util.RESULTS / "calibration.json").exists() else None}
    cal = data["calibration"] or {}
    data["coverage"] = {"real": cal.get("oracle_coverage", 0), "mode": cal.get("mode", "thin"),
                        "dev_goldens": f"{cal.get('dev_goldens_matched', 0)}/{len(cal.get('dev_goldens', []))}"}
    html = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":"), default=str).replace("</", "<\\/")
    out = ROOT / "report" / "index.html"
    util.write_text(out, html.replace("/*__DATA__*/null", blob))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB): {len(data['runs'])} runs, {len(data['gallery'])} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())

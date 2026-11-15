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
    """Featured runs (always) + runs that are valid records in results/bench.jsonl (superseded runs are excluded)."""
    from factory import bench
    valid = {r["run_id"] for r in bench.load_records()}
    out, seen = [], set()
    for d in sorted((util.RESULTS / "featured").glob("*/run.json")) if (util.RESULTS / "featured").exists() else []:
        out.append(d.parent)
        seen.add(d.parent.name)
    for d in sorted(util.RUNS.glob("*/run.json")) if util.RUNS.exists() else []:
        if d.parent.name in valid and d.parent.name not in seen:
            out.append(d.parent)
            seen.add(d.parent.name)
    return out


def _excerpt(text: str, n: int = 700) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else "…" + text[-n:]


def build_runs(oracle: Oracle) -> list[dict]:
    out = []
    corpus = {r["name"]: r["scenario"] for r in scenarios.corpus_table()}
    for d in gather_runs():
        rec = util.read_json(d / "run.json")
        case = bugs.load_case(rec["case"])
        featured = "featured" in d.parts
        run = {k: rec.get(k) for k in ("run_id", "case", "condition", "trial", "model", "accepted", "attempts_used", "seconds",
                                      "cost_usd", "notes", "interactive")}
        run["featured"] = featured
        run["case_name"] = case["name"]
        run["report_text"] = case["report"]
        run["bench"] = rec["run_id"].endswith("__bench")
        inv = rec.get("investigation")
        repro_files = sorted((d / "store" / "repros").glob("*.json")) if (d / "store" / "repros").exists() else []
        agent_repros = [util.read_json(p) for p in repro_files]
        if inv:
            run["investigation"] = {"seconds": inv.get("seconds"), "lab_tool_calls": inv.get("lab_tool_calls"),
                                    "text": _excerpt(inv.get("final_text"), 900)}
        run["agent_repros"] = [{"name": r["name"], "note": r.get("note", "")} for r in agent_repros]
        run["attempts"] = []
        with tempfile.TemporaryDirectory(prefix="tlr_") as td:
            buggy = bugs.materialize(rec["case"], Path(td) / "buggy") if featured else None
            for a in rec["attempts"]:
                n = a["attempt"]
                v = util.read_json(d / f"attempt{n}.verdict.json") if (d / f"attempt{n}.verdict.json").exists() else {}
                patch = (d / f"attempt{n}.patch").read_text(encoding="utf-8") if (d / f"attempt{n}.patch").exists() else ""
                att = {k: a.get(k) for k in ("attempt", "claim", "verdict", "accepted", "failing_gate", "seconds", "cost_usd",
                                             "num_turns", "tool_counts", "lab_tool_calls", "tamper_suspect", "false_done",
                                             "feedback", "diff", "regressions", "notes_so_far")}
                att["gates"] = [{k: g.get(k) for k in ("gate", "status", "detail")} for g in v.get("gates", a.get("gates", []))]
                att["agent_text"] = _excerpt(a.get("final_text"), 600)
                if featured:
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
                    sims = {"before (buggy)": buggy}
                    if cand:
                        sims["after (attempt %d)" % n] = cand
                    scens = [corpus[x] for x in names[:3] if x in corpus]
                    scens += [dict(r["scenario"], name="agent repro: " + r["name"]) for r in agent_repros[:1]]
                    att["replay"] = [replay_item(oracle, s_, sims) for s_ in scens]
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
            fixed = bugs.materialize(cid, Path(td) / (cid + "_fix"), c["fix_patch"])
            cov = util.read_json(c["dir"] / "coverage.json") if (c["dir"] / "coverage.json").exists() else {}
            out.append({"case": cid, "name": c["name"], "report": c["report"], "families": c["families"],
                        "plausible": c.get("plausible"), "trap": c.get("trap"), "trap_note": c.get("trap_note"),
                        "corpus_hits": len(cov.get("corpus_hits", [])), "vanilla_hits": len(cov.get("vanilla_hits", [])),
                        "fix_patch": c["fix_patch"][:4000],
                        "replay": [replay_item(oracle, corpus[n], {"before (buggy)": sim, "after (reference fix)": fixed})
                                   for n in c["repro_scenarios"]]})
    return out


def build_live() -> list[dict]:
    """Agent-written repro scenarios replayed in real Minecraft (capture/live_confirm.py)."""
    f = util.RESULTS / "live_confirm.json"
    if not f.exists():
        return []
    out = []
    with tempfile.TemporaryDirectory(prefix="tlv_") as td:
        for it in util.read_json(f).get("items", []):
            tp = util.RESULTS / "live_confirm" / f"{it['name']}.jsonl"
            if not tp.exists() or not (util.ROOT / it["patch"]).exists():
                continue
            real = util.read_jsonl(tp)
            sc, init = real[0]["scenario"], real[0]["initial_state"]
            buggy = bugs.materialize(it["case"], Path(td) / (it["name"] + "_b"))
            root = Path(td) / (it["name"] + "_c")
            bugs.materialize(it["case"], root)
            patchutil.apply(root, (util.ROOT / it["patch"]).read_text(encoding="utf-8"))
            item = {"scenario": it["name"], "provenance": "live", "keys": keys_timeline(sc), "oracle": slim(real), "series": {}}
            for label, sim in (("before (buggy)", buggy), (f"after (agent patch, attempt {it['attempt']})", root / "sim")):
                r = util.run_sims(sim, [{"scenario": sc, "initial_state": init}])[0]
                c = compare.compare(real, r["trace"])
                item["series"][label] = {"trace": slim(r["trace"]), "status": c["status"], "first": c["first_divergence"]}
            out.append({**{k: it.get(k) for k in ("name", "case", "run_id", "model", "repro", "attempt")}, "replay": item,
                        "accepted_patch": it["accepted_patch"]["status"], "buggy": it["buggy"]["status"],
                        "reference": it["reference"]["status"]})
    return out


def build_discovery(oracle: Oracle) -> dict | None:
    f = util.RESULTS / "discovery.json"
    if not f.exists():
        return None
    d = util.read_json(f)
    out = {k: d.get(k) for k in ("seed", "count_per_case", "oracle", "recall")}
    out["cases"] = []
    with tempfile.TemporaryDirectory(prefix="tld_") as td:
        for c in d["cases"]:
            row = {k: c[k] for k in ("case", "generated", "valid", "divergent")}
            row["clusters"] = [{k: cl.get(k) for k in ("signature", "count", "raw_size", "min_size", "first_divergence",
                                                         "keys_at_divergence")} for cl in c["clusters"]]
            if c["clusters"]:
                sim = bugs.materialize(c["case"], Path(td) / c["case"])
                m = dict(c["clusters"][0]["minimized"], name="minimal repro")
                row["replay"] = replay_item(oracle, m, {"before (buggy)": sim})
            out["cases"].append(row)
    return out


def _bench_records() -> list[dict]:
    from factory import bench
    keep = ("run_id", "case", "condition", "trial", "model", "accepted", "claims", "failing_gates", "seconds", "cost_usd")
    return [{k: r.get(k) for k in keep} for r in bench.load_records()]


def main(argv=None) -> int:
    oracle = Oracle()
    data = {"runs": build_runs(oracle), "gallery": build_gallery(oracle),
            "summary": util.read_json(util.RESULTS / "summary.json") if (util.RESULTS / "summary.json").exists() else None,
            "selftest": util.read_json(util.RESULTS / "selftest.json") if (util.RESULTS / "selftest.json").exists() else None,
            "calibration": util.read_json(util.RESULTS / "calibration.json") if (util.RESULTS / "calibration.json").exists() else None,
            "families": {r["name"]: r["family"] for r in scenarios.corpus_table()},
            "live": build_live(), "bench_records": _bench_records(), "discovery": build_discovery(oracle),
            "live_rerecord": (util.read_json(util.RESULTS / "live_confirm.json").get("presentation_rerecord")
                              if (util.RESULTS / "live_confirm.json").exists() else None)}
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

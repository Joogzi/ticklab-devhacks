"""Live confirm: replay the scenarios the AGENT wrote (its saved repros) in real Minecraft, then check the agent's
accepted patch against those real recordings.

  python capture/live_confirm.py prepare     # build + install the mod in presentation mode; writes CAPTURE_READY.md
  python capture/live_confirm.py analyze     # after the game closes: real recording vs buggy / accepted patch / reference

The agent never touches Minecraft: the mod replays the agent-authored scenario inputs. This is an extra, independent
check on top of the verifier, and footage for the demo (third-person camera, on-screen captions).
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import build_mod  # noqa: E402
import discover_prism  # noqa: E402
from factory import bugs, patchutil, scenarios, util  # noqa: E402
from oracle import adapters, compare  # noqa: E402
from oracle.oracle import ensure_reference  # noqa: E402

BATCH = "live"
PLAN = HERE / "out" / "live_plan.json"
OUT_JSON = util.RESULTS / "live_confirm.json"
OUT_DIR = util.RESULTS / "live_confirm"


def collect() -> list[dict]:
    """Agent-saved repros from accepted featured runs (one per run), with the accepted attempt's patch."""
    items, seen = [], set()
    for d in sorted((util.RESULTS / "featured").glob("*/run.json")):
        run = util.read_json(d)
        if not run.get("accepted"):
            continue
        acc = next(a for a in run["attempts"] if a.get("accepted"))
        for rp in sorted((d.parent / "store" / "repros").glob("*.json"))[:1]:
            r = util.read_json(rp)
            sc = dict(r["scenario"])
            name = re.sub(r"[^A-Za-z0-9_]", "_", f"live_{run['case'].split('_')[0]}_{r['name']}")[:60]
            if name in seen or scenarios.validate(dict(sc, name=name)):
                continue
            seen.add(name)
            sc["name"] = name
            items.append({"name": name, "case": run["case"], "run_id": run["run_id"], "model": run["model"],
                          "repro": r["name"], "note": r.get("note", ""), "attempt": acc["attempt"],
                          "patch": str((d.parent / f"attempt{acc['attempt']}.patch").relative_to(util.ROOT)).replace("\\", "/"),
                          "scenario": sc})
    return items


def prepare() -> int:
    items = collect()
    if not items:
        print("no accepted featured runs with agent repros")
        return 2
    d = discover_prism.discover()
    if not d["selected"]:
        print("no ticklab Prism instance:", d["problems"])
        return 2
    sel = d["selected"]
    mod_scen = []
    for it in items:
        s = dict(it["scenario"])
        s["_caption"] = f"Agent-written test: {it['repro']}"
        s["_sub"] = f"bug {it['case'].split('_')[0]} · written by the {it['model']} agent · replayed in real Minecraft"
        mod_scen.append({"name": it["name"], "family": "live", "scenario": s})
    corpus_names = []
    if "--no-corpus" not in sys.argv:  # longer footage: all ground-truth movements too (also re-checks determinism)
        for row in scenarios.corpus_table():
            s = dict(row["scenario"])
            s["_caption"] = f"Ground truth: {row['name']}"
            s["_sub"] = f"{row['family']} · real Minecraft 26.3"
            mod_scen.append({"name": row["name"], "family": row["family"], "scenario": s})
            corpus_names.append(row["name"])
    sf = HERE / "out" / "live_scenarios.json"
    util.write_json(sf, {"scenarios": mod_scen})
    util.write_json(PLAN, items)
    util.write_json(HERE / "out" / "live_plan_corpus.json", corpus_names)
    jar = build_mod.compile_mod(sel["classpath"])
    cfg = build_mod.install(sel, jar, BATCH, "listed", 7, [], [],
                            extra={"scenarios_file": str(sf), "presentation": True, "settle_ticks": 60,
                                   "fixture_commands_by_fixture": {
                                       "wall_v1": build_mod.WALL_COMMANDS,
                                       "flat_stone_v1": [c.replace("minecraft:stone", "minecraft:air") for c in build_mod.WALL_COMMANDS]}})
    util.write_text(ROOT / "CAPTURE_READY.md", f"""# CAPTURE_READY — live confirm (recording-friendly)

Start your screen recorder, then in Prism click **Play** on **{sel['name']}** and open the world **ticklab**.
The mod switches to a third-person camera and replays {len(items)} scenario(s) that the agent wrote while debugging,
then {len(corpus_names)} ground-truth movements, each with a small caption. It closes the game when done
(~{(len(items) + len(corpus_names)) * 6 // 60 + 1} min plus loading).
""")
    print(f"installed live-confirm batch: {len(items)} agent-written + {len(corpus_names)} ground-truth scenarios")
    return 0


def analyze() -> int:
    items = util.read_json(PLAN)
    done = util.read_json(HERE / "out" / BATCH / "done.json")
    ref = ensure_reference()
    out = {"captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "minecraft": done.get("minecraft"),
           "note": "Scenario inputs were written by the agent (saved repros); the capture mod replayed them in real Minecraft.",
           "items": []}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.jsonl"):  # results describe the latest capture only
        old.unlink()
    for it in items:
        raw_p = HERE / "out" / BATCH / f"{it['name']}.raw.jsonl"
        if not raw_p.exists():
            out["items"].append({**{k: it[k] for k in ("name", "case", "run_id", "repro")}, "status": "not captured"})
            continue
        raw = [json.loads(l) for l in raw_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        tr = adapters.raw_capture_to_trace(raw, it["scenario"], {"minecraft": done.get("minecraft"), "mod": done.get("mod"),
                                                                 "kind": "live confirm of an agent-written scenario"})
        util.write_text(OUT_DIR / f"{it['name']}.jsonl", adapters.dumps(tr))
        init = tr[0]["initial_state"]
        res = {k: it[k] for k in ("name", "case", "run_id", "model", "repro", "attempt", "patch")}
        with tempfile.TemporaryDirectory(prefix="tll_") as td:
            buggy = bugs.materialize(it["case"], Path(td) / "b")
            root = Path(td) / "c"
            bugs.materialize(it["case"], root)
            patchutil.apply(root, (util.ROOT / it["patch"]).read_text(encoding="utf-8"))
            for label, sim in (("reference", ref), ("buggy", buggy), ("accepted_patch", root / "sim")):
                r = util.run_sims(sim, [{"scenario": it["scenario"], "initial_state": init}])[0]
                c = compare.compare(tr, r["trace"]) if r["ok"] else {"status": "error", "first_divergence": None}
                res[label] = {"status": c["status"], "first_divergence": c.get("first_divergence")}
        out["items"].append(res)
        print(f"{it['name']:44} real vs accepted patch: {res['accepted_patch']['status']:8} | vs buggy: {res['buggy']['status']:8} | vs reference: {res['reference']['status']}")
    cp = HERE / "out" / "live_plan_corpus.json"
    corpus_names = util.read_json(cp) if cp.exists() else []
    if corpus_names:  # presentation mode must not change movement: compare against the committed corpus
        table = {r["name"]: r["scenario"] for r in scenarios.corpus_table()}
        same, diff, missing = 0, [], 0
        for n in corpus_names:
            rp = HERE / "out" / BATCH / f"{n}.raw.jsonl"
            if not rp.exists():
                missing += 1
                continue
            raw = [json.loads(l) for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
            tr = adapters.raw_capture_to_trace(raw, table[n], {})
            ref_tr = util.read_jsonl(util.CORPUS / f"{n}.jsonl")
            body = lambda t: json.dumps(t[0]["initial_state"], sort_keys=True) + adapters.dumps(t[1:])
            if body(tr) == body(ref_tr):
                same += 1
            else:
                diff.append(n)
        out["presentation_rerecord"] = {"scenarios": len(corpus_names), "byte_identical_to_corpus": same,
                                        "different": diff, "missing": missing}
        print(f"ground-truth re-recording in presentation mode: {same}/{len(corpus_names)} byte-identical to the corpus"
              + (f"; different: {diff}" if diff else "") + (f"; missing {missing}" if missing else ""))
    util.write_json(OUT_JSON, out)
    ready = ROOT / "CAPTURE_READY.md"
    if ready.exists():
        ready.unlink()
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    sys.exit(prepare() if cmd == "prepare" else analyze() if cmd == "analyze" else 2)

"""`python -m factory calibrate`: validate the pristine sim against every available vanilla trace.

Sources: oracle/corpus/*.jsonl (the committed vanilla layer) and, for dev-time cross-checks,
oracle/dev_goldens/*.jsonl (converted from the read-only lab/golden; never committed).
Also recomputes the visible/holdout split (oracle/split.json) and bug coverage flags.
"""
from __future__ import annotations

import hashlib
import json
import sys

from oracle import adapters, compare
from oracle.oracle import Oracle, ensure_reference

from . import scenarios, util

GOLDENS = ("idle", "walk", "jump", "look")


def ensure_dev_goldens() -> list:
    src = util.ROOT / "lab" / "golden"
    out = []
    for n in GOLDENS:
        dst = util.DEV_GOLDENS / f"golden_{n}.jsonl"
        if not dst.exists() and (src / f"{n}.json").exists():
            tr = adapters.golden_to_trace(util.read_json(src / f"{n}.json"), f"golden_{n}")
            util.write_text(dst, adapters.dumps(tr))
        if dst.exists():
            out.append(dst)
    return out


def corpus_files() -> list:
    if not util.CORPUS.exists():
        return []
    usable = None
    idx = util.CORPUS / "INDEX.json"
    if idx.exists():
        usable = {s["name"] for s in util.read_json(idx).get("scenarios", []) if s.get("usable")}
    return [p for p in sorted(util.CORPUS.glob("*.jsonl")) if usable is None or p.stem in usable]


def calibrate_trace(path, sim_dir=util.SIM) -> dict:
    tr = util.read_jsonl(path)
    head = tr[0]
    got, _ = util.run_sim(sim_dir, head["scenario"], initial_state=head.get("initial_state"))
    res = compare.compare(tr, got)
    return {"name": head["name"], "file": str(path.relative_to(util.ROOT)).replace("\\", "/"),
            "status": res["status"], "first_divergence": res["first_divergence"],
            "max_delta": res["max_delta"], "diverging_ticks": res["diverging_ticks"], "ticks": res["ticks_expected"]}


def _h(name: str) -> int:
    return int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)


def compute_split(rows: list[dict], vanilla_names: set) -> dict:
    """Deterministic ~60/40 visible/holdout split by name hash; each family on both sides when possible."""
    side = {r["name"]: ("visible" if _h(r["name"]) % 100 < 60 else "holdout") for r in rows}
    fams: dict[str, list[str]] = {}
    for r in rows:
        fams.setdefault(r["family"], []).append(r["name"])
    for fam, names in fams.items():
        if len(names) < 2:
            continue
        sides = {side[n] for n in names}
        if len(sides) == 1:
            only = sides.pop()
            mover = max(names, key=_h) if only == "visible" else min(names, key=_h)
            side[mover] = "holdout" if only == "visible" else "visible"
    out = []
    for r in rows:
        out.append({"name": r["name"], "family": r["family"], "split": side[r["name"]],
                    "provenance": "vanilla" if r["name"] in vanilla_names else "reference",
                    "scenario_hash": adapters.scenario_hash(r["scenario"])})
    return {"schema_version": 1, "method": "sha256(name)[:8] % 100 < 60 -> visible; family balancing",
            "scenarios": out}


def bug_coverage(split: dict) -> list[dict]:
    """For each seeded bug, which of its diverging scenarios are vanilla-backed (if bugs exist)."""
    out = []
    for cf in sorted(util.BUGS.glob("*/case.json")) if util.BUGS.exists() else []:
        case = util.read_json(cf)
        prov = {s["name"]: s["provenance"] for s in split["scenarios"]}
        cov = cf.parent / "coverage.json"
        hits = util.read_json(cov).get("corpus_hits", []) if cov.exists() else []
        names = case.get("repro_scenarios", []) + hits
        van = sorted({n for n in names if prov.get(n) == "vanilla"})
        out.append({"case": case["id"], "vanilla_scenarios": van,
                    "coverage": "vanilla" if van else "reference-only"})
    return out


def run(verbose: bool = True) -> dict:
    goldens = ensure_dev_goldens()
    ensure_reference()
    corpus = corpus_files()
    results = {"corpus": [calibrate_trace(p) for p in corpus], "dev_goldens": [calibrate_trace(p) for p in goldens]}
    rows = scenarios.corpus_table()
    names_with_trace = {r["name"] for r in results["corpus"]}
    split = compute_split(rows, names_with_trace)
    util.write_json(util.ORACLE / "split.json", split)
    o = Oracle()
    results["mode"] = "full" if corpus else "thin"
    results["oracle_coverage"] = len(corpus)
    results["corpus_matched"] = sum(r["status"] == "match" for r in results["corpus"])
    results["dev_goldens_matched"] = sum(r["status"] == "match" for r in results["dev_goldens"])
    results["vanilla_backed_scenarios"] = sum(o.has_vanilla(r["scenario"]) for r in rows)
    results["bug_coverage"] = bug_coverage(split)
    worst = {}
    for r in results["corpus"] + results["dev_goldens"]:
        for f, d in r["max_delta"].items():
            d = float("inf") if d == "inf" else d
            worst[f] = max(worst.get(f, 0.0), d)
    results["max_delta_all"] = worst
    out = util.RESULTS / "calibration.json"
    if out.exists():
        try:
            prev = util.read_json(out)
            fewer = len(prev.get("dev_goldens", [])) > len(goldens) or len(prev.get("corpus", [])) > len(corpus)
        except Exception:
            fewer = False
        if fewer:  # never replace committed evidence with a run that saw fewer real traces (e.g. a clone without lab/)
            out = util.RESULTS / "calibration.local.json"
    util.write_json(out, results)
    if verbose:
        print(f"ORACLE COVERAGE: {len(corpus)} real vanilla scenarios ({results['mode'].upper()} mode)")
        print(f"{'source':10} {'scenario':34} {'status':8} {'ticks':>5}  max|dpos|   max|dvel|   first divergence")
        for kind in ("corpus", "dev_goldens"):
            for r in results[kind]:
                md = {k: (float('inf') if v == 'inf' else v) for k, v in r["max_delta"].items()}
                dp = max(md.get(k, 0.0) for k in ("x", "y", "z"))
                dv = max(md.get(k, 0.0) for k in ("vx", "vy", "vz"))
                fd = r["first_divergence"]
                fds = f"tick {fd['tick']} {fd['field']} exp={fd['expected']} got={fd['actual']}" if fd else "-"
                print(f"{kind[:10]:10} {r['name']:34} {r['status']:8} {r['ticks']:5}  {dp:9.2e}   {dv:9.2e}   {fds}")
        print(f"corpus matched {results['corpus_matched']}/{len(corpus)}; dev goldens matched "
              f"{results['dev_goldens_matched']}/{len(goldens)}; split: "
              f"{sum(s['split']=='visible' for s in split['scenarios'])} visible / "
              f"{sum(s['split']=='holdout' for s in split['scenarios'])} holdout")
    return results


def main(argv) -> int:
    r = run(verbose="--quiet" not in argv)
    if "--json" in argv:
        print(json.dumps(r, indent=2))
    bad = [x for x in r["corpus"] + r["dev_goldens"] if x["status"] != "match"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

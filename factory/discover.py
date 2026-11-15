"""`python -m factory discover`: find behavior bugs nobody reported.

Random valid scenarios (both fixtures) are run on a candidate sim and on the oracle's reference layer. Every
divergence is shrunk to a minimal repro (truncate after the first diverging tick, drop actions one at a time
while it still diverges, truncate again), then grouped by symptom:
(first diverging field, keys held at that tick, airborne?, sprinting?, fixture).

  python -m factory discover                      # every seeded bug; writes results/discovery.json
  python -m factory discover --case c9_compound_sprint_jump --count 400 --seed 3

No LLM involved. Random scenarios have no real recording, so answers come from the reference layer
(validated against the real corpus) and are labeled that way.
"""
from __future__ import annotations

import argparse
import random
import tempfile
import time
from pathlib import Path

from oracle import compare
from oracle.adapters import SETTLED_START
from oracle.oracle import ensure_reference

from . import bugs, scenarios, util

KEYS = ["forward", "backward", "left", "right", "jump", "shift", "sprint"]
KEY_WEIGHT = [6, 2, 3, 3, 4, 2, 4]
RATIO_MIN = 100.0


def random_scenario(rng: random.Random, i: int) -> dict:
    fixture = "wall_v1" if rng.random() < 0.25 else "flat_stone_v1"
    dur = rng.randint(20, 120)
    acts = []
    for _ in range(rng.randint(1, 5)):
        k = rng.choices(KEYS, KEY_WEIGHT)[0]
        a = rng.randint(0, dur - 2)
        b = rng.randint(a + 1, min(dur - 1, a + 45))
        acts += [{"at": a, "key": k, "down": True}, {"at": b, "key": k, "down": False}]
    if rng.random() < 0.3:  # sprint-running is rare under uniform picks; seed it explicitly
        a, b = rng.randint(0, dur // 3), rng.randint(dur // 2, dur - 1)
        acts += [{"at": a, "key": "forward", "down": True}, {"at": a, "key": "sprint", "down": True},
                 {"at": b, "key": "forward", "down": False}, {"at": b, "key": "sprint", "down": False}]
    for _ in range(rng.choice([0, 0, 1, 2])):
        acts.append({"at": rng.randint(0, dur - 1), "yaw": rng.choice([0, 15, 30, 45, 84, 90, 135, -30, -60, -120, 180]), "pitch": 0})
    acts.sort(key=lambda a: a["at"])
    return scenarios.make(f"disc_{i:04d}", dur, acts, fixture)


def _jobs(scens):
    return [{"scenario": s, "initial_state": dict(SETTLED_START)} for s in scens]


class Prober:
    """Batch-evaluates scenarios on candidate + reference (one subprocess each per batch)."""

    def __init__(self, cand: Path, ref: Path):
        self.cand, self.ref, self.calls = cand, ref, 0

    def run(self, scens: list[dict]) -> list[dict]:
        self.calls += 1
        exp = util.run_sims(self.ref, _jobs(scens), timeout=600)
        got = util.run_sims(self.cand, _jobs(scens), timeout=600)
        out = []
        for e, g in zip(exp, got):
            if not (e["ok"] and g["ok"]):
                out.append({"diverges": g["ok"] != e["ok"], "first": None, "ref": e.get("trace")})
                continue
            c = compare.compare(e["trace"], g["trace"])
            out.append({"diverges": c["status"] != "match" and compare.max_ratio(c) >= RATIO_MIN,
                        "first": c["first_divergence"], "ref": e["trace"]})
        return out


def on_floor(trace) -> bool:
    return all(abs(r["x"]) < 46 and abs(r["z"]) < 46 and r["y"] >= 100 - 1e-6 for r in trace[1:])


def truncate(s: dict, first_tick: int) -> dict:
    d = first_tick + 1
    return dict(s, duration=d, actions=[a for a in s["actions"] if a["at"] < d])


def minimize(s: dict, probe) -> tuple[dict, dict]:
    """1-minimal shrink: truncate, then drop single actions while the divergence persists, then truncate again.

    `probe(list_of_scenarios) -> list_of_results` (result has 'diverges' and 'first'). Returns (scenario, result).
    """
    res = probe([s])[0]
    if not res["diverges"]:
        return s, res
    if res["first"]:
        t = truncate(s, res["first"]["tick"])
        r2 = probe([t])[0]
        if r2["diverges"]:
            s, res = t, r2
    while True:
        cands = [dict(s, actions=s["actions"][:i] + s["actions"][i + 1:]) for i in range(len(s["actions"]))]
        if not cands:
            break
        rs = probe(cands)
        k = next((i for i, r in enumerate(rs) if r["diverges"]), None)
        if k is None:
            break
        s, res = cands[k], rs[k]
        if res["first"]:
            t = truncate(s, res["first"]["tick"])
            r2 = probe([t])[0]
            if r2["diverges"]:
                s, res = t, r2
    return s, res


def keys_at(s: dict, tick: int) -> list[str]:
    held = {}
    for a in sorted(s["actions"], key=lambda a: a["at"]):
        if a["at"] > tick:
            break
        if "key" in a:
            held[a["key"]] = a["down"]
    return sorted(k for k, v in held.items() if v)


AXIS = {"x": "horizontal motion", "z": "horizontal motion", "vx": "horizontal motion", "vz": "horizontal motion",
        "y": "vertical motion", "vy": "vertical motion", "on_ground": "ground state", "sprinting": "sprint state",
        "sneaking": "sneak state", "pose": "pose", "yaw": "rotation", "pitch": "rotation"}


def signature(s: dict, res: dict) -> str:
    """Coarse symptom: what diverged, in which movement phase. Keys held are kept as an example, not in the key."""
    fd = res["first"] or {}
    t = fd.get("tick", 0)
    ref = res["ref"][1:] if res.get("ref") else []
    rec = ref[t] if t < len(ref) else {}
    phase = "airborne" if rec and not rec.get("on_ground") else "on the ground"
    spr = "sprinting" if rec.get("sprinting") else "not sprinting"
    wall = "near the wall" if s["fixture"] == "wall_v1" and rec and rec.get("z", 0) > 3.0 else "open floor"
    return f"{AXIS.get(fd.get('field'), fd.get('field', '?'))} · {phase} · {spr} · {wall}"


def shift_earlier(s: dict, res: dict, probe) -> tuple[dict, dict]:
    """Move every action earlier by the same amount while the divergence persists (shorter repro)."""
    lo = min((a["at"] for a in s["actions"]), default=0)
    for step in (lo, lo // 2, 5, 2, 1):
        if step <= 0 or step > lo:
            continue
        t = dict(s, actions=[dict(a, at=a["at"] - step) for a in s["actions"]], duration=max(1, s["duration"] - step))
        r = probe([t])[0]
        if r["diverges"]:
            s, res = t, r
            lo -= step
    return s, res


def discover_case(case_id: str, count: int, seed: int, ref: Path) -> dict:
    t0 = time.time()
    rng = random.Random(f"{seed}:{case_id}")
    with tempfile.TemporaryDirectory(prefix="tld_") as td:
        cand = bugs.materialize(case_id, Path(td))
        pr = Prober(cand, ref)
        raw = [random_scenario(rng, i) for i in range(count)]
        res = pr.run(raw)
        valid = [(s, r) for s, r in zip(raw, res) if r["ref"] and on_floor(r["ref"])]
        div = [(s, r) for s, r in valid if r["diverges"]]
        clusters: dict[str, dict] = {}
        for s, r in div:
            sig0 = signature(s, r)
            if sig0 in clusters and clusters[sig0]["minimized"]:
                clusters[sig0]["count"] += 1
                continue
            m, mr = minimize(s, pr.run)
            m, mr = shift_earlier(m, mr, pr.run)
            sig = signature(m, mr)
            c = clusters.setdefault(sig, {"signature": sig, "count": 0, "minimized": None})
            c["count"] += 1
            clusters.setdefault(sig0, c)
            if c["minimized"] is None or len(m["actions"]) < len(c["minimized"]["actions"]):
                c.update({"minimized": m, "first_divergence": mr["first"],
                          "keys_at_divergence": keys_at(m, (mr["first"] or {}).get("tick", 0)),
                          "raw_size": {"actions": len(s["actions"]), "ticks": s["duration"]},
                          "min_size": {"actions": len(m["actions"]), "ticks": m["duration"]}})
        uniq = {id(c): c for c in clusters.values()}.values()
        cl = sorted(uniq, key=lambda c: -c["count"])
    return {"case": case_id, "generated": count, "valid": len(valid), "divergent": len(div), "clusters": cl,
            "found": bool(cl), "probe_batches": pr.calls, "seconds": round(time.time() - t0, 1)}


def run(cases=None, count=200, seed=1, verbose=True) -> dict:
    ref = ensure_reference()
    out = {"seed": seed, "count_per_case": count, "oracle": "reference layer (validated against the real corpus)",
           "cases": []}
    for cid in cases or bugs.case_ids():
        r = discover_case(cid, count, seed, ref)
        out["cases"].append(r)
        if verbose:
            print(f"{cid:26} {r['divergent']:4}/{r['valid']:<4} divergent  {len(r['clusters'])} cluster(s)  {r['seconds']}s")
            for c in r["clusters"][:4]:
                print(f"    x{c['count']:<3} {c['signature']}  ({c['raw_size']['actions']} actions/{c['raw_size']['ticks']}t -> "
                      f"{c['min_size']['actions']}/{c['min_size']['ticks']}t)")
    found = sum(r["found"] for r in out["cases"])
    out["recall"] = {"found": found, "total": len(out["cases"])}
    if verbose:
        print(f"recall: {found}/{len(out['cases'])} seeded bugs found without being told about them")
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="factory discover")
    ap.add_argument("--case", action="append")
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    out = run(a.case, a.count, a.seed)
    if not a.case:
        util.write_json(util.RESULTS / "discovery.json", out)
    return 0

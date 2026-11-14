"""Normalize raw TickProbe output into ticklab.trace/1 corpus traces + INDEX.json, with validation and
determinism checks (batch-vs-batch order independence and in-batch repeats).

Usage: python capture/normalize.py a [b]     # batch dirs under capture/out/
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from oracle import adapters  # noqa: E402

CORPUS = ROOT / "oracle" / "corpus"


def load_scenarios() -> dict:
    rows = json.loads((ROOT / "oracle" / "corpus_scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    return {r["name"]: r for r in rows}


def read_raw(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def body(trace: list[dict]) -> str:
    """The part of a trace that must be reproducible: initial state + records (not capture metadata)."""
    return json.dumps(trace[0]["initial_state"], sort_keys=True) + "\n" + adapters.dumps(trace[1:])


def validate(trace: list[dict], scenario: dict) -> list[str]:
    probs = []
    head, recs = trace[0], trace[1:]
    if head.get("schema") != adapters.SCHEMA:
        probs.append("bad header")
    if len(recs) != scenario["duration"]:
        probs.append(f"frames {len(recs)} != duration {scenario['duration']}")
    if [r["tick"] for r in recs] != list(range(len(recs))):
        probs.append("ticks not contiguous from 0")
    for r in recs:
        for k in ("x", "y", "z", "vx", "vy", "vz", "yaw", "pitch"):
            v = r.get(k)
            if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
                probs.append(f"tick {r['tick']}: {k} not finite")
                break
        if r["y"] < 100 - 1e-6 or not (-48 <= r["x"] <= 48 and -48 <= r["z"] <= 48):
            probs.append(f"tick {r['tick']}: player off the floor ({r['x']:.3f},{r['y']:.3f},{r['z']:.3f})")
            break
    return probs


def normalize_batch(batch: str) -> tuple[dict, dict]:
    d = HERE / "out" / batch
    done = json.loads((d / "done.json").read_text(encoding="utf-8")) if (d / "done.json").exists() else {}
    scen = load_scenarios()
    out = {}
    for p in sorted(d.glob("*.raw.jsonl")):
        stem = p.name[: -len(".raw.jsonl")]
        name = stem[: -len(".repeat")] if stem.endswith(".repeat") else stem
        if name not in scen:
            continue
        lab = {"minecraft": done.get("minecraft", "26.3"), "mod": done.get("mod"), "java": done.get("java"),
               "captured_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
               "order": done.get("order"), "batch": batch}
        out[stem] = adapters.raw_capture_to_trace(read_raw(p), scen[name]["scenario"], lab)
    return out, done


def write_corpus(batches: list[str]) -> dict:
    scen = load_scenarios()
    norm = {b: normalize_batch(b) for b in batches}
    primary, done = norm[batches[0]]
    CORPUS.mkdir(parents=True, exist_ok=True)
    index = {"schema_version": 1, "minecraft": done.get("minecraft"), "mod": done.get("mod"), "java": done.get("java"),
             "batches": {b: {"order": norm[b][1].get("order"), "captured": norm[b][1].get("captured"),
                             "failures": norm[b][1].get("failures", [])} for b in batches},
             "scenarios": []}
    for name, row in scen.items():
        entry = {"name": name, "family": row["family"], "file": f"{name}.jsonl",
                 "scenario_hash": adapters.scenario_hash(row["scenario"]), "usable": False, "notes": []}
        tr = primary.get(name)
        if tr is None:
            entry["notes"].append(f"not captured in batch {batches[0]}")
            index["scenarios"].append(entry)
            continue
        probs = validate(tr, row["scenario"])
        det = {}
        rep = primary.get(name + ".repeat")
        if rep is not None:
            det["repeat_in_batch"] = body(rep) == body(tr)
        for b in batches[1:]:
            other = norm[b][0].get(name)
            det[f"order_vs_{b}"] = None if other is None else body(other) == body(tr)
        entry["determinism"] = det
        bad_det = [k for k, v in det.items() if v is False]
        if bad_det:
            probs.append(f"non-deterministic: {bad_det}")
        entry["frames"] = len(tr) - 1
        entry["usable"] = not probs
        entry["notes"] += probs
        with open(CORPUS / f"{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            f.write(adapters.dumps(tr))
        index["scenarios"].append(entry)
    index["usable"] = sum(e["usable"] for e in index["scenarios"])
    with open(CORPUS / "INDEX.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
    return index


if __name__ == "__main__":
    idx = write_corpus(sys.argv[1:] or ["a"])
    print(f"corpus: {idx['usable']}/{len(idx['scenarios'])} usable")
    for e in idx["scenarios"]:
        if not e["usable"]:
            print("  unusable:", e["name"], e["notes"][:2])

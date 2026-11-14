"""Schema validation of oracle/corpus/*.jsonl against ticklab.trace/1 and INDEX.json consistency."""
from __future__ import annotations

import math

from oracle import adapters

from . import scenarios, util

REQUIRED = ["x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose"]


def validate_trace(path) -> list[str]:
    probs = []
    try:
        tr = util.read_jsonl(path)
    except Exception as e:
        return [f"{path.name}: unreadable ({e})"]
    raw = path.read_bytes()
    if b"\r\n" in raw:
        probs.append(f"{path.name}: CRLF line endings")
    h = tr[0]
    if h.get("schema") != "ticklab.trace/1":
        probs.append(f"{path.name}: bad schema {h.get('schema')}")
    if h.get("source") != "vanilla":
        probs.append(f"{path.name}: source must be vanilla")
    sc = h.get("scenario", {})
    if adapters.scenario_hash(sc) != h.get("scenario_hash"):
        probs.append(f"{path.name}: scenario_hash mismatch")
    if scenarios.validate(sc):
        probs.append(f"{path.name}: invalid scenario {scenarios.validate(sc)[:1]}")
    if not isinstance(h.get("initial_state"), dict):
        probs.append(f"{path.name}: missing initial_state")
    recs = tr[1:]
    if [r.get("tick") for r in recs] != list(range(sc.get("duration", -1))):
        probs.append(f"{path.name}: ticks not 0..duration-1")
    for r in recs:
        miss = [k for k in REQUIRED if k not in r]
        if miss:
            probs.append(f"{path.name}: tick {r.get('tick')} missing {miss}")
            break
        if any(isinstance(r[k], float) and not math.isfinite(r[k]) for k in REQUIRED):
            probs.append(f"{path.name}: non-finite value at tick {r['tick']}")
            break
    return probs


def validate_corpus() -> list[str]:
    probs = []
    files = sorted(util.CORPUS.glob("*.jsonl"))
    for p in files:
        probs += validate_trace(p)
    idx = util.CORPUS / "INDEX.json"
    if not idx.exists():
        probs.append("INDEX.json missing")
        return probs
    index = util.read_json(idx)
    names = {e["name"] for e in index.get("scenarios", [])}
    for p in files:
        if p.stem not in names:
            probs.append(f"{p.name} not listed in INDEX.json")
    table = {r["name"]: adapters.scenario_hash(r["scenario"]) for r in scenarios.corpus_table()}
    for e in index.get("scenarios", []):
        if e["name"] in table and e.get("scenario_hash") != table[e["name"]]:
            probs.append(f"INDEX {e['name']}: hash differs from corpus_scenarios.json")
    return probs

"""Adapters into ticklab.trace/1.

- `golden_to_trace`: the earlier lab's vanilla goldens (lab/golden/*.json, dev-time cross-checks only).
- `raw_capture_to_trace`: raw TickProbe output (capture/out/*.raw.jsonl) -> normalized trace.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA = "ticklab.trace/1"
TRACE_FIELDS = ["x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose", "sprinting", "sneaking"]
SETTLED_START = {"x": 0.5, "y": 100.0, "z": 0.5, "vx": 0.0, "vy": -0.0784000015258789, "vz": 0.0,
                 "on_ground": True, "yaw": 0.0, "pitch": 0.0, "pose": "STANDING", "sprinting": False, "sneaking": False}


def scenario_hash(s: dict) -> str:
    return hashlib.sha256(json.dumps(s, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def golden_to_trace(golden: dict, name: str) -> list[dict]:
    sc = {k: v for k, v in golden["scenario"].items() if k != "observe"}
    sc["name"] = name
    recs = []
    for i, fr in enumerate(golden["frames"]):
        p = fr["player"]
        tick = fr.get("scenario_tick", i)
        vx, vy, vz = p["velocity"]
        recs.append({"tick": tick, "x": p["x"], "y": p["y"], "z": p["z"], "vx": vx, "vy": vy, "vz": vz,
                     "on_ground": p["on_ground"], "yaw": p["yaw"], "pitch": p["pitch"], "pose": p["pose"]})
    # The golden's frame list starts after tick 0; its pre-tick state is the settled standing state at the
    # same spawn point (verified: idle frames equal SETTLED_START), so it is used as the initial state.
    init = {k: SETTLED_START[k] for k in ("x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose")}
    head = {"schema": SCHEMA, "source": "vanilla", "name": name, "scenario_hash": scenario_hash(sc), "scenario": sc,
            "fields": ["x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose"], "initial_state": init,
            "lab": {"origin": "lab/golden (earlier capture; dev cross-check only)",
                    "run_id": golden.get("source", {}).get("run_id")}}
    return [head] + recs


def raw_capture_to_trace(raw: list[dict], scenario: dict, lab: dict) -> list[dict]:
    """raw: TickProbe lines: {"type":"initial",...} then {"type":"tick","tick":i,...}."""
    init_line = next((r for r in raw if r.get("type") == "initial"), None)
    if init_line is None:
        raise ValueError("raw capture has no initial-state line")
    init = {k: init_line[k] for k in TRACE_FIELDS if k in init_line}
    recs = []
    for r in raw:
        if r.get("type") != "tick":
            continue
        recs.append({"tick": r["tick"], **{k: r[k] for k in TRACE_FIELDS if k in r}})
    head = {"schema": SCHEMA, "source": "vanilla", "name": scenario["name"], "scenario_hash": scenario_hash(scenario),
            "scenario": scenario, "fields": [f for f in TRACE_FIELDS if recs and f in recs[0]],
            "initial_state": init, "lab": lab}
    return [head] + recs


def dumps(trace: list[dict]) -> str:
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in trace)

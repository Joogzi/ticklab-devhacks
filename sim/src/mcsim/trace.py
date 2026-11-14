"""ticklab.trace/1 writer (JSONL: header line, then one record per tick)."""
import hashlib
import json

SCHEMA = "ticklab.trace/1"
FIELDS = ["x", "y", "z", "vx", "vy", "vz", "on_ground", "yaw", "pitch", "pose", "sprinting", "sneaking"]


def scenario_hash(scenario: dict) -> str:
    canon = json.dumps(scenario, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def header(scenario: dict, initial_state: dict, source: str = "mcsim") -> dict:
    return {"schema": SCHEMA, "source": source, "name": scenario.get("name"),
            "scenario_hash": scenario_hash(scenario), "scenario": scenario, "fields": FIELDS,
            "initial_state": initial_state, "lab": {"engine": "mcsim"}}


def record(tick: int, state: dict) -> dict:
    out = {"tick": tick}
    for f in FIELDS:
        out[f] = state[f]
    return out


def dumps(lines) -> str:
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in lines)

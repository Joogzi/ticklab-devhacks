"""Scenario format helpers and the corpus scenario table (PROJECT.md §3).

`python -m factory.scenarios` regenerates oracle/corpus_scenarios.json.
"""
from __future__ import annotations

import re

from . import util

KEYS = ("forward", "backward", "left", "right", "jump", "shift", "sprint")

TABLE = """
walk_f10 walk 50 forward↓0 forward↑10
walk_f20 walk 50 forward↓0 forward↑20
walk_f35 walk 50 forward↓0 forward↑35
walk_back walk 45 backward↓0 backward↑25
sprint_run sprint 50 forward↓0 sprint↓0 forward↑30 sprint↑30
sprint_release_sprint sprint 50 forward↓0 sprint↓0 sprint↑15 forward↑35
sprint_release_forward sprint 50 forward↓0 sprint↓0 forward↑12 sprint↑30
sprint_late_press sprint 50 forward↓0 sprint↓10 forward↑35 sprint↑35
jump_stand jump 40 jump↓2 jump↑3
jump_hold jump 60 jump↓2 jump↑45
jump_run jump 55 forward↓0 jump↓10 jump↑11 forward↑35
jump_sprint jump 55 forward↓0 sprint↓0 jump↓10 jump↑11 forward↑35 sprint↑35
jump_sprint_release_sprint_air jump 55 forward↓0 sprint↓0 jump↓10 jump↑11 sprint↑14 forward↑40
jump_run_release_forward_air jump 55 forward↓0 jump↓10 jump↑11 forward↑14
jump_sprint_release_forward_air jump 55 forward↓0 sprint↓0 jump↓10 jump↑11 forward↑14 sprint↑40
jump_double_tap jump 60 jump↓5 jump↑6 jump↓25 jump↑26
jump_sprint_hold jump 60 forward↓0 sprint↓0 jump↓8 jump↑40 forward↑40 sprint↑40
diag_walk_fl diagonal 50 forward↓0 left↓0 forward↑30 left↑30
diag_walk_fr diagonal 50 forward↓0 right↓0 forward↑30 right↑30
diag_sprint_fl diagonal 50 forward↓0 left↓0 sprint↓0 forward↑30 left↑30 sprint↑30
diag_sprint_jump_fr diagonal 55 forward↓0 right↓0 sprint↓0 jump↓10 jump↑11 forward↑35 right↑35 sprint↑35
diag_back_left diagonal 50 backward↓0 left↓0 backward↑25 left↑25
strafe_left strafe 45 left↓0 left↑25
strafe_right strafe 45 right↓0 right↑25
back_jump strafe 50 backward↓0 jump↓10 jump↑11 backward↑30
sneak_walk sneak 50 shift↓0 forward↓0 forward↑35 shift↑35
sneak_diag sneak 50 shift↓0 forward↓0 left↓0 forward↑35 left↑35 shift↑35
sneak_toggle_mid sneak 55 forward↓0 shift↓15 shift↑30 forward↑40
sneak_jump sneak 45 shift↓0 jump↓5 jump↑6 shift↑30
look_walk_turn look 50 forward↓0 yaw90/pitch0@10 forward↑35
look_sprint_jump_turn look 55 forward↓0 sprint↓0 jump↓10 jump↑11 yaw45/pitch0@14 forward↑40 sprint↑40
look_diag_turn look 50 forward↓0 left↓0 yaw-60/pitch0@8 yaw30/pitch0@20 forward↑35 left↑35
look_pitch_walk look 45 yaw0/pitch60@2 forward↓3 forward↑30
wall_walk_into wall 40 forward↓0 forward↑30
wall_sprint_into wall 40 forward↓0 sprint↓0 forward↑30 sprint↑30
wall_sprint_jump_land wall 50 forward↓0 sprint↓0 jump↓20 jump↑21 forward↑40 sprint↑40
wall_sprint_jump_into wall 45 forward↓0 sprint↓0 jump↓6 jump↑7 forward↑35 sprint↑35
wall_diag_slide wall 45 forward↓0 left↓0 forward↑35 left↑35
wall_diag_sprint_slide wall 45 forward↓0 left↓0 sprint↓0 forward↑35 left↑35 sprint↑35
wall_glance_sprint wall 55 forward↓0 forward↑18 yaw84/pitch0@20 forward↓20 sprint↓20 forward↑50 sprint↑50
wall_steep_sprint wall 55 forward↓0 forward↑18 yaw60/pitch0@20 forward↓20 sprint↓20 forward↑50 sprint↑50
wall_back_off wall 50 forward↓0 forward↑22 backward↓25 backward↑40
wall_jump_hold wall 50 forward↓0 jump↓18 jump↑40 forward↑40
wall_strafe_after wall 50 forward↓0 forward↑20 left↓20 left↑40
"""
FIXTURE_OF_FAMILY = {"wall": "wall_v1"}
FIXTURES = ("flat_stone_v1", "wall_v1")

_KEY_RE = re.compile(r"^(\w+)([↓↑])(\d+)$")
_LOOK_RE = re.compile(r"^yaw(-?[\d.]+)/pitch(-?[\d.]+)@(\d+)$")


def _num(s: str):
    f = float(s)
    return int(f) if f.is_integer() else f


def parse_actions(tokens: list[str]) -> list[dict]:
    acts = []
    for tok in tokens:
        m = _KEY_RE.match(tok)
        if m:
            acts.append({"at": int(m.group(3)), "key": m.group(1), "down": m.group(2) == "↓"})
            continue
        m = _LOOK_RE.match(tok)
        if m:
            acts.append({"at": int(m.group(3)), "yaw": _num(m.group(1)), "pitch": _num(m.group(2))})
            continue
        raise ValueError(f"bad action token {tok!r}")
    return sorted(acts, key=lambda a: a["at"])  # stable: table order kept within a tick


def make(name: str, duration: int, actions: list[dict], fixture: str = "flat_stone_v1") -> dict:
    return {"schema_version": 1, "name": name, "duration": duration, "fixture": fixture, "actions": actions}


def corpus_table() -> list[dict]:
    """[{name, family, scenario}] for the 33 corpus scenarios."""
    out = []
    for line in TABLE.strip().splitlines():
        name, fam, dur, *toks = line.split()
        out.append({"name": name, "family": fam,
                    "scenario": make(name, int(dur), parse_actions(toks), FIXTURE_OF_FAMILY.get(fam, "flat_stone_v1"))})
    return out


def validate(s: dict) -> list[str]:
    """Return a list of problems (empty = valid)."""
    probs = []
    if not isinstance(s, dict):
        return ["scenario must be an object"]
    if s.get("schema_version") != 1:
        probs.append("schema_version must be 1")
    if not isinstance(s.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", s.get("name") or ""):
        probs.append("name must match [A-Za-z0-9_.-]{1,64}")
    d = s.get("duration")
    if not isinstance(d, int) or not 1 <= d <= 200:
        probs.append("duration must be an int in 1..200")
        d = 0
    if s.get("fixture", "flat_stone_v1") not in FIXTURES:
        probs.append(f"fixture must be one of {FIXTURES}")
    last = -1
    for a in s.get("actions", []):
        at = a.get("at")
        if not isinstance(at, int) or at < 0 or (d and at >= d):
            probs.append(f"action at={at!r} outside 0..duration-1")
            continue
        if at < last:
            probs.append("actions must be ordered by at")
        last = at
        if "key" in a:
            if a["key"] not in KEYS or not isinstance(a.get("down"), bool):
                probs.append(f"bad key action {a}")
        elif "yaw" in a or "pitch" in a:
            for k in ("yaw", "pitch"):
                if k in a and not isinstance(a[k], (int, float)):
                    probs.append(f"bad {k} in {a}")
            if "pitch" in a and not -90 <= a["pitch"] <= 90:
                probs.append("pitch must be within -90..90")
        else:
            probs.append(f"unknown action {a}")
    return probs


def family_of(name: str) -> str:
    for row in corpus_table():
        if row["name"] == name:
            return row["family"]
    return name.split("_")[0]


def write_corpus_scenarios() -> None:
    rows = corpus_table()
    for r in rows:
        assert not validate(r["scenario"]), (r["name"], validate(r["scenario"]))
    util.write_json(util.ORACLE / "corpus_scenarios.json",
                    {"schema_version": 1, "fixture": "flat_stone_v1", "scenarios": rows})


if __name__ == "__main__":
    write_corpus_scenarios()
    print(f"wrote {util.ORACLE / 'corpus_scenarios.json'} ({len(corpus_table())} scenarios)")

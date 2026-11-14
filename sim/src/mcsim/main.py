"""mcsim command line: `python -m mcsim run <scenario.json> [--out trace.jsonl] [--initial state.json]`."""
import argparse
import json
import sys

from . import input as inp
from . import trace
from .player import Player
from .world import World


def simulate(scenario: dict, initial_state: dict | None = None) -> list:
    """Run a scenario; returns [header, record_0, ..., record_{duration-1}]."""
    world = World(scenario.get("fixture", "flat_stone_v1"))
    player = Player(initial_state)
    init = player.state()
    keys = inp.Keys()
    actions = sorted(scenario.get("actions", []), key=lambda a: a["at"])
    out = [trace.header(scenario, init)]
    i = 0
    for t in range(int(scenario["duration"])):
        while i < len(actions) and actions[i]["at"] == t:
            a = actions[i]
            if "key" in a:
                if a["key"] not in inp.KEYS:
                    raise ValueError(f"unknown key {a['key']!r}")
                setattr(keys, a["key"], bool(a["down"]))
            if "yaw" in a:
                player.yaw = float(a["yaw"])
            if "pitch" in a:
                player.pitch = float(a["pitch"])
            i += 1
        player.tick(keys, world)
        out.append(trace.record(t, player.state()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mcsim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="simulate a scenario and emit a ticklab.trace/1 JSONL trace")
    r.add_argument("scenario")
    r.add_argument("--out")
    r.add_argument("--initial", help="JSON file with the initial player state")
    args = ap.parse_args(argv)
    with open(args.scenario, encoding="utf-8") as f:
        scenario = json.load(f)
    init = None
    if args.initial:
        with open(args.initial, encoding="utf-8") as f:
            init = json.load(f)
    text = trace.dumps(simulate(scenario, init))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0

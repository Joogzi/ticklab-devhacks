"""Orchestrate the real-Minecraft capture: discover -> build/install -> (human clicks Play) -> poll done.json
-> next batch -> normalize into oracle/corpus/ with determinism checks.

Usage:
  python capture/run_capture.py status            # what is missing / where we are
  python capture/run_capture.py batch a           # build+install batch a (listed + in-batch repeats), wait for it
  python capture/run_capture.py batch b           # shuffled order (seed 7), wait for it
  python capture/run_capture.py normalize a b     # write oracle/corpus + INDEX.json
Batches: a = listed order with repeat_check; b = shuffled (seed 7). The human clicks Play once per batch.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import build_mod  # noqa: E402
import discover_prism  # noqa: E402
import normalize  # noqa: E402

BATCHES = {"a": ["--batch", "a", "--order", "listed"],
           "b": ["--batch", "b", "--order", "shuffled", "--seed", "7", "--no-repeat-check"]}


def status() -> int:
    d = discover_prism.discover()
    print("instance:", d["selected"]["name"] if d["selected"] else "none")
    for p in d["problems"]:
        print("  problem:", p)
    for b in BATCHES:
        od = HERE / "out" / b
        done = od / "done.json"
        prog = od / "progress.json"
        print(f"batch {b}: " + ("done " + done.read_text(encoding="utf-8")[:200] if done.exists() else
                                ("progress " + prog.read_text(encoding="utf-8") if prog.exists() else "not run")))
    return 0 if d["selected"] else 2


def wait_done(batch: str, timeout_s: float) -> dict | None:
    done = HERE / "out" / batch / "done.json"
    prog = HERE / "out" / batch / "progress.json"
    t0, last = time.time(), None
    while time.time() - t0 < timeout_s:
        if done.exists():
            try:
                return json.loads(done.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        if prog.exists():
            txt = prog.read_text(encoding="utf-8")
            if txt != last:
                print("progress:", txt, flush=True)
                last = txt
        time.sleep(5)
    return None


def run_batch(batch: str, timeout_s: float) -> int:
    rc = build_mod.main(BATCHES[batch])
    if rc != 0:
        return rc
    print(f"waiting for the human to click Play (batch {batch}); polling every 5 s, timeout {timeout_s/60:.0f} min")
    res = wait_done(batch, timeout_s)
    if res is None:
        print("timed out waiting for done.json")
        return 3
    print("done:", json.dumps({k: res.get(k) for k in ("captured", "scenarios", "failures", "error", "elapsed_ms")}))
    ready = ROOT / "CAPTURE_READY.md"
    if ready.exists():
        ready.unlink()
    return 0 if not res.get("error") else 4


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "status":
        return status()
    if argv[0] == "batch":
        return run_batch(argv[1], float(argv[2]) * 60 if len(argv) > 2 else 25 * 60)
    if argv[0] == "normalize":
        idx = normalize.write_corpus(argv[1:] or ["a"])
        print(f"corpus: {idx['usable']}/{len(idx['scenarios'])} usable -> {normalize.CORPUS}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

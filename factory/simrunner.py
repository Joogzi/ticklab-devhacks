"""Harness-owned batch runner, executed as a subprocess: python factory/simrunner.py <sim_dir> <jobs.json> <out.json>

Imports the (possibly agent-modified) mcsim from <sim_dir>/src and runs every job
({"scenario":..., "initial_state":...}); writes [{"ok":bool, "trace":[...]|None, "error":str|None}].
Candidate code never runs inside the harness process itself.
"""
import json
import sys
import traceback


def main() -> int:
    sim_dir, jobs_path, out_path = sys.argv[1:4]
    sys.path.insert(0, sim_dir + "/src")
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    out = []
    try:
        from mcsim.main import simulate
    except Exception:
        err = traceback.format_exc(limit=3)
        out = [{"ok": False, "trace": None, "error": "import failed: " + err} for _ in jobs]
    else:
        for j in jobs:
            try:
                tr = simulate(j["scenario"], j.get("initial_state"))
                # round-trip through JSON text so results equal what the CLI would emit
                out.append({"ok": True, "trace": json.loads(json.dumps(tr)), "error": None})
            except Exception:
                out.append({"ok": False, "trace": None, "error": traceback.format_exc(limit=3)})
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())

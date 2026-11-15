"""Compare a presentation-mode re-recording batch against the committed corpus and fold it into results/live_confirm.json.

  python capture/rerecord_check.py wp
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from factory import scenarios, util  # noqa: E402
from oracle import adapters  # noqa: E402


def body(t):
    return json.dumps(t[0]["initial_state"], sort_keys=True) + adapters.dumps(t[1:])


def main(batch: str) -> int:
    table = {r["name"]: r["scenario"] for r in scenarios.corpus_table()}
    same, diff = [], []
    for rp in sorted((HERE / "out" / batch).glob("*.raw.jsonl")):
        n = rp.name[: -len(".raw.jsonl")]
        if n not in table:
            continue
        raw = [json.loads(l) for l in rp.read_text(encoding="utf-8").splitlines() if l.strip()]
        (same if body(adapters.raw_capture_to_trace(raw, table[n], {})) == body(util.read_jsonl(util.CORPUS / f"{n}.jsonl"))
         else diff).append(n)
    f = util.RESULTS / "live_confirm.json"
    d = util.read_json(f)
    pr = d.get("presentation_rerecord") or {"scenarios": 0, "byte_identical_to_corpus": 0, "different": [], "missing": 0}
    pr["byte_identical_to_corpus"] += len(same)
    pr["different"] = sorted(set(pr.get("different", [])) | set(diff))
    pr["missing"] = max(0, pr.get("missing", 0) - len(same) - len(diff))
    pr["batches"] = sorted(set(pr.get("batches", ["live"])) | {batch})
    d["presentation_rerecord"] = pr
    util.write_json(f, d)
    print(f"{batch}: {len(same)} byte-identical, {len(diff)} different {diff}; total {pr['byte_identical_to_corpus']}/{pr['scenarios']}")
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

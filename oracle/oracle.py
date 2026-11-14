"""The two-layer oracle: vanilla corpus first (ground truth), else the pristine reference build.

Harness-private. Agents never import this; the lab MCP server and the verifier do.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from factory import util

from .adapters import SETTLED_START, scenario_hash


def ensure_reference() -> Path:
    """(Re)build oracle/reference/ as a private pristine copy of sim/ (gitignored, never in workspaces)."""
    dst = util.REFERENCE_SIM
    src_files = sorted((util.SIM / "src").rglob("*.py"))
    manifest = {str(p.relative_to(util.SIM)).replace("\\", "/"): util.sha256_file(p) for p in src_files}
    mpath = dst / "MANIFEST.json"
    if mpath.exists():
        try:
            if util.read_json(mpath) == manifest:
                return dst
        except Exception:
            pass
    util.rmtree(dst)
    for p in src_files:
        out = dst / p.relative_to(util.SIM)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)
    util.write_json(mpath, manifest)
    return dst


class Oracle:
    def __init__(self, corpus_dir: Path = util.CORPUS, use_reference: bool = True):
        self.by_hash: dict[str, Path] = {}
        self.usable: dict[str, bool] = {}
        idx = corpus_dir / "INDEX.json"
        usable_names = None
        if idx.exists():
            usable_names = {s["name"] for s in util.read_json(idx).get("scenarios", []) if s.get("usable")}
        for p in sorted(corpus_dir.glob("*.jsonl")) if corpus_dir.exists() else []:
            try:
                head = util.read_jsonl(p)[0]
            except Exception:
                continue
            if usable_names is not None and head.get("name") not in usable_names:
                continue
            self.by_hash[head["scenario_hash"]] = p
        self.use_reference = use_reference
        self.ref = ensure_reference() if use_reference else None

    def has_vanilla(self, scenario: dict) -> bool:
        return scenario_hash(scenario) in self.by_hash

    def expected(self, scenario: dict) -> tuple[list[dict], str, dict]:
        """Return (trace incl. header, provenance 'vanilla'|'reference', initial_state)."""
        h = scenario_hash(scenario)
        if h in self.by_hash:
            tr = util.read_jsonl(self.by_hash[h])
            return tr, "vanilla", tr[0].get("initial_state") or dict(SETTLED_START)
        if not self.use_reference:
            raise KeyError(f"no vanilla trace for {scenario.get('name')} and reference layer disabled")
        return self.expected_many([scenario])[0]

    def expected_many(self, scens: list[dict]) -> list[tuple[list[dict], str, dict]]:
        """Batch version of expected(): one reference-sim subprocess for all non-vanilla scenarios."""
        out: list = [None] * len(scens)
        ref_jobs, ref_idx = [], []
        for i, s in enumerate(scens):
            h = scenario_hash(s)
            if h in self.by_hash:
                tr = util.read_jsonl(self.by_hash[h])
                out[i] = (tr, "vanilla", tr[0].get("initial_state") or dict(SETTLED_START))
            elif not self.use_reference:
                raise KeyError(f"no vanilla trace for {s.get('name')} and reference layer disabled")
            else:
                ref_jobs.append({"scenario": s, "initial_state": dict(SETTLED_START)})
                ref_idx.append(i)
        if ref_jobs:
            for i, r in zip(ref_idx, util.run_sims(self.ref, ref_jobs)):
                if not r["ok"]:
                    raise RuntimeError(f"reference sim failed on {scens[i].get('name')}: {r['error']}")
                tr = r["trace"]
                tr[0]["source"] = "reference"
                out[i] = (tr, "reference", dict(SETTLED_START))
        return out

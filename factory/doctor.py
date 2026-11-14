"""`python -m factory doctor`: what is installed, what the oracle looks like, which features are enabled."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

from . import util


def _ver(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=20)
        out = (p.stdout or p.stderr).strip().splitlines()
        return out[0] if out else "?"
    except Exception:
        return None


def oracle_mode() -> dict:
    corpus = sorted(util.CORPUS.glob("*.jsonl")) if util.CORPUS.exists() else []
    goldens = sorted(util.DEV_GOLDENS.glob("*.jsonl")) if util.DEV_GOLDENS.exists() else []
    usable = len(corpus)
    idx = util.CORPUS / "INDEX.json"
    if idx.exists():
        try:
            usable = sum(1 for s in util.read_json(idx).get("scenarios", []) if s.get("usable"))
        except Exception:
            pass
    return {"corpus_traces": len(corpus), "corpus_usable": usable, "dev_goldens": len(goldens),
            "mode": "full" if usable else "thin"}


def gather() -> dict:
    info = {"os": f"{platform.system()} {platform.release()} ({platform.version()})", "python": sys.version.split()[0]}
    info["venv_python"] = util.lab_python()
    try:
        p = subprocess.run([util.lab_python(), "-c", "import importlib.metadata as m; print(m.version('mcp'))"],
                           capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=30)
        info["mcp"] = p.stdout.strip() or None
    except Exception:
        info["mcp"] = None
    info["cargo"] = _ver(["cargo", "--version"]) if shutil.which("cargo") else None
    info["sim_impl"] = "python (cargo absent; see Log [DECISION])" if not info["cargo"] else "python"
    info["javac"] = _ver(["javac", "-version"]) if shutil.which("javac") else None
    claude = util.find_claude()
    info["claude"] = claude
    info["claude_version"] = _ver([claude, "--version"]) if claude else None
    info["git"] = _ver(["git", "--version"])
    try:
        sys.path.insert(0, str(util.ROOT / "capture"))
        import discover_prism  # type: ignore
        d = discover_prism.discover()
        info["prism"] = {"roots": d["roots"], "exe": d["exe"],
                         "instance": d["selected"]["name"] if d["selected"] else None, "problems": d["problems"]}
    except Exception as e:
        info["prism"] = {"error": str(e)}
    info["oracle"] = oracle_mode()
    info["features"] = {
        "agent_runs": bool(claude and info["mcp"]),
        "capture": bool(info["javac"] and info.get("prism", {}).get("instance")),
        "discovery": (util.ROOT / "factory" / "discover.py").exists(),
    }
    return info


def main(argv) -> int:
    info = gather()
    if "--json" in argv:
        print(json.dumps(info, indent=2))
        return 0
    o = info["oracle"]
    print("TickLab doctor")
    for k in ("os", "python", "venv_python", "mcp", "sim_impl", "javac", "claude", "claude_version", "git"):
        print(f"  {k:15} {info[k] if info[k] else 'MISSING'}")
    pr = info["prism"]
    print(f"  {'prism':15} roots={pr.get('roots')} instance={pr.get('instance') or 'none'}")
    for p in pr.get("problems", []):
        print(f"  {'':15} problem: {p}")
    print(f"  {'oracle':15} mode={o['mode'].upper()}  corpus={o['corpus_traces']} (usable {o['corpus_usable']})  dev_goldens={o['dev_goldens']}")
    print(f"  ORACLE COVERAGE: {o['corpus_usable']} real vanilla scenarios")
    print(f"  {'features':15} " + ", ".join(f"{k}={'on' if v else 'off'}" for k, v in info["features"].items()))
    return 0

"""Shared helpers: repo paths, LF-only JSON writing, hashing, sim invocation, Windows-safe cleanup."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "sim"
ORACLE = ROOT / "oracle"
CORPUS = ORACLE / "corpus"
DEV_GOLDENS = ORACLE / "dev_goldens"
REFERENCE_SIM = ORACLE / "reference"
BUGS = ROOT / "bugs"
RESULTS = ROOT / "results"
RUNS = ROOT / "runs"
WORKSPACES = ROOT / "workspaces"


def canonical_json(obj) -> str:
    """Canonical form used for scenario hashes: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def scenario_hash(scenario: dict) -> str:
    return hashlib.sha256(canonical_json(scenario).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 with LF newlines regardless of platform."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path: Path, obj, indent: int | None = 2) -> None:
    write_text(path, json.dumps(obj, indent=indent, sort_keys=False) + "\n")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def lab_python() -> str:
    """Interpreter for harness subprocesses: the project venv if present (it has `mcp`), else this one."""
    for cand in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def sim_cmd(sim_dir: Path) -> tuple[list[str], dict]:
    """Command + env to run an mcsim checkout (Python implementation, see Log [DECISION]).

    The single place that knows how to invoke the simulator; accepts any directory laid out like `sim/`.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(sim_dir) / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    return [sys.executable, "-B", "-m", "mcsim"], env


def run_sim(sim_dir: Path, scenario: dict, timeout: float = 60, initial_state: dict | None = None) -> tuple[list[dict], str]:
    """Run mcsim on a scenario dict; returns (records incl. header, stderr). Raises on failure."""
    import tempfile

    cmd, env = sim_cmd(sim_dir)
    with tempfile.TemporaryDirectory(prefix="tl_") as td:
        sp = Path(td) / "s.json"
        op = Path(td) / "t.jsonl"
        write_json(sp, scenario)
        args = cmd + ["run", str(sp), "--out", str(op)]
        if initial_state is not None:
            ip = Path(td) / "init.json"
            write_json(ip, initial_state)
            args += ["--initial", str(ip)]
        p = subprocess.run(args, env=env, capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=timeout)
        if p.returncode != 0 or not op.exists():
            raise RuntimeError(f"mcsim failed (rc={p.returncode}): {p.stderr.strip()[-2000:]}")
        return read_jsonl(op), p.stderr


def run_sims(sim_dir: Path, jobs: list[dict], timeout: float = 120) -> list[dict]:
    """Run many scenarios against a sim checkout in ONE subprocess (factory/simrunner.py).

    jobs: [{"scenario":..., "initial_state":...}] -> [{"ok", "trace", "error"}]. Timeout -> all failed.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="tl_") as td:
        jp, op = Path(td) / "jobs.json", Path(td) / "out.json"
        write_json(jp, jobs, indent=None)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        try:
            p = subprocess.run([sys.executable, "-B", str(ROOT / "factory" / "simrunner.py"), str(sim_dir), str(jp), str(op)],
                               env=env, capture_output=True, stdin=subprocess.DEVNULL, text=True, timeout=timeout, cwd=td)
        except subprocess.TimeoutExpired:
            return [{"ok": False, "trace": None, "error": f"timeout after {timeout}s"} for _ in jobs]
        if not op.exists():
            err = (p.stderr or "")[-1500:]
            return [{"ok": False, "trace": None, "error": f"runner crashed rc={p.returncode}: {err}"} for _ in jobs]
        return read_json(op)


def rmtree(path: Path, retries: int = 5) -> None:
    """Remove a tree on Windows: clear read-only bits (git objects), retry on transient locks."""
    path = Path(path)
    if not path.exists():
        return

    def onerror(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for i in range(retries):
        try:
            shutil.rmtree(path, onerror=onerror)
        except Exception:
            pass
        if not path.exists():
            return
        time.sleep(0.3 * (i + 1))
    if path.exists():
        raise RuntimeError(f"could not remove {path}")


def find_claude() -> str | None:
    """Resolve the Claude Code CLI: PATH, TICKLAB_CLAUDE, then the VS Code extension's bundled binary."""
    env = os.environ.get("TICKLAB_CLAUDE")
    if env and Path(env).exists():
        return env
    w = shutil.which("claude")
    if w:
        return w
    ext = Path.home() / ".vscode" / "extensions"
    if ext.exists():
        cands = sorted(ext.glob("anthropic.claude-code-*/resources/native-binary/claude*.exe"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if cands:
            return str(cands[0])
    return None


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, stdin=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass

"""Integrity helpers for the verifier's G0 gate: protected-file manifest, patch path policy, capability scan."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

from . import util

# Files that determine a verdict (hashed before a run, re-checked by the verifier). Kept to verdict-affecting
# files only, so unrelated harness edits (report, docs) can't cause false TAMPER verdicts. Builders: never edit
# these while a run/bench is in progress.
PROTECTED_DIRS = ["oracle/corpus", "bugs", "sim"]
PROTECTED_FILES = ["oracle/tolerance.toml", "oracle/compare.py", "oracle/oracle.py", "oracle/adapters.py",
                   "oracle/split.json", "oracle/corpus_scenarios.json", "factory/verifier.py", "factory/integrity.py",
                   "factory/patchutil.py", "factory/simrunner.py", "factory/bugs.py", "factory/scenarios.py",
                   "factory/util.py", "factory/check.py"]

ALLOWED_PATCH_PREFIX = "sim/src/"
# Modules candidate sim code may import (stdlib subset needed for numerics/IO of the CLI) + its own package.
ALLOWED_IMPORTS = {"math", "struct", "dataclasses", "json", "sys", "argparse", "hashlib", "typing", "functools",
                   "itertools", "collections", "enum", "__future__", "mcsim", "decimal", "fractions", "operator",
                   "copy", "bisect", "abc", "numbers", "array"}
# Names whose *new* use in candidate code is a capability escalation (file/network/process/eval access).
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "vars", "breakpoint", "input",
                   "getattr", "setattr", "delattr", "__builtins__", "__loader__", "__spec__"}


def manifest() -> dict:
    files = []
    for d in PROTECTED_DIRS:
        base = util.ROOT / d
        if base.exists():
            files += [p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [util.ROOT / f for f in PROTECTED_FILES if (util.ROOT / f).exists()]
    return {str(p.relative_to(util.ROOT)).replace("\\", "/"): util.sha256_file(p) for p in sorted(set(files))}


def manifest_changes(before: dict, after: dict | None = None) -> list[str]:
    after = after if after is not None else manifest()
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def path_violations(paths: list[str]) -> list[str]:
    bad = []
    for p in paths:
        q = p.replace("\\", "/")
        if not q.startswith(ALLOWED_PATCH_PREFIX) or ".." in Path(q).parts or not q.endswith(".py"):
            bad.append(p)
    return bad


def _usage(src: str) -> tuple[set, dict]:
    tree = ast.parse(src)
    imports, names = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            names[node.id] = names.get(node.id, 0) + 1
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr not in ("__init__", "__name__", "__dict__"):
            names["dunder:" + node.attr] = names.get("dunder:" + node.attr, 0) + 1
    return imports, names


def capability_violations(base_src: Path, cand_src: Path) -> list[str]:
    """New non-allowlisted imports or new uses of forbidden builtins in candidate vs base sources."""
    out = []
    for p in sorted(Path(cand_src).rglob("*.py")):
        rel = p.relative_to(cand_src)
        try:
            imp, names = _usage(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            out.append(f"{rel}: syntax error ({e.msg})")  # G1 will also fail; listed for clarity
            continue
        b = Path(base_src) / rel
        bimp, bnames = _usage(b.read_text(encoding="utf-8")) if b.exists() else (set(), {})
        for m in sorted(imp - bimp):
            if m not in ALLOWED_IMPORTS:
                std = "stdlib" if m in sys.stdlib_module_names else "third-party"
                out.append(f"{rel}: new import of {std} module '{m}' (dependency / capability)")
        for n, c in names.items():
            if c > bnames.get(n, 0):
                out.append(f"{rel}: new use of '{n}'")
    return out

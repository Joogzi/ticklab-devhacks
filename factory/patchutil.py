"""Minimal, strict unified-diff tools (parse, apply with exact context, make) — no dependence on git apply.

Paths come from `diff --git a/X b/X` or `--- a/X` / `+++ b/X` lines with the a/ b/ prefix stripped.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


def _strip(p: str) -> str | None:
    p = p.split("\t")[0].strip()
    if p == "/dev/null":
        return None
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    return p[2:] if p[:2] in ("a/", "b/") else p


def _done(h) -> bool:
    old = sum(1 for op, _ in h["lines"] if op in (" ", "-"))
    new = sum(1 for op, _ in h["lines"] if op in (" ", "+"))
    return old >= h["old_len"] and new >= h["new_len"]


def parse(text: str) -> list[dict]:
    """Return [{old, new, hunks:[{old_start, old_len, new_len, lines:[(op, text)]}], binary}]."""
    files: list[dict] = []
    cur, hunk = None, None
    for line in text.replace("\r\n", "\n").split("\n"):
        if hunk is not None and not _done(hunk):
            if line[:1] in (" ", "+", "-"):
                hunk["lines"].append((line[0], line[1:]))
                continue
            if line == "":
                hunk["lines"].append((" ", ""))
                continue
        if line.startswith("\\"):
            continue
        if line.startswith("diff --git "):
            cur, hunk = {"old": None, "new": None, "hunks": [], "binary": False, "git": True}, None
            files.append(cur)
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if m:
                cur["old"], cur["new"] = m.group(1), m.group(2)
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            if cur is None:
                cur = {"old": None, "new": None, "hunks": [], "binary": True}
                files.append(cur)
            cur["binary"] = True
        elif line.startswith("--- "):
            if cur is None or cur["hunks"] or not cur.get("git"):
                cur = {"old": None, "new": None, "hunks": [], "binary": False}
                files.append(cur)
            cur["old"], hunk = _strip(line[4:]), None
            cur["git"] = False
        elif line.startswith("+++ ") and cur is not None:
            cur["new"] = _strip(line[4:])
        elif line.startswith("new file mode") and cur is not None:
            cur["old"] = None
        elif line.startswith("deleted file mode") and cur is not None:
            cur["new"] = None
        else:
            m = _HUNK.match(line)
            if m and cur is not None:
                hunk = {"old_start": int(m.group(1)),
                        "old_len": int(m.group(2)) if m.group(2) is not None else 1,
                        "new_len": int(m.group(4)) if m.group(4) is not None else 1, "lines": []}
                cur["hunks"].append(hunk)
    return [f for f in files if f["hunks"] or f["binary"] or f["old"] or f["new"]]


def touched_paths(text: str) -> list[str]:
    out = []
    for f in parse(text):
        for p in (f.get("old"), f.get("new")):
            if p and p not in out:
                out.append(p)
    return out


def apply(root: Path, text: str) -> list[str]:
    """Apply a patch under `root`. Raises PatchError on any mismatch. Returns changed paths."""
    root = Path(root)
    changed = []
    for f in parse(text):
        if f["binary"]:
            raise PatchError(f"binary patch not allowed ({f.get('new') or f.get('old')})")
        target = f["new"] or f["old"]
        if target is None:
            raise PatchError("patch entry without a path")
        rp = Path(target)
        if rp.is_absolute() or ".." in rp.parts or ":" in target:
            raise PatchError(f"unsafe path {target}")
        path = root / rp
        src: list[str] = []
        if f["old"] is not None:
            op = root / f["old"]
            if not op.exists():
                raise PatchError(f"file to patch does not exist: {f['old']}")
            src = op.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        out, pos = [], 0
        for h in f["hunks"]:
            want = [t for op_, t in h["lines"] if op_ in (" ", "-")]
            start = max(h["old_start"] - 1, 0)
            if src[start:start + len(want)] != want:
                found = None
                for delta in range(1, 300):
                    for s in (start - delta, start + delta):
                        if s >= pos and src[s:s + len(want)] == want:
                            found = s
                            break
                    if found is not None:
                        break
                if found is None:
                    raise PatchError(f"hunk does not apply to {target} near line {h['old_start']}")
                start = found
            if start < pos:
                raise PatchError(f"overlapping hunks in {target}")
            out += src[pos:start]
            out += [t for op_, t in h["lines"] if op_ in (" ", "+")]
            pos = start + len(want)
        out += src[pos:]
        if f["new"] is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(out))
        changed.append(target)
    return changed


def make(old_text: str, new_text: str, path: str) -> str:
    """Unified diff (a/<path> b/<path>) from old to new text; empty string if identical."""
    a = old_text.replace("\r\n", "\n").splitlines(keepends=True)
    b = new_text.replace("\r\n", "\n").splitlines(keepends=True)
    d = "".join(difflib.unified_diff(a, b, f"a/{path}", f"b/{path}", n=3))
    return (f"diff --git a/{path} b/{path}\n" + d) if d else ""

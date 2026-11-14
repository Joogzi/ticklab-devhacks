"""Compile TickProbe with plain javac (no Gradle/Loom), jar it, install it into the ticklab Prism instance,
write its config, and write CAPTURE_READY.md.

Usage:
  python capture/build_mod.py                      # build + install for batch "a" (listed order)
  python capture/build_mod.py --batch b --order shuffled --seed 7
  python capture/build_mod.py --test-compile       # compile only, against any local 26.x jars (no install)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import discover_prism  # noqa: E402

MOD = HERE / "mod"
BUILD = HERE / "build"
JAR_NAME = "ticklab_capture.jar"
REPEAT_CHECK = ["sprint_release_sprint", "jump_hold", "look_diag_turn"]


def find_javac() -> str:
    cands = []
    if os.environ.get("JAVA_HOME"):
        cands.append(Path(os.environ["JAVA_HOME"]) / "bin" / "javac.exe")
    w = shutil.which("javac")
    if w:
        cands.append(Path(w))
    for root in (Path("C:/Program Files/Eclipse Adoptium"), Path("C:/Program Files/Java"),
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Eclipse Adoptium",
                 Path(os.environ.get("APPDATA", "")) / "PrismLauncher" / "java"):
        if root.exists():
            cands += sorted(root.glob("*/bin/javac.exe"), reverse=True)
    for c in cands:
        try:
            v = subprocess.run([str(c), "-version"], capture_output=True, text=True, timeout=30)
            out = (v.stdout + v.stderr).strip()
            if out.startswith("javac ") and int(out.split()[1].split(".")[0]) >= 25:
                return str(c)
        except Exception:
            continue
    raise SystemExit("No JDK >= 25 javac found (JAVA_HOME, PATH, Program Files, Prism java/). See docs/CAPTURE_SETUP.md step 1.")


def test_classpath() -> list[str]:
    """Any local Minecraft 26.x client jar + loader/mixin + libraries (compile check only)."""
    root = discover_prism.prism_roots()[0]
    mc = sorted((root / "libraries" / "com" / "mojang" / "minecraft").glob("26.*/minecraft-26.*-client.jar"))
    if not mc:
        raise SystemExit("no Minecraft 26.x client jar in Prism libraries for a test compile")
    loader = sorted((root / "libraries" / "net" / "fabricmc" / "fabric-loader").glob("*/*.jar"))[-1:]
    inst = {"minecraft": mc[-1].parent.name, "fabric_loader": loader[0].parent.name if loader else "?"}
    jars, probs = discover_prism.find_jars(root, inst)
    return [str(j) for j in jars]


def compile_mod(classpath: list[str]) -> Path:
    javac = find_javac()
    classes = BUILD / "classes"
    shutil.rmtree(classes, ignore_errors=True)
    classes.mkdir(parents=True)
    sources = sorted(str(p) for p in (MOD / "src").rglob("*.java"))
    argfile = BUILD / "javac.args"
    argfile.write_text("\n".join(['-cp', '"' + os.pathsep.join(classpath).replace("\\", "/") + '"']), encoding="utf-8")
    cmd = [javac, "--release", "25", "-proc:none", "-encoding", "UTF-8", f"@{argfile}", "-d", str(classes), *sources]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit("javac failed:\n" + p.stdout + p.stderr)
    jar = BUILD / JAR_NAME
    with zipfile.ZipFile(jar, "w", zipfile.ZIP_DEFLATED) as z:
        for base in (classes, MOD / "resources"):
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    info = zipfile.ZipInfo(str(f.relative_to(base)).replace("\\", "/"), (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, f.read_bytes())
    return jar


def install(sel: dict, jar: Path, batch: str, order: str, seed: int, only: list[str], repeat: list[str]) -> dict:
    if "ticklab" not in sel["name"].lower() and "ticklab" not in sel["id"].lower():
        raise SystemExit(f"refusing to touch instance {sel['name']!r}: name must contain 'ticklab'")
    game = Path(sel["game_dir"])
    (game / "mods").mkdir(parents=True, exist_ok=True)
    (game / "config").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(jar, game / "mods" / JAR_NAME)
    out_dir = HERE / "out" / batch
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    cfg = {"enabled": True, "scenarios_file": str(ROOT / "oracle" / "corpus_scenarios.json"), "out_dir": str(out_dir),
           "settle_ticks": 30, "order": order, "seed": seed, "repeat_check": repeat, "only": only,
           "quit_when_done": True}
    with open(game / "config" / "ticklab_capture.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def write_ready(sel: dict, cfg: dict, batch: str) -> None:
    text = f"""# CAPTURE_READY — please click Play

The TickLab capture mod is built and installed in Prism instance **{sel['name']}** (batch `{batch}`, order `{cfg['order']}`).

1. In Prism Launcher, select **{sel['name']}** and click **Play**.
2. Open the singleplayer world **ticklab**.
3. Don't touch anything. The mod runs {len(cfg['only']) or 33} scenarios (about 3 s each) and closes the game when it is done.
   Keyboard and mouse input is ignored while it runs. You can leave the window in the background.

The agent is polling `capture/out/{batch}/done.json` and will continue on its own.
"""
    with open(ROOT / "CAPTURE_READY.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-compile", action="store_true")
    ap.add_argument("--batch", default="a")
    ap.add_argument("--order", default="listed", choices=["listed", "reversed", "shuffled"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-repeat-check", action="store_true")
    ap.add_argument("--no-ready-file", action="store_true")
    a = ap.parse_args(argv)
    if a.test_compile:
        jar = compile_mod(test_classpath())
        print(f"test compile OK -> {jar} ({jar.stat().st_size} bytes)")
        return 0
    d = discover_prism.discover()
    if not d["selected"] or [p for p in d["problems"] if "missing" in p]:
        print("cannot build for the capture instance yet:")
        for p in d["problems"]:
            print("  -", p)
        return 2
    sel = d["selected"]
    jar = compile_mod(sel["classpath"])
    only = [s for s in a.only.split(",") if s]
    cfg = install(sel, jar, a.batch, a.order, a.seed, only, [] if a.no_repeat_check else REPEAT_CHECK)
    if not a.no_ready_file:
        write_ready(sel, cfg, a.batch)
    print(f"installed {JAR_NAME} into {sel['game_dir']}; batch {a.batch} ({a.order}); CAPTURE_READY.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

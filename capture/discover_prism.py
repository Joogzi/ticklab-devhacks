"""Locate Prism Launcher's data dir, its instances, and the jars needed to compile the capture mod.

Only instances whose name contains `ticklab` are ever selected. Prints diagnostics; never guesses silently.
Usage: python capture/discover_prism.py [--json]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MC_VERSION = "26.3"


def prism_roots() -> list[Path]:
    cands: list[Path] = []
    for var in ("PRISM_DATA_DIR", "PRISMLAUNCHER_DATA", "PRISM_LAUNCHER_DIR"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "PrismLauncher")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(Path(local) / "Programs" / "PrismLauncher")  # portable installs keep data here
    cands += [Path("C:/Program Files/PrismLauncher"), Path.home() / "scoop" / "persist" / "prismlauncher"]
    return [c for c in cands if (c / "instances").is_dir()]


def prism_exe() -> Path | None:
    for c in [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "PrismLauncher" / "prismlauncher.exe",
              Path("C:/Program Files/PrismLauncher/prismlauncher.exe")]:
        if c.exists():
            return c
    return None


def read_cfg(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.startswith("["):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def list_instances(root: Path) -> list[dict]:
    out = []
    for d in sorted((root / "instances").iterdir()):
        if not (d / "instance.cfg").exists():
            continue
        cfg = read_cfg(d / "instance.cfg")
        comps = {}
        mp = d / "mmc-pack.json"
        if mp.exists():
            try:
                for c in json.loads(mp.read_text(encoding="utf-8")).get("components", []):
                    comps[c.get("uid")] = c.get("version")
            except Exception:
                pass
        mcdir = d / ".minecraft" if (d / ".minecraft").exists() else d / "minecraft"
        out.append({"id": d.name, "name": cfg.get("name", d.name), "dir": str(d), "game_dir": str(d / ".minecraft"),
                    "game_dir_exists": mcdir.exists(), "minecraft": comps.get("net.minecraft"),
                    "fabric_loader": comps.get("net.fabricmc.fabric-loader"),
                    "intermediary": comps.get("net.fabricmc.intermediary")})
    return out


def _maven(root: Path, group: str, art: str, ver: str) -> Path:
    return root / "libraries" / Path(*group.split(".")) / art / ver / f"{art}-{ver}.jar"


def find_jars(root: Path, inst: dict) -> tuple[list[Path], list[str]]:
    """Return (classpath jars, problems)."""
    probs, jars = [], []
    client = root / "libraries" / "com" / "mojang" / "minecraft" / inst["minecraft"] / f"minecraft-{inst['minecraft']}-client.jar"
    if client.exists():
        jars.append(client)
    else:
        probs.append(f"client jar missing: {client} (launch the instance once so Prism downloads it)")
    fl = _maven(root, "net.fabricmc", "fabric-loader", inst["fabric_loader"] or "?")
    if fl.exists():
        jars.append(fl)
    else:
        probs.append(f"fabric-loader jar missing: {fl}")
    mix = sorted((root / "libraries" / "net" / "fabricmc" / "sponge-mixin").glob("*/*.jar"))
    if mix:
        jars.append(mix[-1])
    else:
        probs.append("sponge-mixin jar missing under libraries/net/fabricmc/sponge-mixin")
    # Everything else the client references (authlib, brigadier, datafixer, joml, slf4j, ...): add all
    # non-native jars from the Minecraft version's meta-declared libraries if present, else a broad scan.
    meta = root / "meta" / "net.minecraft" / f"{inst['minecraft']}.json"
    if meta.exists():
        try:
            for lib in json.loads(meta.read_text(encoding="utf-8")).get("libraries", []):
                g, a, v = lib["name"].split(":")[:3]
                p = _maven(root, g, a, v)
                if p.exists() and "natives" not in p.name:
                    jars.append(p)
        except Exception as e:
            probs.append(f"could not parse {meta}: {e}")
    for sub in ("org/ow2/asm", "com/mojang", "org/joml", "org/slf4j", "it/unimi", "com/google"):
        for p in (root / "libraries" / Path(sub)).rglob("*.jar") if (root / "libraries" / Path(sub)).exists() else []:
            if "natives" not in p.name and p not in jars and "minecraft-" not in p.name:
                jars.append(p)
    return jars, probs


def discover(verbose: bool = True) -> dict:
    res = {"roots": [], "instances": [], "selected": None, "problems": [], "exe": str(prism_exe() or "")}
    roots = prism_roots()
    res["roots"] = [str(r) for r in roots]
    if not roots:
        res["problems"].append("Prism data directory not found (looked in PRISM_* env vars, %APPDATA%\\PrismLauncher, portable installs)")
        return res
    root = roots[0]
    insts = list_instances(root)
    res["instances"] = insts
    cands = [i for i in insts if "ticklab" in i["name"].lower() or "ticklab" in i["id"].lower()]
    if not cands:
        res["problems"].append("no Prism instance whose name contains 'ticklab' (docs/CAPTURE_SETUP.md step 2)")
        return res
    good = [i for i in cands if i["minecraft"] == MC_VERSION and i["fabric_loader"]]
    if not good:
        i = cands[0]
        res["problems"].append(f"instance '{i['name']}' has minecraft={i['minecraft']} fabric_loader={i['fabric_loader']}; "
                               f"need minecraft {MC_VERSION} + Fabric Loader")
        return res
    sel = dict(good[0])
    jars, probs = find_jars(root, sel)
    sel["root"] = str(root)
    sel["classpath"] = [str(j) for j in jars]
    res["selected"] = sel
    res["problems"] += probs
    return res


if __name__ == "__main__":
    r = discover()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2))
    else:
        print("Prism roots:", r["roots"] or "none")
        for i in r["instances"]:
            print(f"  instance {i['name']!r:32} mc={i['minecraft']} fabric={i['fabric_loader']}")
        sel = r["selected"]
        print("selected:", sel["name"] if sel else "none", f"({len(sel['classpath'])} jars)" if sel else "")
        for p in r["problems"]:
            print("PROBLEM:", p)

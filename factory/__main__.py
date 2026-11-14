"""TickLab command line: python -m factory <command> [...]."""
from __future__ import annotations

import argparse
import importlib
import sys

COMMANDS = {
    "doctor": ("factory.doctor", "report tools, Prism, oracle mode"),
    "check": ("factory.check", "fast LLM-free health check (gate table)"),
    "calibrate": ("factory.calibrate", "validate pristine sim against the oracle corpus; write split"),
    "selftest": ("factory.selftest", "run the verifier on known fixes, traps and adversarial patches"),
    "verify": ("factory.verifier", "run the verifier on a patch for a case"),
    "run": ("factory.loop", "run the agent loop on one case"),
    "bench": ("factory.bench", "benchmark baseline vs lab"),
    "report": ("factory.report", "generate report/index.html"),
    "demo": ("factory.demo", "LLM-free demo: calibrate + selftest + report"),
    "devpost-fill": ("factory.devpost_fill", "substitute real numbers into DEVPOST.md"),
    "bugs": ("factory.bugs", "list/apply/inspect seeded bugs"),
    "discover": ("factory.discover", "random scenario discovery + minimization (Tier 2)"),
}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # agent text may contain any Unicode; Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print("usage: python -m factory <command> [args]\n")
        for k, (_, d) in COMMANDS.items():
            print(f"  {k:13} {d}")
        return 0 if (not argv or argv[0] in ("-h", "--help")) else 2
    mod_name, _ = COMMANDS[argv[0]]
    try:
        mod = importlib.import_module(mod_name)
    except ModuleNotFoundError as e:
        if e.name == mod_name:
            print(f"{argv[0]}: not built yet")
            return 3
        raise
    return int(mod.main(argv[1:]) or 0)


if __name__ == "__main__":
    sys.exit(main())

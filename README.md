# TickLab

**An agentic dev workflow for behavioral bugs, with a verifier the agent can't influence.**

Coding agents can edit game code, but game bugs are behavioral, stateful and timing-dependent. An agent
that only reads source can't tell whether its fix actually works. TickLab gives the agent a **lab**: a
headless, deterministic simulator plus an **oracle** of recorded real behavior. With it the agent can
reproduce a reported bug, diff per-tick traces against known-correct behavior, save the repro, patch the
code, and re-run. A separate **verifier** decides whether a patch is accepted. The agent has no way to
influence it: the verifier runs the exact reproduction, a visible regression suite, **hidden holdout
scenarios** and a determinism check, and it rejects patches that touch tests, the oracle or the verifier.

The general problem is **reproducing the behavior of a reference implementation** (a port, a rewrite, a
migration, a platform-parity effort), where verification is the hard part. Minecraft 26.3 player movement
is the testbed. The simulator is the "port", and vanilla Minecraft is the reference.

> Built for DevHacks 2026 (Ohio State), Riot Games track 2 "Agentic development".

## Quickstart (Windows, Python 3.11+)

```powershell
python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt   # only needs `mcp`
python -m factory doctor      # tools, Prism instance, oracle mode (thin/full)
python -m factory check       # fast LLM-free health check: every gate PASS/FAIL/SKIPPED
python -m factory calibrate   # pristine simulator vs every real vanilla trace available
python -m factory selftest    # verifier vs reference fixes, trap fixes, adversarial patches
python -m factory verify --case b2_sprint_stop_late --patch bugs/b2_sprint_stop_late/trap.patch
```

## Repository map

| Path | What |
|---|---|
| `sim/` | **mcsim**, the small project the agent modifies: a tick-based player-movement simulator (Python; `python -m mcsim run scenario.json`) |
| `oracle/` | vanilla corpus (`corpus/`, captured from real Minecraft), comparator, tolerances, visible/holdout split |
| `bugs/` | harness-private seeded-bug cases: patches, developer-style reports, traps, hidden variants |
| `factory/` | the harness: verifier, selftest, calibrate, check, lab MCP server, agent driver, loop, bench, report |
| `capture/` | TickProbe Fabric mod + Prism Launcher tooling that records real vanilla traces (optional; Windows) |
| `docs/ENGINEERING.md` | architecture, tradeoffs, failure modes, evidence |

## Reproducing without Minecraft

The simulator, verifier, harness, benchmark and report only read the committed corpus traces, so you
don't need Minecraft to reproduce any result. Capture (`capture/`, see `docs/CAPTURE_SETUP.md`) is only for
recording new ground truth.

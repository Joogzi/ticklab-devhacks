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

## Results (measured, not claimed)

The same agent (Claude Code, model <!--fill:lab_models-->haiku<!--/fill-->), on the same <!--fill:n_cases-->9<!--/fill--> seeded behavior bugs, with and without the
lab, judged by the same independent verifier. <!--fill:n_runs-->36<!--/fill--> runs; up to 2 attempts each. Source: `results/bench.jsonl`
(append-only), aggregated in `results/summary.json`.

<!--fill:results_table-->

| metric | baseline (no lab) | lab |
|---|---|---|
| accepted by verifier | 13 | 14 |
| runs | 18 | 18 |
| false 'done' claims | 8 | 4 |
| mean attempts | 1.33 | 1.22 |
| median time to accept (s) | 23.3 | 28.4 |
| previously-passing scenarios broken by final patches | 0 | 0 |
| mean cost per run (USD) | 0.0196 | 0.0158 |

<!--/fill-->

The verifier `selftest` passed <!--fill:selftest_passed-->21<!--/fill-->/<!--fill:selftest_total-->21<!--/fill-->: reference fixes accepted, naive fixes rejected,
8 cheating patches rejected (edit corpus/tolerance/verifier/tests, hardcode the repro, add a dependency, read oracle files,
touch protected files). See `results/selftest.json`.

**What the numbers say.** With this agent and these bugs, the lab barely changed *how many* bugs got fixed:
six easy bugs were fixed every time in both conditions, b5 (diagonal input) was fixed by neither, and b6/c9 were
split. The clear difference is **trust**: without the lab, the agent made twice as many wrong FIXED claims
(<!--fill:baseline_false_done_attempts-->8<!--/fill--> of <!--fill:baseline_fixed_claims-->21<!--/fill--> claims vs <!--fill:lab_false_done_attempts-->4<!--/fill--> of
<!--fill:lab_fixed_claims-->18<!--/fill-->). In both conditions, every one of those false claims was caught by the verifier, not by a person.
One baseline run was rejected because the tool-log scan flagged a benign `cd ../..` inside the workspace. Discounting it,
baseline would be 14/18, so treat acceptance as a tie. The scan has since been fixed to resolve paths before flagging.

**Live confirm in the real game.** The scenarios the agent wrote while debugging (its saved repros) were replayed in
real Minecraft 26.3 by the capture mod. In 4/4, the real recording matches the agent's accepted patch on every tick and
diverges from the original buggy code (`results/live_confirm.json`, `python capture/live_confirm.py analyze`). The agent
never touches the game; the mod plays the agent's inputs. A third capture run in the same session re-recorded all 33
ground-truth scenarios byte-identically.

**Caveats.** Small n (<!--fill:n_runs-->36<!--/fill--> runs, one model): these are counts, with no significance claims. Oracle: <!--fill:oracle_coverage-->33<!--/fill-->
real Minecraft 26.3 recordings (<!--fill:oracle_mode-->full<!--/fill--> mode), which the simulator matches exactly. Hidden *variants* with other
timings are answered by the reference layer, which is validated against those recordings. An earlier run of the same
benchmark against a pre-correction oracle is kept in `results/summary_thin_mode.json` and superseded by the numbers
above (see `docs/ENGINEERING.md`). Open `report/index.html` (`python -m factory report`) to replay any run tick by tick.

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

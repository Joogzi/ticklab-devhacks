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

**What's in it:** a movement simulator that matches **44/44 real Minecraft 26.3 recordings** (open floor and a wall),
11 seeded behavior bugs, a 6-gate verifier with hidden holdouts, lab tools for the agent (MCP), a benchmark of the same
agent with and without the lab, automatic bug discovery, and an offline replay report.

> Built for DevHacks 2026 (Ohio State), Riot Games track 2 "Agentic development".

## Quickstart (Windows, Python 3.11+)

```powershell
python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt   # only needs `mcp`
python -m factory doctor      # tools, Prism instance, oracle mode (thin/full)
python -m factory check       # fast LLM-free health check: every gate PASS/FAIL/SKIPPED
python -m factory calibrate   # pristine simulator vs every real vanilla trace available
python -m factory selftest    # verifier vs reference fixes, trap fixes, adversarial patches
python -m factory verify --case b2_sprint_stop_late --patch bugs/b2_sprint_stop_late/trap.patch
python -m factory discover    # random scenarios -> minimal repros -> symptom clusters (no LLM)
python -m factory report      # report/index.html (offline; light/dark; #bug=0&t=24 deep links)
python -m factory run --case b11_wall_air_velocity --condition lab   # one real agent run (needs the claude CLI)
```

## Results (measured, not claimed)

The same agent (Claude Code, models <!--fill:models-->haiku and sonnet<!--/fill-->), on the same <!--fill:n_cases-->11<!--/fill--> seeded behavior bugs, with and without the
lab, judged by the same independent verifier against <!--fill:oracle_coverage-->44<!--/fill--> real Minecraft 26.3 recordings.
<!--fill:n_runs-->88<!--/fill--> runs (11 bugs × 2 conditions × 2 trials × 2 models), up to 2 attempts each. Source: `results/bench.jsonl`
(append-only), aggregated per model in `results/summary.json`.

<!--fill:results_table-->

| metric | haiku: baseline | haiku: lab | sonnet: baseline | sonnet: lab |
|---|---|---|---|---|
| accepted by the verifier | 20 / 22 | 20 / 22 | 17 / 22 | 22 / 22 |
| wrong "FIXED" claims | 7 / 26 | 0 / 19 | 12 / 29 | 1 / 23 |
| median time to accept (s) | 57.2 | 41.0 | 15.5 | 18.5 |
| regressions shipped | 0 | 0 | 0 | 0 |
| mean cost per run (USD) | 0.0211 | 0.0134 | 0.0941 | 0.105 |

<!--/fill-->

**What the numbers say.**
* **The lab mostly stops false "done".** Without the lab, the agent claimed FIXED on a patch the verifier rejected
  <!--fill:haiku_baseline_false_done_attempts-->7<!--/fill--> times (haiku) and <!--fill:sonnet_baseline_false_done_attempts-->12<!--/fill--> times (sonnet). With the
  lab: <!--fill:haiku_lab_false_done_attempts-->0<!--/fill--> and <!--fill:sonnet_lab_false_done_attempts-->1<!--/fill-->.
* **With the stronger model, the lab also fixes more:** sonnet was accepted on <!--fill:sonnet_lab_accepted-->22<!--/fill-->/<!--fill:sonnet_lab_runs-->22<!--/fill-->
  bugs with the lab vs <!--fill:sonnet_baseline_accepted-->17<!--/fill-->/<!--fill:sonnet_baseline_runs-->22<!--/fill--> without. The baseline failures are the subtle
  ones: the one-tick sprint timing (b2), the air-acceleration trap (b6) and the compound case (c9). With haiku, acceptance
  was a tie (<!--fill:haiku_lab_accepted-->20<!--/fill-->/<!--fill:haiku_lab_runs-->22<!--/fill--> each), but lab runs reached an accepted fix faster
  (<!--fill:haiku_lab_median_time_to_accept_s-->41.0<!--/fill--> s vs <!--fill:haiku_baseline_median_time_to_accept_s-->57.2<!--/fill--> s median) and cheaper.
* **In every condition, every wrong claim was caught by the verifier** before it could ship, and no final patch broke
  a scenario that passed before.

**Integrity note.** One sonnet baseline run was rejected because the tool-log scan misread a harmless `cd ../../..`
back to the workspace root (the shell keeps its working directory between commands). Without that flag its patch is
accepted, so that baseline is 18/22 discounting it. The recorded result is kept as-is, and the scan now tracks the
working directory across commands.

**Discovery.** With no report and no agent, `python -m factory discover` found <!--fill:discovery_found-->11<!--/fill-->/<!--fill:discovery_total-->11<!--/fill-->
seeded bugs from random scenarios and shrank each one to a minimal repro (see `results/discovery.json`).

**Live confirm in the real game.** The scenarios the agent wrote while debugging (its saved repros) were replayed in
real Minecraft 26.3 by the capture mod. In 4/4, the real recording matches the agent's accepted patch on every tick and
diverges from the original buggy code (`results/live_confirm.json`, `python capture/live_confirm.py analyze`). The agent
never touches the game; the mod plays the agent's inputs. A third capture run in the same session re-recorded all 33
ground-truth scenarios byte-identically.

**Caveats.** Small n (<!--fill:n_runs-->88<!--/fill--> runs, two models): these are counts, with no significance claims. Ground truth is
<!--fill:oracle_coverage-->44<!--/fill--> real recordings on two fixtures (open floor and one wall). Hidden variants with other timings use the
reference layer, which matches all of those recordings exactly. Earlier benchmark runs judged against smaller or
pre-correction oracles are kept in `results/summary_thin_mode.json` and `results/summary_flat_only.json` and superseded
by the numbers above (see `docs/ENGINEERING.md`). Open `report/index.html` (`python -m factory report`) to replay any run.

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

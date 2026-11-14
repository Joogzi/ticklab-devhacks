# TickLab — engineering notes

(Living document. Sections are appended as phases land; the final architecture/tradeoffs/failure-mode
write-up is completed in Phase 8.)

## Simulator model and calibration (Phase 1)

**Implementation language.** `cargo` is not installed on the build laptop, so `mcsim` is implemented in
Python with the module structure the spec gives for the Rust crate (`input`, `world`, `collision`,
`physics`, `player`, `trace`, `main`, plus `fmath` for Java float emulation). CLI:
`python -m mcsim run <scenario.json> [--out trace.jsonl] [--initial state.json]` with `PYTHONPATH=sim/src`
(the harness resolves this in one helper, `factory.util.sim_cmd`).

**Where the model comes from.** Minecraft 26.x ships unobfuscated, so instead of recalling vanilla movement
from memory, the per-tick order was read from bytecode (`javap -c`) of the closest locally available client
jar (26.1.2; 26.3 is not downloaded yet). This was a dev-time reading only; nothing from the jar is in the repo.
Findings that matter for fidelity (and that the seeded bugs later perturb):

| Topic | Vanilla behavior (as read) |
|---|---|
| Input vector | Keyboard impulses (left−right, forward−back) are **normalized** to unit length, then scaled by `0.98f`, then by the sneak attribute (`0.3f`) if crouching, then mapped from the unit circle onto the unit square (`modifyInputSpeedForSquareMovement`). All float math. |
| Crouch timing | The `crouching` flag (which drives the sneak slowdown and blocks sprint start) is computed from the shift key as of the **previous** tick; the pose flips to `CROUCHING` at the end of the current tick. |
| Sprint | Starts when not sprinting, forward impulse > 1e-5, not crouching, sprint key down. Stops when forward impulse is gone (or horizontal collision). Releasing the sprint key alone does **not** stop sprinting. |
| Speed lag | Ground speed uses the cached `speed` field, refreshed from the attribute **after** travel, so a sprint start/stop changes ground acceleration one tick later. Air acceleration (`0.02f` / `0.025999999f`) and the sprint-jump boost read `isSprinting()` immediately. |
| Velocity threshold | Player: if `vx²+vz² < 9e-6` zero both; if `|vy| < 0.003` zero it. Applied at the start of the living-entity step, before the jump. |
| Jump | If jump held, on ground and `noJumpDelay == 0`: `vy = max(0.42f, vy)`, sprint adds `(-sin, cos)(yaw) * 0.2` using Mth's 65536-entry float sine table (now taking a double argument); cooldown 10. Releasing jump resets the cooldown to 0. |
| Travel | friction = `0.6f` on ground (block below, from last tick's `on_ground`) else 1; accel = `speed * (0.21600002f / f³)` on ground; move with collision; then `vy = (vy − 0.08) * 0.98f`, horizontal `× f*0.91f`. |
| Collision | Y first, then the larger horizontal axis, then the other; epsilon 1e-7; `on_ground = vertical collision && dy < 0`; blocked components zeroed; landing zeroes vy. |

**Calibration result (thin mode).** `python -m factory calibrate` against the four earlier real-vanilla
goldens (`lab/golden/{idle,walk,jump,look}`, converted into gitignored `oracle/dev_goldens/`, initial state
matched: settled standing at (0.5, 100, 0.5), `vy = -0.0784000015258789`): **4/4 match, max error 0.0 in
every field** (bit-exact). Sprint, sneak, diagonal and turning behavior is not covered by these goldens; it
is validated only when the real corpus from `capture/` lands (Phase C).

## Architecture and data flow

```
 bug report (untrusted text) ──► CASE.md ──► subject agent (claude -p, fresh process per attempt)
                                              │  tools: Read/Edit/Write/Glob/Grep, Bash = `python sim/run.py …` + read-only git
                                              │  lab condition only: MCP server `lab` (factory/labtools_mcp.py, harness-owned)
                                              ▼
 isolated workspace (%USERPROFILE%\.ticklab\ws\<case>\<cond>-<n>)  = buggy sim/ + CASE.md + scenarios/visible (inputs only)
                                              │  harness extracts `git diff` vs the base commit
                                              ▼
 verifier (factory/verifier.py, in the harness) ── clean temp checkout of pristine+bug, apply ONLY the diff
   G0 integrity → G1 build → G2 repro → G3 visible suite + unit tests → G4 holdouts → G5 determinism → verdict.json
                                              │                                   ▲
                                              │                    oracle: vanilla corpus (oracle/corpus) first,
                                              │                    else reference layer (oracle/reference = pristine sim copy)
                                              ▼
 accepted ──► done            rejected ──► feedback (identical for both conditions) appended to CASE.md ──► next attempt
```

* **Trust boundary.** Nothing the agent writes is trusted except the diff to `sim/src/**`, and that diff is
  applied to a fresh checkout. The verifier, oracle, tolerances, tests, holdouts and bugs live in the repo, and
  the agent's workspace sits outside the repo tree. That layout also stops Claude Code from auto-loading this
  repo's own agent instruction/notes files, which describe the seeded bugs. Candidate code only ever runs in a
  subprocess (`factory/simrunner.py`), never inside the harness process.
* **Claims vs verdicts.** The agent must end with `STATUS: FIXED|UNABLE`. The claim is recorded separately
  from the verdict, so "false done" (claimed FIXED, verifier rejected) is a measured quantity.
* **Feedback symmetry.** Both conditions get the same post-attempt feedback: gate names, pass/fail, counts,
  the first divergence for *visible* failures, and only counts + family labels for holdout failures. The
  experiment therefore isolates the lab tools.

## Why it is built this way (tradeoffs, rejected alternatives)

* **Why not trust agent claims?** Behavior bugs pass a casual read, and an agent can sincerely "fix"
  something plausible and say FIXED. Only an independent check of behavior settles it. How often agents'
  claims were wrong is measured in the benchmark (false-done rate), not assumed here.
* **Why hidden holdouts?** Any check the agent can see, it can satisfy without fixing the behavior. That covers
  editing tests, hardcoding the repro, or a naive fix that only covers the reported input. Selftest proves the
  holdouts catch a repro hardcoded by scenario name (adversarial patch `d`) and a naive sprint fix that also
  stops sprinting on key release (trap `b2`). Both pass G2 + G3 and fail only G4.
* **Why a reference layer?** Real captures are slow and finite. A pristine copy of the simulator answers
  variants nobody recorded (hidden variants, fuzzing). It is trusted only as far as calibration against vanilla
  validates it, and every answer is labeled `provenance: reference` or `vanilla`.
* **Why headless/deterministic?** Agents need many cheap experiments (each sim run takes milliseconds), and
  determinism makes a divergence a fact rather than a flake (G5 runs the whole suite twice, byte-identical).
* **Why read vanilla's bytecode?** Minecraft 26.x is unobfuscated, so the exact per-tick order can be read
  with `javap`. That beat recollection: the model was bit-exact on the first try against the real goldens.
* **Rejected:** letting the agent run the verifier (the information leak defeats holdouts); `git apply`
  inside the repo tree (path resolution against the outer repo); OS sandboxing (not available in the time
  box; containment = workspace isolation + tool allow-list + post-hoc tamper scan + G0 capability scan).

## Failure modes (how it breaks, how we detect it)

| Failure | Detection / mitigation |
|---|---|
| Agent edits tests, tolerances, corpus, verifier | G0 path policy (only `sim/src/*.py`), protected-file hash manifest before/after each attempt |
| Agent special-cases the reported input | G4 hidden holdouts (real-vanilla holdout split + per-family reference variants) |
| Agent reads oracle data at runtime / adds a dependency | G0 capability scan: new non-allowlisted imports, new `open`/`exec`/`eval`/`getattr`/dunder use |
| Agent wanders outside its workspace | Claude Code permission mode denies it; post-hoc tool-log scan flags `TAMPER_SUSPECT` (absolute paths outside the workspace, `..` traversal, repo path) and G0 rejects |
| Prompt injection via the bug report | The report is wrapped as quoted untrusted data; the system prompt says so; least-privilege tools limit the blast radius |
| LLM slow, stuck or wrong | Per-attempt wall-clock cap + `--max-budget-usd`, process-tree kill on timeout; up to N attempts; the verdict never depends on the LLM |
| Oracle wrong (reference layer) | Calibration against every real vanilla trace; provenance on every answer; thin-mode banner everywhere |
| Flaky sim | G5 determinism (two full runs, byte-identical) |
| Weak tests letting a wrong patch through | Holdouts + per-field tolerance 1e-7; every seeded bug diverges ≥ 100× tolerance (checked by `factory bugs check`) |

## Answers to the mentors' questions

* **Who is this for, and what do they do differently?** Teams doing behavior-parity work (ports,
  rewrites, engine migrations, server re-implementations). Instead of a developer reproducing and checking
  every agent patch by hand, they write a report and review only patches the verifier accepted, with a replay
  of the evidence.
* **What does it add beyond engine/IDE agent integrations?** The oracle-backed lab (per-tick diffs against
  recorded real behavior) and an independent acceptance gate with hidden holdouts. IDE integrations let an
  agent edit and run code; they don't tell anyone whether the behavior is now right.
* **Can the agent pass by changing the test?** No. Any change outside `sim/src` is rejected at G0, and
  tests/oracle/verifier live outside the agent's workspace. Selftest proves 8 cheating patches are rejected.
* **Where is the LLM in the loop, and what happens when it is slow or wrong?** Only in the attempt step.
  Timeouts and budgets bound it; wrong patches are rejected with feedback; the verdict is LLM-free.
* **How does it fail?** See the table above. Its weakest point is oracle coverage: where no real trace
  exists, correctness rests on the calibrated reference model.

## Evidence: what was measured, how, and how much to trust it

**Benchmark.** `python -m factory bench`: <!--fill:n_cases-->9<!--/fill--> cases × {baseline, lab} × 2 trials, model <!--fill:lab_models-->haiku<!--/fill-->,
MAX_ATTEMPTS=2, 600 s per attempt. Every run record is in `results/bench.jsonl` (append-only).

<!--fill:results_table-->

| metric | baseline (no lab) | lab |
|---|---|---|
| accepted by verifier | 13 | 16 |
| runs | 18 | 18 |
| false 'done' claims | 9 | 2 |
| mean attempts | 1.33 | 1.28 |
| median time to accept (s) | 23.9 | 24.3 |
| previously-passing scenarios broken by final patches | 23 | 0 |
| mean cost per run (USD) | 0.0163 | 0.0182 |

<!--/fill-->

* **Acceptance** = the verifier accepted the final patch (agent claims are ignored).
* **False "done"** = an attempt that ended `STATUS: FIXED` but was rejected. Baseline: <!--fill:baseline_false_done_attempts-->9<!--/fill-->
  of <!--fill:baseline_fixed_claims-->22<!--/fill--> FIXED claims; lab: <!--fill:lab_false_done_attempts-->2<!--/fill--> of <!--fill:lab_fixed_claims-->18<!--/fill-->. This is the "don't
  trust the agent saying it's done" problem, measured.
* **Regressions** = scenarios that matched before the patch but diverge after it, summed over final patches.
* **Time**: the median time to an accepted patch is about the same in both conditions (<!--fill:baseline_median_time_to_accept_s-->23.9<!--/fill--> s vs
  <!--fill:lab_median_time_to_accept_s-->24.3<!--/fill--> s). The lab doesn't make easy bugs faster; it changes outcomes on the hard ones and
  makes the agent's claims trustworthy. Cost: about $<!--fill:baseline_mean_cost_usd-->0.0163<!--/fill--> (baseline) vs $<!--fill:lab_mean_cost_usd-->0.0182<!--/fill--> (lab) per run.

**Where the difference comes from.** b1, b2, b3, b4, b7 and b8 were fixed in every run in both conditions: a modern
model fixes them by reading the code plus the report (a ceiling effect, reported as-is). The conditions differ on b5
(diagonal input mapping, invisible without reference behavior), b6 (air acceleration; its naive fix is a trap) and c9
(compound bug with the vague report "Sprint-jumping is off"). The "plausible-looking" bugs were not all hard for the
agent: b2, b4, b7 and b8 look plausible but were still found by reading.

**Integrity events (reported, not hidden).**
* <!--fill:n_invalidated-->3<!--/fill--> early pilot runs were invalidated by append-only records in `bench.jsonl`. These were harness
  false positives at G0: the protected-file manifest included report/demo files the builder was editing during the bench,
  and the tool-log scan misread an escaped `
` in edited code as the path `t:/n`. Both were fixed (the manifest now covers
  only verdict-affecting files, and the scan reads only path fields). Re-scanning all stored streams with the fixed
  scanner found 0 hits, and the runs were repeated.
* <!--fill:baseline_tamper_suspect_runs-->2<!--/fill--> baseline runs were flagged TAMPER_SUSPECT by the tool-log scan. Manual inspection
  found both benign: a `../../scenarios/...` relative path used from `sim/src` (stays inside the workspace; the command
  was outside the allow-list and was denied anyway), and an Edit to a mistyped home directory outside the workspace.
  Re-verifying both patches without the scan rejects them at G2 anyway, so neither outcome depends on the flag.
  The scan is deliberately conservative.

**How much to trust it.** The verdicts are deterministic and reproducible (`python -m factory verify --case <id>
--patch results/featured/<run>/attempt<n>.patch`). Behavioral ground truth is thin. Only 4 real vanilla recordings
(idle/walk/jump/look) back the model directly, bit-exact. Sprint, sneak, diagonal and turning semantics come from
reading the 26.1.2 client bytecode and are not yet confirmed by 26.3 recordings (the capture tooling is built; see
`docs/CAPTURE_SETUP.md`). If the real game differs, the corpus would move the oracle and every seeded bug would need
re-validation (`python -m factory calibrate && python -m factory bugs check && python -m factory selftest`). n is small
(18 runs per condition, one model), so treat the numbers as a demonstration, not an effect size.

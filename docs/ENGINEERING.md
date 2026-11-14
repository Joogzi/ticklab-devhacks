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
| Sprint speed timing | In the 26.1.2 bytecode the cached `speed` field is refreshed after travel (a one-tick lag). **Real 26.3 recordings show no lag**: sprint speed applies on the same tick sprinting starts. The model follows the recordings (see below). Air acceleration (`0.02f` / `0.025999999f`) and the sprint-jump boost read `isSprinting()` immediately. |
| Velocity threshold | Player: if `vx²+vz² < 9e-6` zero both; if `|vy| < 0.003` zero it. Applied at the start of the living-entity step, before the jump. |
| Jump | If jump held, on ground and `noJumpDelay == 0`: `vy = max(0.42f, vy)`, sprint adds `(-sin, cos)(yaw) * 0.2` using Mth's 65536-entry float sine table (now taking a double argument); cooldown 10. Releasing jump resets the cooldown to 0. |
| Travel | friction = `0.6f` on ground (block below, from last tick's `on_ground`) else 1; accel = `speed * (0.21600002f / f³)` on ground; move with collision; then `vy = (vy − 0.08) * 0.98f`, horizontal `× f*0.91f`. |
| Collision | Y first, then the larger horizontal axis, then the other; epsilon 1e-7; `on_ground = vertical collision && dy < 0`; blocked components zeroed; landing zeroes vy. |

**Calibration result (thin mode).** `python -m factory calibrate` against the four earlier real-vanilla
goldens (`lab/golden/{idle,walk,jump,look}`, converted into gitignored `oracle/dev_goldens/`, initial state
matched: settled standing at (0.5, 100, 0.5), `vy = -0.0784000015258789`): **4/4 match, max error 0.0 in
every field** (bit-exact). Sprint, sneak, diagonal and turning behavior is not covered by these goldens; it
is validated only when the real corpus from `capture/` lands (Phase C).

**Calibration result (full mode, real 26.3 corpus).** TickProbe captured all 33 corpus scenarios from
Minecraft 26.3 (Fabric Loader 0.20.1, Java 25) through Prism Launcher, in two batches: listed order with 3
in-batch repeats, then shuffled order (seed 7). Every normalized trace is **byte-identical** across the two batches
and across the repeats (order independence + no state leakage, `oracle/corpus/INDEX.json`). The earlier lab's real
`walk` golden and the new corpus `walk_f20` (same inputs, same initial state) agree with **0.0** difference over 30
ticks, which independently validates the new mod.

The first comparison matched 22/33 scenarios. All 11 mismatches had a single cause, visible on the tick sprinting
starts: real 26.3 applies sprint speed immediately (`vz` 0.06956 = 0.13·0.98·0.546), while the model taken from
the 26.1.2 bytecode applied it one tick late (0.05351). After a one-line fix (refresh the speed before travel),
`python -m factory calibrate` matches **33/33 real traces** plus 4/4 dev goldens within tolerance. The
seeded-bug patches were regenerated from the corrected simulator. All construction rules still hold, every bug's
divergences now land on real vanilla scenarios, and the selftest is still 21/21. This is the workflow the project
argues for: a model that looked right from source reading was corrected only by recorded behavior.


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
MAX_ATTEMPTS=2, 600 s per attempt, judged against the real Minecraft 26.3 corpus. Every run record is in
`results/bench.jsonl` (append-only).

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

* **Acceptance** = the verifier accepted the final patch (agent claims are ignored).
* **False "done"** = an attempt that ended `STATUS: FIXED` but was rejected. Baseline: <!--fill:baseline_false_done_attempts-->8<!--/fill-->
  of <!--fill:baseline_fixed_claims-->21<!--/fill--> FIXED claims; lab: <!--fill:lab_false_done_attempts-->4<!--/fill--> of <!--fill:lab_fixed_claims-->18<!--/fill-->.
* **Regressions** = scenarios that matched before the patch but diverge after it, summed over final patches.
* **Time/cost**: the median time to an accepted patch is <!--fill:baseline_median_time_to_accept_s-->23.3<!--/fill--> s (baseline) vs
  <!--fill:lab_median_time_to_accept_s-->28.4<!--/fill--> s (lab); mean cost per run $<!--fill:baseline_mean_cost_usd-->0.0196<!--/fill--> vs $<!--fill:lab_mean_cost_usd-->0.0158<!--/fill-->.
  The lab does not make easy bugs faster.

**Interpretation (honest).** b1, b2, b3, b4, b7 and b8 were fixed in every run in both conditions: a modern model
fixes them from the code plus the report (a ceiling effect, even though four of them look "plausible"). b5 (diagonal
input mapping) was fixed by nobody. b6 (air acceleration, with a naive-fix trap) was fixed once, only with the lab, and
c9 (compound, vague report) once in each condition. So on *acceptance*, the lab made little difference for this model
and these bugs. The effects that do show: wrong FIXED claims halved with the lab (8 vs 4; 38% vs 22% of FIXED claims), and in both
conditions the independent verifier caught every wrong claim before it could ship. In the hackathon framing, the
verifier, not the agent, is what makes agentic parity work trustworthy, and the lab mostly makes the agent's own
judgment better calibrated.

**History: the benchmark was re-run when the real corpus landed.** The first full benchmark (36 runs) used the
reference layer before any 26.3 recordings existed. It reported baseline 13/18 vs lab 16/18, false done 9 vs 2,
and regressions 23 vs 0 (`results/summary_thin_mode.json`). The real recordings then showed that the model's sprint
timing was off by one tick (see Calibration), which changed the oracle for every sprint scenario. All 36 runs were
superseded by append-only records and the benchmark was repeated. The smaller effect above is the result we stand
behind; the earlier, larger gap partly came from judging against a model that was wrong about sprint timing.

**Integrity events (reported, not hidden).**
* <!--fill:n_invalidated-->39<!--/fill--> run records carry append-only invalidations: 36 superseded thin-mode runs (above) and 3 pilot
  runs rejected by harness false positives. The protected-file manifest then included report files the builder edited
  during the bench, and the tool-log scan misread an escaped `\n` in edited code as the path `t:/n`. Both were fixed:
  the manifest covers only verdict-affecting files, and the scan reads only path fields.
* In the final benchmark, <!--fill:baseline_tamper_suspect_runs-->1<!--/fill--> baseline run was flagged TAMPER_SUSPECT for
  `cd scenarios/visible && … && cd ../..`. The path stays inside the workspace, and the command was denied by the tool
  allow-list anyway. Re-verifying that patch without the scan would ACCEPT it, so this false positive cost the
  baseline one acceptance (13/18 recorded, 14/18 discounting it). Recorded results were not edited. The scan now
  resolves `..` against a tracked working directory (regression test in `tests/test_harness.py`); rescanning every
  stored stream flags only one genuinely outside path (an Edit to a mistyped home directory, in a superseded run).

**How much to trust it.** The verdicts are deterministic and reproducible (`python -m factory verify --case <id>
--patch results/featured/<run>/attempt<n>.patch`). Ground truth: 33 real Minecraft 26.3 recordings (all families:
walk, sprint, jump, diagonal, strafe, sneak, look), deterministic and order-independent, and the pristine simulator
matches all of them. Hidden *variants* (other timings) are answered by the reference layer, which is only as good as
that calibration: one flat fixture and these movement families, nothing else. n is small (18 runs per condition, one
model), so treat the numbers as a demonstration, not an effect size.

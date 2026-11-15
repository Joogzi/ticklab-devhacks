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


**Walls and collisions (`wall_v1`).** The first version only had a flat floor, but the proposal's own example bug
is "sprint-jumping after landing against a wall". `wall_v1` adds a 3-block-tall stone wall whose near face is the plane
z = 4, along with 11 wall scenarios (walk/sprint/jump into it, slide along it diagonally, back off, jump while pressed
against it, and a matched pair: sprinting along the wall at 6° vs 30°). The collision rule was read from the 26.3
bytecode: a wall hit cancels sprint unless it is *minor*, meaning the actual movement stays within ~8° (0.1396 rad) of
the player's input direction (`LocalPlayer.isHorizontalCollisionMinor`). TickProbe builds the wall through a
`fixture_commands` config, and the wall batches were captured twice (listed + shuffled, 2 in-batch repeats):
**11/11 real wall recordings matched the simulator exactly on the first comparison** and were byte-identical across
batches. In the real game, sprint survives the 6° glance (ticks 20–49) and drops on the 30° hit (tick 20 only). Two
seeded bugs use walls. `b10` cancels sprint on *any* wall contact (it looks simpler and "more correct"; its naive fix,
never letting a wall stop sprint, is rejected). `b11`'s bug report is the proposal's sentence verbatim: blocked velocity
is only zeroed on the ground, so mid-air wall hits keep pushing.

**Discovery (finding bugs nobody reported).** `python -m factory discover` generates 200 random valid scenarios per
seeded bug (both fixtures; sprint-running is seeded explicitly because uniform key picks rarely produce it) and runs
them against the reference layer. Every divergence ≥ 100× tolerance is shrunk to a 1-minimal repro: truncate after the
first diverging tick, drop single actions while it still diverges, then shift everything earlier. Results are grouped
by symptom (which axis diverged, airborne or grounded, sprinting or not, open floor or near the wall). Result: **11/11
seeded bugs found with no report and no agent**, with repros typically shrinking from ~10 actions over ~80 ticks to
2–3 actions. Two findings worth noting. On the compound case `c9`, the dominant symptom is the half the one-line report
never mentions (walking jumps drift); the sprint-boost half is masked because the air-acceleration bug always diverges
first, so in practice you fix one and re-run. Discovery uses the reference layer by necessity (random scenarios have
no recordings), so it is only as trustworthy as the calibration above.

**Live confirm (agent-written scenarios in the real game).** `capture/live_confirm.py` takes the repro scenarios the agent
saved during accepted featured runs and has TickProbe replay them in real Minecraft 26.3. Presentation mode adds a
third-person camera and on-screen captions, and doesn't change the movement. Each recording is then compared against the
original buggy code, the agent's accepted patch, and the reference simulator. Result (latest featured runs): 3/3 recordings
(b10 and b11 against the wall, c9 on open floor) match the accepted patch and the reference exactly, and all 3 diverge
from the buggy code. An earlier session with the previous featured runs gave 4/4. This check is
independent of the verifier: the inputs were authored by the agent, and the answers come from the real game, not the oracle.
Recording mode also re-recorded all 44 corpus scenarios (two presentation batches): **44/44 byte-identical** to the
committed corpus. That is a third independent capture run with identical output, and it shows the camera and captions don't touch movement.

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

**Benchmark.** `python -m factory bench`: <!--fill:n_cases-->11<!--/fill--> cases × {baseline, lab} × 2 trials × 2 models (<!--fill:models-->haiku and sonnet<!--/fill-->),
MAX_ATTEMPTS=2, 600 s per attempt, judged against <!--fill:oracle_coverage-->44<!--/fill--> real Minecraft 26.3 recordings plus hidden
reference variants. Every run record is in `results/bench.jsonl` (append-only); aggregates are per model, never mixed.

<!--fill:results_table-->

| metric | haiku: baseline | haiku: lab | sonnet: baseline | sonnet: lab |
|---|---|---|---|---|
| accepted by the verifier | 20 / 22 | 20 / 22 | 17 / 22 | 22 / 22 |
| wrong "FIXED" claims | 7 / 26 | 0 / 19 | 12 / 29 | 1 / 23 |
| median time to accept (s) | 57.2 | 41.0 | 15.5 | 18.5 |
| regressions shipped | 0 | 0 | 0 | 0 |
| mean cost per run (USD) | 0.0211 | 0.0134 | 0.0941 | 0.105 |

<!--/fill-->

* **Acceptance** = the verifier accepted the final patch (agent claims are ignored).
* **Wrong "FIXED" claims** = attempts that ended `STATUS: FIXED` but were rejected (shown as rejected / FIXED claims).
* **Regressions** = scenarios that matched before the patch but diverge after it, summed over final patches.

**Interpretation.** The clearest effect, consistent across both models, is on false "done": without the lab the agent
was wrong about its own fix <!--fill:haiku_baseline_false_done_attempts-->7<!--/fill-->/<!--fill:haiku_baseline_fixed_claims-->26<!--/fill--> (haiku) and
<!--fill:sonnet_baseline_false_done_attempts-->12<!--/fill-->/<!--fill:sonnet_baseline_fixed_claims-->29<!--/fill--> (sonnet) times; with the lab,
<!--fill:haiku_lab_false_done_attempts-->0<!--/fill-->/<!--fill:haiku_lab_fixed_claims-->19<!--/fill--> and <!--fill:sonnet_lab_false_done_attempts-->1<!--/fill-->/<!--fill:sonnet_lab_fixed_claims-->23<!--/fill-->.
With sonnet, the lab also raised acceptance from <!--fill:sonnet_baseline_accepted-->17<!--/fill--> to <!--fill:sonnet_lab_accepted-->22<!--/fill--> of 22. The
baseline misses were b2 (one-tick sprint timing, 0/2: both naive fixes broke visible sprint scenarios), b6 (air
acceleration, 1/2, rejected at the holdouts as designed) and c9 (compound, 0/2: one half fixed, the other caught by
holdouts). With haiku, acceptance was a tie, but lab runs were faster and cheaper to an accepted fix. Seven bugs
(b1, b3, b4, b7, b8, b10, b11) were fixed in every run of both conditions for both models: reading the code plus the
report suffices for them (a ceiling effect, reported as-is). In every condition the verifier caught every wrong claim.

**History (superseded benchmarks, kept for transparency).** (1) Thin mode, before any 26.3 recording
(`results/summary_thin_mode.json`). (2) Flat floor only, after the 33-recording corpus corrected the model's sprint
timing (`results/summary_flat_only.json`; haiku: 13/18 vs 14/18). Both were superseded by append-only invalidation
records when the oracle or the hidden suites changed, and the benchmark was repeated. The numbers above are the ones
we stand behind.

**Integrity events (reported, not hidden).**
* <!--fill:n_invalidated-->75<!--/fill--> run records carry append-only invalidations: superseded benchmarks (above) and 3 pilot runs
  rejected by harness false positives. The manifest then included report files edited during the bench, and an
  escaped `\n` was read as the path `t:/n`. Both were fixed.
* Tool-log scan false positives that cost a baseline acceptance: one in the flat-only benchmark (`cd scenarios/visible
  && … && cd ../..`, fixed by resolving `..` per command) and one in the final benchmark (sonnet b2 baseline:
  `cd ../../..` after an earlier `cd sim/src/mcsim`, fixed by tracking the shell's working directory across calls).
  Recorded results were never edited. Re-verifying that patch without the scan ACCEPTS it, so sonnet baseline is 17/22
  recorded and 18/22 discounting the flag. Regression tests for both cases are in `tests/test_harness.py`, and
  rescanning every stored stream now flags a single, genuinely outside path (an Edit to a mistyped home directory, in a
  superseded run).

**How much to trust it.** The verdicts are deterministic and reproducible (`python -m factory verify --case <id>
--patch results/featured/<run>/attempt<n>.patch`). Ground truth: 33 real Minecraft 26.3 recordings (all families:
walk, sprint, jump, diagonal, strafe, sneak, look), deterministic and order-independent, and the pristine simulator
matches all of them. Hidden *variants* (other timings) are answered by the reference layer, which is only as good as
that calibration: one flat fixture and these movement families, nothing else. n is small (18 runs per condition, one
model), so treat the numbers as a demonstration, not an effect size.

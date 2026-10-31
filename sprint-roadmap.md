# AnyGame-Bench: Sprint Roadmap

Companion to `architecture.md` and `implementation-guide.md`. Sprints are sized as roughly one week of part-time work each; stretch or compress as needed. Each sprint ends with a demo-able result and explicit exit criteria. Order is chosen so the riskiest unknowns (input, capture, judging) are hit early on a fake game before any real one.

## Overview

| Sprint | Theme | Headline outcome |
|--------|-------|------------------|
| 0 | Foundations | Repo, models, fake game, capture + input working |
| 1 | Core loop | A model completes a trivial task in the fake game |
| 2 | Recording and caps | Every run is fully logged, capped, and killable |
| 2b | L1 grid assist | Labeled coordinate grid on the agent's view; L0-vs-L1 retest |
| 3 | Research and planning | Brief and plan phases, with ablation switch |
| 4 | Judge and task specs | Automated success verdicts, calibrated against humans |
| 5 | First real game | OSRS "kill a goblin" runs across multiple models |
| A1 | Long-run foundations | Checkpoint/resume, compaction, wall-clock and budget caps |
| A2 | Case file and attach | Case-file generator, window picker, black-capture warning |
| A3 | Model ladder | Attempt-mode case files across frontier, older, and local models |
| 6 | Breadth and difficulty | Emulated game, generic "level up" tasks, paused mode |
| H1 | Calibration micro-benchmark | Hit rate vs target size and speed per model |
| H2 | Decision-frequency ablation | Success vs decision frequency and cost |
| H3 | Reflex and intents | Hybrid beats the slow loop on the calibration scene |
| H4 | Hybrid on a real offline game | First C0-C4 comparison on a real task |
| H5 | Analysis | Understanding vs precision vs latency decomposition |
| 7 | Analysis and release | Reports, post-mortems, MCP mode, write-up |

---

## Sprint 0: Foundations

**Goal:** Prove the plumbing works before any AI is involved.

Tasks:
- Create repo, `pyproject.toml`, lint/test setup, `.gitignore` for `runs/` and secrets.
- Implement `models.py` (TaskSpec, Action, Limits) and YAML loading.
- Build `testbed/fakegame.py`: a pygame window with a red square to click, then a door, then a simple enemy.
- Implement `capture.py` (window grab, downscale, scale factor) and `inputs.py` (click, key, window clamping).
- Set DPI awareness; write a calibration test that clicks known targets at several window sizes.
- Implement `killswitch.py` and verify it halts input.

**Exit criteria:**
- A scripted (non-AI) action list clicks the red square in the fake game with exact accuracy.
- Out-of-window actions are refused.
- Kill switch stops a running script within 1 second.

**Risks:** DPI scaling, windowed capture quirks. Budget extra time here; every later sprint depends on it.

---

## Sprint 1: Core loop

**Goal:** A model plays the fake game end to end.

Tasks:
- Implement `agent/openai_compat.py` and `models.yaml` profiles (base URL, price, vision flag).
- Implement `parsing.py` (tolerant JSON actions, one re-ask on error) and `prompts.py`.
- Implement `loop.py`: capture, prompt, decide, act, repeat, with `done` handling.
- Add settle delay after actions and simple stuck detection (frame diff).
- Add a mock/scripted agent for cost-free orchestration tests.
- Run 3 models (one frontier reference, two free vision models) on "click the red square" and "reach the door."

**Exit criteria:**
- At least one model completes both fake-game tasks.
- Invalid-output rate and latency are logged per model.
- Failed runs terminate cleanly (cap or kill), never hang.

**Deliverable:** First tiny results table, even if it only proves the loop.

### Sprint 1 results (2026-10-31, local Ollama models, n=1 each)

| Task | Model | Outcome | Success | Steps | Invalid | Avg ms/call |
|------|-------|---------|---------|-------|---------|-------------|
| square | qwen2.5vl:3b | claimed_done | **yes** (3 of 4 runs) | 2-3 | 0-20% | 1.4k-43k |
| square | qwen3-vl:2b | cap_steps | no | 20 | 40% | 30.8k |
| square | qwen3.5:4b | cap_steps | no | 20 | 0% | 7.8k |
| square | qwen3.5:9b | cap_time | no | 5 | 62% | 124.9k |
| door | all four models | cap | **no** (9 attempts) | 20-40 | 2-66% | 7.8k-42k |

Findings:
- **Harness validated end-to-end**: calibrated clicks land within ±5 px of the true target across window moves; out-of-window and cursor-verification refusals all correct. Twelve integration quirks found and fixed through live model contact (prompt notation contract, function-call/string/float/pair coordinate tolerance, frame calibration assist, multi-object reply merging, native-Ollama client for `think:false`, state-read-before-terminate, and more).
- **Model capability boundary (the benchmark working as intended):** qwen2.5vl:3b localizes precisely (±5 px) but cannot re-ground to a new target after a state change (door task, 9 attempts); qwen3.5:4b reads the HUD and plans correctly but its aim carries a systematic ~25 px bias below the target; qwen3-vl:2b guesses its coordinate frame; thinking modes are not disabled by `think:false` for qwen3-vl (works for qwen3.5 via the native API). Consistent with published grounding research: coordinate grounding is the weakest skill of current VLMs.
- **OPEN ITEM (exit criterion 1, "both tasks"):** no local model completed the door task. Next levers, in order: (a) L1 grid overlay (already designed, attacks aim bias directly), (b) a hosted frontier reference model as the ceiling data point, (c) a GUI-grounding-specialized model (UI-TARS class) if one lands in Ollama's library.

---

## Sprint 2: Recording and caps

**Goal:** Runs are reproducible artifacts, not terminal output.

Tasks:
- `recorder.py`: `steps.jsonl` (flushed per step), JPEG frames, independent `ffmpeg` MP4 capture.
- Run folder structure: `runs/<date>_<task>_<model>_<n>/`.
- `orchestrator.py`: owns lifecycle, enforces `max_steps`, `max_wall_minutes`, `max_cost_usd`.
- Token and cost accounting per step; summary in `result.json`.
- Simple local replay viewer (scrub frames with the action overlay) as a script or tiny HTML page.
- Secrets hygiene: redact API keys from saved prompts and logs.

**Exit criteria:**
- Any run can be replayed visually from its folder alone.
- Each cap, when hit, produces the correct `outcome` and a valid `result.json`.
- A crash mid-run still leaves usable partial logs.

---

## Sprint 2b: L1 grid assist

**Goal:** Attack the aim bias documented in Sprint 1 with the architecture's designed fix (5.6).

Tasks:
- `perception.py`: labeled grid overlay applied to the agent's view only (recorder keeps clean frames for the judge).
- `--assist L0|L1|L2` CLI override defaulting from the task spec; assist level recorded per run.
- Retest: door task, qwen2.5vl:3b, L0 vs L1 (n=1 each).

**Exit criteria:** Both runs recorded; the L1 run's clicks measurably closer to the target than the L0 run's (or the finding documented either way).

### Sprint 2b results (2026-10-31, qwen2.5vl:3b, door task, n=1 each)

- L0: 20 steps, 73% invalid, 14 clicks all in one degenerate cluster (~172 px from the square).
- L1: 21 steps, 48% invalid, 23 clicks with real spread and the only click that ever came near the door (83 px). No completion at n=1.
- Verdict: L1 measurably breaks the degenerate aim fixation and improves output validity, but does not close the re-grounding capability gap for this model class. Both runs are fully recorded (steps.jsonl + frames + run.mp4 + replay.html).

---

## Sprint 3: Research and planning

**Goal:** Add the novel phases from the original idea.

Tasks:
- `research.py`: time-boxed research producing `brief.md`. Support three modes: `web` (tool-calling or harness-driven search/fetch), `none`, and `provided`.
- `planner.py`: goal + brief into ordered subgoals with observable checks; `plan.md`.
- Inject current subgoal and plan into every loop prompt; add replan trigger (stuck or agent request) and count replans.
- Track time and tokens separately for research, plan, and execute.
- Write a human-authored brief for one fake-game task to serve as the `provided` baseline.

**Exit criteria:**
- Same task runs under all three research modes with the mode recorded in the result.
- Briefs are saved and readable; replans appear in the step log.
- On the fake game, measurable difference (or lack of one) between modes on at least one model.

**Risk:** Research quality varies a lot for weak models without tool calling. The harness-driven search loop is the fallback.

### Sprint 3 results (2026-10-31, qwen2.5vl:3b, square task, n=1 per mode)

| Mode | Outcome | Success | Steps | Invalid | Notes |
|------|---------|---------|-------|---------|-------|
| none | claimed_done | yes | 4 | 43% | brief from model knowledge |
| provided | claimed_done | yes | 7 | 42% | human brief, zero research calls |
| web | cap_steps | yes (adapter-verified) | 20 | 41% | model ran real DuckDuckGo searches for a game that does not exist on the web; burned steps, still hit the square |

- All three modes ran on the same task with the mode recorded in the result; brief.md/plan.md saved per run; replans counted (and a replan-closure bug found by a live run, fixed, regression-tested).
- Measurable difference: web mode wasted steps researching a nonexistent game (the risk the roadmap predicted), none and provided both completed efficiently. n=1, not a ranking.

---

## Sprint 4: Judge and task specs

## Sprint 4: Judge and task specs

**Goal:** Automated, trustworthy success verification.

Tasks:
- Finalize task spec format: `success.evidence`, `evidence_step`, baseline snapshot, milestones.
- Implement the evidence turn: after a `done` claim, the agent gets a few capped steps to show proof.
- `judge.py`: VLM judge with keyframe selection, cited frames, strict-by-default prompt; judges never see agent thoughts.
- Double-run judging (shuffled frame order) with escalation on disagreement.
- Adapter hook interface for deterministic verifiers (OCR region check, region diff).
- Human labeling: hand-label 20-30 runs (fake game plus a few real recordings); compute judge agreement, false-positive and false-negative rates.
- Add tasks to the fake game specifically designed to fool the judge (near-miss states).

**Exit criteria:**
- Judge agreement with human labels is measured and written down. Target is roughly 90 percent or better on the fake game; whatever the number is, it is published with results.
- `premature_done` cases are correctly caught.
- Results record which verifiers were used.

**Risk:** Generic judging of subtle outcomes (like a rank change) is the weakest point; expect to iterate on prompts and keyframe sampling.

---

## Sprint 5: First real game (OSRS goblin)

**Goal:** First real benchmark numbers.

Tasks:
- Create a throwaway account; script or document the start state (position, layout, resolution).
- Write `tasks/osrs/kill-goblin.yaml` with evidence (chat line, XP increase, goblin death) and evidence step (open Skills tab).
- Build optional `adapters/osrs.py`: chat-box OCR for "defeated", XP diff.
- Run the model matrix: 1 frontier reference + 3-5 free/open vision models, at least 5 runs each, `assist_level` L0.
- Run the same matrix with L1 (grid overlay) to measure how much grounding help changes outcomes.
- Run `research=web` vs `none` on the best two models.
- Generate first post-mortems; tag failure categories.

**Exit criteria:**
- Table of success rate, median steps, median time, and cost per model, with `n` shown.
- Failure taxonomy histogram from at least 30 runs.
- No account-safety incidents; kill switch tested before each session.

**Risks:** Latency makes combat-adjacent tasks flaky; account bans (accepted, throwaway only). If OSRS proves too fragile for realtime, run an emulator task first (Sprint 6 item) and return.

---

## Sprint A1: Long-run foundations

**Goal:** Runs can last hours and survive crashes. *(Merged from `addendum-attempt-mode.md`.)*

Tasks:
- `checkpoint.py`: persist plan, scratchpad, compacted history, and counters to `checkpoint.json` every N steps; `agb resume <run_dir>` continues after a crash or rate-limit stall, logging the gap so it is not counted as thinking time.
- Context compaction: running "story so far" summary every K steps; log what was dropped.
- Wall-clock and budget caps as primary limits (`max_wall_hours`); step caps secondary.
- Rate-limit backoff and retry; log waits separately from inference time.

**Exit criteria:** A 2-hour fake-game run survives a forced crash and resumes to completion.

---

## Sprint A2: Case file and `attach`

**Goal:** Attempt-mode outputs and painless run targeting.

Tasks:
- `casefile.py`: auto-generated case file (header with n=1 disclaimer, outcome, timeline with linked frames, discoveries, struggles, cost, "what a human would have done", reproduce config).
- `agb attach`: list visible windows (title, size, process), pick one; record its size/DPI as the run target.
- Warnings: black capture (exclusive fullscreen) and known anti-cheat titles.
- Verify the kill switch is armed before the run starts.

**Exit criteria:** Any open window can be attached; a finished run produces a readable case file.

---

## Sprint A3: Model ladder

**Goal:** Same task, many agents, attempt mode.

Tasks:
- Run one task in attempt mode across: one frontier model, one older API model (record ID, provider, access date), and 2-3 local open models pinned by name/quantization/hash.
- Add constrained-decoding and captioner variants where the runtime supports them.
- Record hardware (CPU, GPU, RAM, runtime, tokens/second) in every result.

**Exit criteria:** A set of case files plus a short comparison note, clearly labeled n=1 and never ranked.

---

## Sprint 6: Breadth and difficulty

**Goal:** Prove it is genuinely any-game, and add generic tasks.

Tasks:
- Add `time_mode=paused`: emulator pause/frame-advance first, then process suspend for offline native games. Never for online games.
- Add an emulated game task (e.g., a Pokemon-style first battle) as a turn-based comparison point against existing public runs.
- Add generic tasks: "gain a level or rank" in at least two games, including one where level-ups are subtle (e.g., an offline or campaign shooter with a rank screen). Use baseline snapshot plus evidence step.
- Add a tier 3 task in a 3D game (offline). Expect low success; the goal is to see where the generic approach breaks.
- Add `stuck budget` fail-fast and tune the stuck-hint text.
- Update the adapter system based on what real games needed; keep the core free of game-specific code.

**Exit criteria:**
- At least 3 distinct games and 2 generic tasks run through the same core without core changes.
- Paused vs realtime comparison on one task, showing the effect of latency.
- Updated difficulty tiers based on actual results.

---

## Sprint H1: Calibration micro-benchmark

**Goal:** Separate "can't see precisely" from "can't think fast enough." *(Merged from `experiment-hybrid-agent.md`.)*

Tasks:
- `testbed/aimscene.py`: moving-target scene in the fake game with ground-truth positions logged; circular targets of controllable size (10-80 px) and speed.
- Run the model matrix paused and realtime; output hit rate and pixel error as a function of size and speed.

**Exit criteria:** A plot showing where each model's pointing precision falls off.

---

## Sprint H2: Decision-frequency ablation

**Goal:** Measure what decision rate buys.

Tasks:
- Add `decision_hz` control (throttle or batch actions); measure effective Hz per model.
- Run C0 (slow loop, realtime), C1 (slow loop, paused), and C2 (fast small-model loop) on the calibration scene and one tier-1 task.

**Exit criteria:** Results table: success vs decision frequency and cost.

---

## Sprint H3: Reflex module and intent protocol

**Goal:** First hybrid.

Tasks:
- `intents.py`: intent schema with mandatory timeouts; planner-to-reflex handoff.
- `reflex/classical.py` (CV tracking) first, then `reflex/vlm.py`.
- Run C3 (hybrid) on the calibration scene's moving-target task.

**Exit criteria:** The hybrid completes the moving-target task at a higher rate than C0.

---

## Sprint H4: Hybrid on a real offline game

**Goal:** C0-C4 on a real task.

Tasks:
- Run C0-C3 on an offline tier-3/4 task (aim trainer first, then an offline shooter against bots).
- Add the C4 specialist/oracle ceiling where feasible; label and report it separately.

**Exit criteria:** First C0-C4 comparison on a real game task with n >= 5 runs per cell.

---

## Sprint H5: Analysis

**Goal:** Decompose failures into understanding vs precision vs latency.

Tasks:
- Use the `precision` and `timing` failure tags to split causes.
- Write up what the hybrid fixed, what it did not, and what it cost.

**Exit criteria:** Short report with conclusions about H1-H4.

---

## Sprint 7: Analysis and release

**Goal:** Turn the pile of runs into a shareable result.

Tasks:
- `report.py`: aggregate to SQLite; per (task, model, config) tables: success rate, median and IQR for steps/time/cost, failure histogram, judge agreement. Include the C0-C4 hybrid comparison tables (Sprints H1-H4) and attempt-mode case files (A2-A3).
- Post-mortem aggregation: most common wrong research facts, most common perception failures.
- Implement Mode B (MCP server) and run opencode through it on 2-3 tasks; compare against Mode A for the same model and note differences.
- Static results page (single HTML file) with run videos linked.
- Write-up: methodology, judge accuracy, limitations, ethics note (throwaway/offline only), and reproduction steps.
- Decide what to open-source: framing as a research harness with logged results; avoid shipping game-specific bot scripts or anti-cheat workarounds.

**Exit criteria:**
- Someone else can clone the repo, run the fake-game task with a free model, and reproduce the pipeline.
- Published tables never rank on fewer than 5 runs per cell.
- Limitations section covers judge noise, start-state variance, and free-model rate limits.

---

## Task backlog (by tier)

### Open item: testbed door task (from Sprint 1/2b findings)

No local model has completed the door task (re-grounding after a state change + aim precision). Levers, mapped to where they fit:

| Lever | Fits in |
|-------|---------|
| Hosted frontier reference model on the testbed tasks (ceiling data point; needs an API key) | Sprint 5 model matrix + a quick testbed re-run |
| GUI-grounding-specialized local models (UI-TARS class) when they land in Ollama's library | Sprint 6 / Sprint A3 model ladder |
| L2 OCR assist ablation (text blocks with coordinates) | Sprint 6 breadth/ablations |


| Tier | Task | Notes |
|------|------|-------|
| 0 | Fake game: click square, reach door | Harness testing |
| 0 | Fake game: calibration aim scene (moving targets) | Hybrid experiment, Sprint H1 |
| 1 | OSRS: kill a goblin | Slow ticks, click-to-move |
| 1 | Emulated RPG: win first battle | Turn-based, pausable |
| 2 | OSRS: gain a level (any skill) | Tests subtle-progress judging |
| 2 | Offline 2D game: reach a named location | Navigation |
| 3 | WoW (throwaway) or offline MMO-like: kill a boar | 3D movement and targeting |
| 3 | Offline shooter/campaign: gain a rank | Subtle evidence in menus |
| 4 | Stealth/action game: eliminate a named target | Navigation, stealth, combat |
| 4 | Real-time FPS campaign: eliminate one enemy | Aiming and latency; expect near-zero success |

## Cross-cutting risks

- **Free-model limits:** rate limits and context caps will cap run lengths. Log retries; don't count rate-limit waits as thinking time.
- **Judge validity:** the whole benchmark rests on it. Never skip human calibration.
- **Variance:** stochastic agents; require repeated runs before drawing conclusions.
- **Safety:** throwaway/offline only; kill switch checked every session; avoid titles with hardware-ban anti-cheat.
- **Scope creep:** resist adding per-game cleverness to the core. If a game needs it, it goes in an adapter and is reported as such.

## Definition of done (v1)

- Core runs unchanged across at least 3 games.
- At least 5 models benchmarked with 5+ runs per cell on tier 1 tasks.
- Judge accuracy measured against human labels and published.
- Research on/off and assist-level ablations reported.
- Full replayable artifacts for every reported run.

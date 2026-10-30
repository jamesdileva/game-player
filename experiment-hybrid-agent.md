# Experiment: Hybrid Agents and the Understanding-vs-Precision Gap

**Status:** Proposed extension. Not yet merged into `architecture.md` or `sprint-roadmap.md`. Section 8 lists the exact merge points so an agent (or you) can fold this in.

## 1. Question

Today's screenshot-driven agents work like stop-motion animation: capture one frame, think, act, repeat, at roughly one decision every few seconds. This experiment asks:

1. **How much of the failure in real-time games is speed, and how much is precision?** (Freezing the game fixes timing but not aiming accuracy.)
2. **Can a hybrid, with a slow smart planner steering a fast lightweight reflex loop, close the gap?**
3. **How does performance change as decision frequency goes from ~0.2 Hz up toward 30 Hz?**

## 2. Hypotheses

- **H1:** Paused mode raises success a lot on tasks needing decisions, but only a little on tasks needing precise pointing (small or moving targets).
- **H2:** Raising decision frequency with the same large model is infeasible (latency, cost). Raising it with a small model improves reaction but hurts understanding.
- **H3:** A hybrid (planner plus reflex module) beats both the slow large-model loop and the fast small-model loop on precision-heavy tasks.
- **H4:** A task-specific specialist (e.g., a trained detector or an oracle using game state) sets an upper bound for precision but cannot generalize to a new game.

These are guesses to be tested, not findings.

## 3. What the current docs already cover vs. what's new

| Topic | Already in the suite | New in this experiment |
|-------|----------------------|------------------------|
| Paused vs realtime | Yes (`time_mode`) | Used as the "understanding" measurement |
| Grid overlay / OCR assist | Yes (L0-L2) | Reused as a precision aid ablation |
| Failure taxonomy | `grounding`, `timing` tags | Add `precision` as a separate tag |
| Tier 3-4 tasks (shooters, stealth) | Yes, as backlog | Become the main testbed here |
| Single-agent loop | Yes (Mode A and B) | **Add hybrid topology: planner plus reflex module** |
| Decision frequency | Implicit | **Add as an explicit ablation axis (`decision_hz`)** |
| Pixel-level aim measurement | No | **Add a calibration micro-benchmark** |
| Specialist/oracle baseline | No | **Add as a labeled upper bound** |

## 4. Experimental conditions

All conditions run the same task spec, start state, caps, and judge as the base benchmark.

| ID | Condition | Description |
|----|-----------|-------------|
| C0 | Slow loop, realtime | Existing Mode A, game keeps running |
| C1 | Slow loop, paused | Existing paused mode; game frozen during inference |
| C2 | Fast small-model loop | Small VLM at 2-10 Hz, realtime, no planner |
| C3 | Hybrid | Large model plans every 1-3 s; reflex module acts at 15-30+ Hz |
| C4 | Specialist/oracle (ceiling) | Trained detector or game-state reader. Offline games only. Reported separately |

Read the results as: C1 minus C0 is the cost of latency; C1 against a human-labeled "can aim" calibration score is the cost of imprecision; C3 against C0/C2 is the hybrid benefit; C4 is the ceiling.

## 5. The hybrid design

### 5.1 Planner (slow, large model)
Same agent as the base harness, but instead of emitting raw clicks it emits **intents** for the reflex module.

### 5.2 Intent protocol

```json
{"intent": "track_and_shoot", "target": "enemy soldier", "until": "target_dead_or_5s"}
{"intent": "move_to", "region": {"x": 800, "y": 300, "w": 200, "h": 200}, "until": "arrived_or_4s"}
{"intent": "hold_position", "until": "planner_update"}
{"intent": "click_target", "target": "goblin", "until": "target_dead_or_8s"}
```

Every intent has a timeout so the reflex module can never run unattended forever. The planner receives a short summary of what the reflex module did and what changed, plus fresh frames, every cycle.

### 5.3 Reflex module (fast, cheap)
Interchangeable implementations, compared as an ablation:

1. **Classical CV:** color or template tracking for a target class. Cheapest, brittle.
2. **Small detector:** a lightweight object detector trained or fine-tuned on a few hundred labeled frames of the target class.
3. **Small VLM:** a fast vision model queried at high frequency to localize the planner's named target.

The planner names the target in words; the reflex module grounds it (the first frame may be handed over via a single bounding box from the planner's own estimate).

### 5.4 Fairness rules
- Intents may only invoke actions available in the standard action space (move, click, key). No reading game memory in C1-C3.
- The reflex module's compute is reported (model size, FPS, cost) so results aren't misleading.
- C4 may use game state but is labeled clearly and is never ranked against C0-C3.

## 6. Measurements

Add these to `result.json` (see architecture section 7.4):

- `decision_hz`: median model decisions per second
- `topology`: `single` or `hybrid`
- `reaction_ms`: time from a target appearing to first relevant action (needs frame timestamps)
- `aim_error_px`: median distance between click/crosshair and target center, from the calibration test
- `reflex_cost`, `reflex_hz`
- `understanding_score`: success rate in paused mode on the task
- `precision_score`: hit rate in the calibration micro-benchmark

### Calibration micro-benchmark (build this first)
A tiny scene in the existing fake game (`testbed/fakegame.py`) with circular targets of controllable size and speed. Run each agent through:
- static targets, sizes 10-80 px
- slow-moving targets
- fast-moving targets

Run both paused and realtime. Output: hit rate and pixel error as a function of size and speed. It is cheap, deterministic, and cleanly separates "can't see precisely" from "can't think fast enough."

## 7. Proposed sprints (insert after Sprint 6)

**Sprint H1: Calibration micro-benchmark**
- Moving-target scene in the fake game, with ground-truth positions logged.
- Run the model matrix paused and realtime; plot hit rate vs size and speed.
- Exit: a plot showing where each model's pointing precision falls off.

**Sprint H2: Decision-frequency ablation**
- Add `decision_hz` control (throttle or batch actions) and measure effective Hz per model.
- Run C0, C1, C2 on the calibration scene and one tier-1 game task.
- Exit: results table showing success vs decision frequency and cost.

**Sprint H3: Reflex module and intent protocol**
- Implement the intent schema, timeouts, and the planner-to-reflex handoff.
- Build the classical-CV reflex first, then a small-VLM reflex.
- Exit: hybrid completes the calibration scene's moving-target task at a higher rate than C0.

**Sprint H4: Hybrid on a real offline game**
- Run C0-C3 on an offline tier-3/4 task (aim trainer first, then an offline shooter against bots).
- Add the C4 specialist/oracle ceiling where feasible.
- Exit: first C0-C4 comparison on a real game task, with `n >= 5` runs per cell.

**Sprint H5: Analysis**
- Decompose failures into understanding vs precision vs latency using the `precision` and `timing` tags.
- Write up what the hybrid fixed, what it didn't, and the cost.
- Exit: short report with conclusions about H1-H4.

Dependencies: needs Sprints 1-2 (core loop, recording), 4 (judge), and 6 (paused mode) done first.

## 8. Merge notes (for folding into the main docs)

**`architecture.md`**
- Section 5: add **5.13 Reflex Module** and describe the Intent protocol; note `topology: single|hybrid` in the agent interface section.
- Section 7.1 (task spec): add `loop.decision_hz` and `loop.topology`.
- Section 7.4 (result record): add the metrics from section 6 above.
- Section 9.4 (failure taxonomy): add `precision`.
- Section 9.5 (ablation axes): add `decision_hz`, `topology`, `reflex_impl`.
- Section 11 (safety): add the note in section 9 below.

**`implementation-guide.md`**
- Add `agent/hybrid.py`, `reflex/` (classical, detector, vlm), `intents.py`, and `testbed/aimscene.py`.
- Add a short subsection on frame timestamps for `reaction_ms`.

**`sprint-roadmap.md`**
- Insert Sprints H1-H5 after Sprint 6 and before Sprint 7; adjust Sprint 7 reporting to include the C0-C4 tables.

## 9. Safety and ethics

A reflex module that tracks and shoots targets is functionally an aimbot. To keep this a research experiment:
- Use offline games, aim trainers, single-player campaigns against bots, and the fake game only.
- No online multiplayer, and no titles with kernel-level anti-cheat, even on throwaway accounts.
- Do not publish reflex modules packaged for specific commercial games.
- Frame results as research on agent architectures, not as a way to play competitively.

## 10. Open questions

- What counts as a fair compute budget for the reflex module? Should compute be matched across conditions?
- Should `reaction_ms` be compared against a human baseline? (A few human runs on the same scenes would make the results much more meaningful.)
- How much does a good intent vocabulary matter? A poor one could make the hybrid look worse than it is.
- Does the planner stay coherent when the reflex module runs 30-100x more steps than the planner between updates?

# AnyGame-Bench: Architecture

> Working title. A local harness that attaches to any running game (emulated, offline, or throwaway account), gives an AI agent a one-line task, and measures whether and how efficiently it completes it using only screen pixels and mouse/keyboard.

## 1. Purpose

Existing game evaluations (Pokemon-to-Brock runs, BALROG, VideoGameBench) are tied to a specific game or emulator and usually read game memory for ground truth. AnyGame-Bench asks a more general question:

**Can an agent, given an unfamiliar game and a small goal, research it, plan, and accomplish it through human-style input, and how many steps, how much time, and how much money does it take?**

Primary use: comparing free/open models and agent frameworks (opencode, etc.), with a frontier model as a ceiling reference.

## 2. Non-goals

- Progressing real accounts or farming anything. Everything is throwaway research.
- Multiplayer competitive play (anti-cheat risk, latency makes it meaningless).
- A polished "bot any game" tool. This is a research harness with logged results.
- Perfect game-agnostic verification. We accept a noisy judge and measure its noise.

## 3. Design principles

1. **Game-agnostic core, optional adapters.** The core only knows pixels in, input out. Game-specific knowledge (OCR regions, chat log checks) lives in optional adapters that never change what the agent sees unless an "assist level" says so.
2. **Agent-agnostic.** Anything that can look at an image and emit an action can be benchmarked.
3. **The harness never trusts the agent.** "I'm done" is a claim, not a result. The judge decides.
4. **Everything is recorded.** Every frame, action, thought, token count, and timestamp. Runs are replayable and re-judgeable.
5. **Comparability beats realism.** Fixed resolution, fixed action space, fixed caps, fixed start state.
6. **Fail safe.** A human kill switch always works. The agent can only touch the game window.

## 4. System overview

```
                    +------------------+
                    |   Task Spec      |  YAML: goal, start state, evidence, caps
                    +--------+---------+
                             |
                    +--------v---------+
                    | Run Orchestrator |  owns lifecycle, caps, kill switch
                    +--+------+------+-+
                       |      |      |
        +--------------+      |      +----------------+
        |                     |                       |
+-------v-------+    +--------v--------+     +--------v--------+
|   Research    |    |   Agent Loop    |     |    Recorder     |
| (web, notes)  |    | observe -> act  |     | frames, actions |
+-------+-------+    +---+---------+---+     | tokens, video   |
        |                |         |         +--------+--------+
        |         +------v--+   +--v------+          |
        |         | Capture |   |  Input  |          |
        |         | (window)|   | (kb/ms) |          |
        |         +------+--+   +--+------+          |
        |                |         |                 |
        |            +---v---------v---+             |
        +----------->|   Game Window   |             |
                     +-----------------+             |
                                                     |
                    +------------------+             |
                    |      Judge       |<------------+
                    | VLM + adapters   |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Post-mortem &   |
                    |  Results Store   |
                    +------------------+
```

## 5. Components

### 5.1 Task Spec
A YAML file per task. See section 7.1. Defines goal text, start-state description, success evidence, limits, and research policy.

### 5.2 Run Orchestrator
Runs the lifecycle (section 6), enforces caps (steps, wall time, cost), handles the kill switch, and writes the final result record. It is the only component that decides when a run ends.

### 5.3 Capture
Grabs frames of the target window only (not the full desktop), downscales to a fixed size (default 1280x720 max, aspect preserved), and timestamps them. Also keeps full-resolution frames for the recording and judge.

### 5.4 Input
Translates abstract actions to OS input, restricted to the window's rectangle. Coordinates are mapped from the agent's frame space to window space. Refuses any action outside the window. Uses DirectInput-style scancodes on Windows, since many games ignore plain virtual-key events.

### 5.5 Agent Interface
A single protocol:

```
decide(observation) -> Decision(actions[], thought, notes_update, usage)
```

Two integration modes:

- **Mode A, harness-driven:** the harness calls any OpenAI-compatible chat endpoint (OpenRouter, Ollama, LM Studio, a vendor API). We own the loop, so step and token accounting is exact.
- **Mode B, MCP server:** the harness exposes `screenshot`, `click`, `key`, `wait`, `note`, `done` as MCP tools, and an external agent (opencode, etc.) drives it. We count tool calls and observe tokens through the agent's own logs where possible. Less exact, but lets you benchmark whole agent frameworks, not just models.

### 5.6 Perception Assist Levels
An ablation axis. The agent's observation is built according to the assist level:

| Level | Observation |
|-------|-------------|
| L0 | Raw screenshot only (default, the "pure" benchmark) |
| L1 | Screenshot with a labeled coordinate grid overlay (helps weak models click) |
| L2 | L1 plus OCR text blocks with their coordinates |

Results are always reported per assist level.

### 5.7 Research
Before play, the agent gets a time-boxed research phase with a configurable tool set (web search and fetch, or none). Output is a **game brief** saved to `brief.md`: controls, relevant mechanics, where to go, what to expect. Ablations: `research=web`, `research=none` (model knowledge only), `research=provided` (a fixed human-written brief).

### 5.8 Planner
Turns goal plus brief into an ordered list of subgoals, each with an observable success check. The plan lives in `plan.md` and is re-read by the agent every step. Replanning is allowed and counted.

### 5.9 Memory
Models have limited context, so the agent loop provides:
- the last N frames (default 3) plus the current one
- the current subgoal and plan
- a **scratchpad** the agent can overwrite (`note` action), capped in size
- an action/outcome history, compacted into a summary every K steps

### 5.10 Recorder
Writes `steps.jsonl` (one record per step), frames as JPEG, and an MP4 of the full run captured independently of the agent loop (so the judge sees real game time, not just sampled frames).

### 5.11 Judge
See section 8.

### 5.12 Post-mortem
After judging, a separate model pass reads the brief, plan, step log, and key frames and writes `postmortem.md`: what worked, where the plan's assumptions were wrong, failure category, and what a human would have done differently. Failure categories are tagged for aggregate analysis (section 9.4).

## 6. Run lifecycle

```
0. SETUP      Human or script puts game in the defined start state. Harness verifies
              the window, resolution, and takes a baseline snapshot.
1. RESEARCH   Time-boxed. Produces brief.md. (skipped if research=none/provided)
2. PLAN       Produces plan.md with subgoals and checks.
3. EXECUTE    Observe -> decide -> act loop until: done claim, cap hit, or kill switch.
4. EVIDENCE   If the agent claims done, it gets a short evidence turn to display proof
              (e.g., open the character/rank screen). Capped at a few steps.
5. JUDGE      Verifier(s) decide success/partial/fail from recording + final frames.
6. ANALYZE    Post-mortem generated, result record written.
```

The baseline snapshot in step 0 matters for generic tasks like "gain a level": the judge compares before and after.

## 7. Data contracts

### 7.1 Task spec

```yaml
id: osrs-kill-goblin-001
game: osrs
title: Kill one goblin
goal: "Kill one goblin."
tier: 1                      # 1 easy ... 4 very hard
start_state: >
  Logged in, standing in Lumbridge near the castle. Default combat stats.
  Default client layout and resolution.
baseline:
  capture_regions:           # optional, for before/after comparisons
    - name: skills_tab
      note: "Skills panel, if visible at start"
success:
  evidence: >
    A goblin is attacked by the player and dies, shown by its health bar
    reaching zero and combat XP increasing, or by the chat line
    "You have defeated the goblin."
  evidence_step: >
    After the kill, open the Skills tab so XP totals are visible.
  verifiers: [vlm]           # adapters appended per game, e.g. adapter:osrs_chat
limits:
  max_steps: 300
  max_wall_minutes: 45
  max_cost_usd: 5.00
research:
  mode: web                  # web | none | provided
  max_minutes: 10
loop:
  time_mode: realtime        # realtime | paused
  assist_level: L0
```

Generic task example (the "level up" idea):

```yaml
id: cod-gain-rank-001
game: cod-campaign-or-offline
goal: "Gain a level or rank."
success:
  evidence: >
    A level-up or rank-up notification appears, or the level/rank number
    shown in the profile screen is higher than in the baseline snapshot.
  evidence_step: "Open the profile or rank screen and leave it visible."
```

### 7.2 Action schema

```json
{"type": "click", "x": 640, "y": 360, "button": "left"}
{"type": "double_click", "x": 640, "y": 360}
{"type": "drag", "x1": 100, "y1": 100, "x2": 300, "y2": 200}
{"type": "move", "x": 640, "y": 360}
{"type": "key", "key": "w", "hold_ms": 800}
{"type": "type", "text": "hello"}
{"type": "scroll", "x": 640, "y": 360, "dy": -3}
{"type": "wait", "ms": 1000}
{"type": "note", "text": "scratchpad content"}
{"type": "done", "claim": "I killed a goblin."}
```

Coordinates are in the downscaled frame the agent sees. The harness maps them to the window.

### 7.3 Step record (`steps.jsonl`)

```json
{
  "step": 17, "t_wall": 82.4, "phase": "execute",
  "frame": "frames/000017.jpg",
  "subgoal": 2,
  "thought": "...", "actions": [ ... ],
  "usage": {"in_tokens": 2100, "out_tokens": 180, "cost_usd": 0.0},
  "latency_ms": 3200,
  "error": null
}
```

### 7.4 Result record (`result.json`)

```json
{
  "run_id": "...", "task_id": "...", "model": "...", "agent_mode": "A",
  "assist_level": "L0", "research_mode": "web", "time_mode": "realtime",
  "outcome": "success|partial|fail|timeout|aborted",
  "verifier": {"used": ["vlm"], "confidence": 0.82, "judge_model": "..."},
  "metrics": {
    "steps": 143, "wall_seconds": 612, "model_calls": 150,
    "tokens_in": 310000, "tokens_out": 24000, "cost_usd": 0.0,
    "research_seconds": 140, "plan_seconds": 20, "execute_seconds": 452,
    "replans": 2, "stuck_events": 3, "invalid_actions": 5
  },
  "failure_category": null
}
```

## 8. Judging

Success verification in an arbitrary game is the hardest part, so it is layered:

1. **VLM judge (default).** A model separate from the agent receives the task, the `evidence` text, the baseline snapshot, sampled keyframes, and the evidence-step frames. It must cite specific frames and return `{verdict, confidence, cited_frames, reasoning}`. Using a different, preferably stronger, model than the agent avoids self-grading.
2. **Adapter verifiers (optional).** Cheap deterministic checks per game: OCR on a chat box, XP number diff, screen-region template match. When present, they override or cross-check the VLM.
3. **Human calibration.** Label a sample of runs by hand (aim for 20-30 runs early) and report judge agreement. Publish the judge's measured accuracy next to every leaderboard.

Rules:
- The agent's `done` claim is never evidence.
- Judges never see the agent's thoughts, only pixels (prevents being talked into a yes).
- Each result records which verifiers ran, so "VLM-only" and "adapter-confirmed" results aren't mixed silently.
- Partial credit comes from optional milestone checks in the task spec, scored the same way.

## 9. Fairness and comparability

### 9.1 Fixed conditions
Same window size and capture resolution, same action space, same caps, same start state (saved character, emulator save state, or a setup script), same judge.

### 9.2 Repetition
Agents are stochastic. Report success rate and median/IQR of steps, time, and cost over at least 5 runs per (task, model, config).

### 9.3 Real-time vs paused
Slow models are penalized in live games because the world keeps moving. Two modes, always reported:
- `realtime`: the game runs while the model thinks.
- `paused`: the harness freezes the game during inference. For emulators, use the emulator's pause or frame-advance. For single-player native games, suspend the process (`psutil.Process.suspend()`) during the model call and resume to execute. Never for online games, where it causes disconnects.

### 9.4 Failure taxonomy
Each failed run gets one primary tag from the post-mortem:
- `research_wrong` (brief had false info)
- `plan_infeasible`
- `perception` (misread the screen)
- `grounding` (right target, wrong click)
- `navigation_lost`
- `stuck_loop`
- `ui_modal` (stuck in a menu/dialog)
- `timing` (too slow for the game)
- `premature_done` (claimed success, judge disagreed)
- `budget` (cap hit while progressing)

### 9.5 Ablation axes
Research mode, assist level, time mode, number of context frames, agent mode (A vs B). Change one at a time.

## 10. Model strategy

- **Reference tier:** one frontier model on a subset, as a ceiling.
- **Free/open tier:** free-endpoint and locally hosted vision models. Check which currently support image input before planning runs, since this changes often.
- **Text-only models:** supported via a *captioner* mode where a fixed small VLM describes the frame in text. This confounds the result, so these are reported in a separate bracket.
- **Output reliability:** weaker models often produce malformed actions. The parser tolerates fenced JSON and minor errors, then re-asks once. Invalid actions are counted as a metric, not hidden.

## 11. Safety and ethics

- Throwaway accounts, emulators, or offline modes only. Check the terms for each game; some forbid automation even on throwaway accounts, so account bans are an accepted risk.
- Prefer offline and campaign modes for titles with aggressive anti-cheat (Vanguard, Ricochet, Warden). Hardware bans can outlive an account.
- Run games inside a VM or dedicated user account where practical.
- **Global kill switch** (hotkey) halts input injection immediately.
- Input is clamped to the game window. The agent cannot type into other apps.
- No credential handling by the agent. Logins happen during setup, by a human.
- API keys live in environment variables, never in task specs or logs. Redact when saving prompts.

## 12. Open questions

- How to define a fair "start state" for games with no save states (script it, or accept a human-set start with a baseline photo)?
- How much does a grid overlay (L1) change rankings? Likely a lot, worth testing early.
- Is MCP mode comparable enough to Mode A to share a leaderboard, or does it need its own?
- Should tasks include a "stuck budget" (e.g., N frames with no screen change) to fail fast?

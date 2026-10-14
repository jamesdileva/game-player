# Addendum: Attempt Mode, Long Runs, and the Model Ladder

**Status:** Proposed extension to `architecture.md`, `implementation-guide.md`, and `sprint-roadmap.md`. Section 7 lists merge points. Companion to `experiment-hybrid-agent.md`.

## 1. Idea

The main docs assume statistical benchmarking (many runs, success rates). This addendum adds a second, lighter-weight way to use the harness:

**Attempt mode: one agent, one task, one long run, then a "case file" report.** The result is a narrative of what the agent did over hours, where it got stuck, what it figured out, and how it ended. It is labeled n=1 and is not used to rank models.

**Study mode** (the existing design) stays available for anyone who wants repeats and real statistics.

| | Attempt mode | Study mode |
|---|---|---|
| Runs per (task, agent) | 1 | 5+ |
| Main output | Case file (narrative plus timeline) | Tables (success rate, medians) |
| Caps | Wall-clock and budget | Steps, wall-clock, cost |
| Ranking | Never | Allowed at n >= 5 |
| Use | Curiosity, demos, "how far does this model get?" | Comparison and research claims |

## 2. Long-run requirements

Runs lasting hours need things short runs can skip:

- **Wall-clock and budget caps first.** Default to caps like `max_wall_hours` and `max_cost_usd`; step caps become a secondary guard.
- **Checkpointing and resume.** Persist run state (plan, scratchpad, compacted history, counters) every N steps to `checkpoint.json`. `agb resume <run_dir>` continues after a crash or rate-limit stall, recording the gap so it isn't counted as thinking time.
- **Context compaction.** Every K steps, summarize old history into a running "story so far" and keep only recent frames. Compaction quality is the main long-run failure point, so log what was dropped.
- **Heartbeat and stuck handling.** Detect long periods with no meaningful screen change or repeated actions, inject a standard hint, and force a replan after a threshold. Count these events.
- **Milestones for multi-step goals.** Goals like "gain a level" may require discovering a grind loop. The task spec's optional milestones (e.g., "found an enemy," "first XP gained") give partial credit and show where the agent stalled.
- **Rate-limit tolerance.** Back off and retry on free-tier limits; log waits separately from inference time.

## 3. The case file (attempt-mode report)

Auto-generated after the judge runs, by a separate model reading the logs and keyframes. Sections:

1. **Header:** task, game, agent/model ID, hardware, settings, and the line "Single attempt (n=1); not a ranking."
2. **Outcome:** success/partial/fail, verifier(s) used, judge confidence.
3. **Timeline:** key moments with timestamps and linked frames (first click, first progress, longest stall, plan changes, final claim).
4. **What it figured out:** discoveries the agent made unprompted, and whether research helped.
5. **Where it struggled:** failure tags (existing taxonomy) with example frames.
6. **Cost and efficiency:** time, steps, tokens, dollars, replans, stuck events.
7. **"What a human would have done":** short comparison.
8. **Reproduce:** exact config and run folder path so someone can re-run with another agent.

Keep it to roughly one page plus links; the raw artifacts remain in the run folder.

## 4. Model ladder

A planned way to compare agents on the same single task:

- **Frontier reference:** one current top model, as a ceiling.
- **Earlier-generation models:** to see how capability progressed. API models get deprecated, so record the exact model ID, access date, and provider; mark results as "may not be reproducible."
- **Local open models:** pinned by model name, quantization, and file hash, which keeps them reproducible indefinitely. Record GPU/CPU and tokens per second.
- **Smallest viable models:** include a few tiny local models on purpose. Expect most to fail tier 1; the failure modes are the useful result.

Always compare agents under the same settings (assist level, time mode, research mode), and say so in each case file.

## 5. Supporting small and local models

Each aid below is its own switch, reported separately so it never hides in the baseline:

- **Constrained decoding:** grammar or JSON-schema constrained output (supported by common local runtimes) to reduce invalid actions.
- **Grid overlay (L1)** and **OCR assist (L2)** from the main architecture.
- **Captioner mode** for text-only models (a fixed small VLM describes each frame); reported in a separate bracket.
- **Paused mode by default** for local models on modest hardware, since realtime play is rarely feasible.
- **Smaller observation:** lower resolution and fewer context frames to fit small context windows.
- **Hardware record:** log CPU, GPU, RAM, runtime, and tokens/second in every result, since local results mean little without them.

## 6. Capturing any running game: `attach`

Ease of use is a goal, so add a simple command:

```
agb attach          # lists visible windows (title, size, process), pick one
agb attach --title "RuneLite"
```

- Saves the chosen window as the run target and records its size/DPI.
- Warns if the capture comes back black (typical of exclusive fullscreen) and suggests windowed or borderless mode.
- Warns on windows from known anti-cheat protected titles and recommends offline/emulated alternatives.
- Verifies the kill switch is armed before the run starts.

## 7. Merge notes

**`architecture.md`**
- Add a section on run modes (attempt vs study) and the case-file report to section 5 (components) or 6 (lifecycle).
- Section 7.1 (task spec): add `mode: attempt|study`, `limits.max_wall_hours`, `checkpoint_every_steps`.
- Section 7.4 (result record): add `mode`, `hardware`, `model_pin` (ID, quantization, hash, access date), `resumed_count`.
- Section 9.2 (repetition): note that attempt mode is exempt from the "n >= 5" rule but is never used for rankings.
- Section 10 (model strategy): add the model ladder and constrained decoding.

**`implementation-guide.md`**
- Add `checkpoint.py`, `compaction.py`, `casefile.py`, and an `attach` command in `cli.py`.
- Add notes on resume, grammar-constrained decoding for local runtimes, and hardware logging.

**`sprint-roadmap.md`**: insert after Sprint 5 (first real game), since it needs the recorder and judge:

- **Sprint A1: Long-run foundations.** Checkpoint/resume, compaction, wall-clock/budget caps, rate-limit handling. Exit: a 2-hour fake-game run survives a forced crash and resumes.
- **Sprint A2: Case file and `attach`.** Case-file generator, window picker, black-capture warning. Exit: any open window can be attached and a case file is produced from a finished run.
- **Sprint A3: Model ladder.** Run one task through frontier, an older model, and 2-3 local models in attempt mode, plus constrained-decoding and captioner variants. Exit: a set of case files plus a short comparison note, clearly labeled n=1.

## 8. Open questions

- How should resumed runs be labeled in reports (and should a resume invalidate an attempt)?
- Is one attempt per agent enough to be interesting, or should the case file include a cheap second attempt for sanity?
- How much of the case file should the agent itself write versus an independent model (independent is less flattering to the agent)?
- Should older API models be re-tested periodically while still available?

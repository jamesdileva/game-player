# AnyGame-Bench — Results (v1, exploratory)

**Status:** exploratory (n=1 per cell unless noted). Nothing here is a ranking — architecture 9.2 requires n ≥ 5 per cell before any comparison is a ranking. What this documents is that the pipeline works end-to-end across three games and what was learned building it.

**Reproduction:** see README (headless tests, per-game start-state checklists, `agb run/matrix/label/calibrate/report`). Every run folder contains `result.json`, `steps.jsonl`, frames, `run.mp4`, and a replay page.

## Hardware

AMD Radeon RX 6400 (4 GB VRAM), 16 GB RAM, Ollama 0.40.11, Windows. The 3–4 B models partially offload to CPU (~50/50 split), which sets the performance ceiling documented below.

## Tasks and outcomes

| Game | Task | Best model | Result | Verified by |
|------|------|-----------|--------|-------------|
| OSRS (RuneLite) | Kill one goblin | qwen2.5vl:3b | **success** — XP drop witnessed, goblin killed | Human (user testimony) |
| ToS (Dolphin) | Title → file-select | qwen3-vl:2b | **success** — file-select reached in 7 steps | Judge (qwen2.5vl, cross-model, 0.9, agree) |
| Colosseum (Dolphin) | Win a battle | qwen2.5vl:3b | **partial** — moves selected, damage dealt, one foe fainted; capped by step budget on exp screens | Human (user testimony) + judge (partial, false-negative on damage) |
| fakegame (testbed) | Click square / reach door | qwen2.5vl:3b | **success** (multiple runs) | Deterministic adapter (title state) |

## Model matrix (observed, same hardware)

| Model | VRAM fit | Latency/call | Instruction-following | Notes |
|-------|----------|-------------|----------------------|-------|
| qwen2.5vl:3b | ~50% GPU | 13–60 s | best of the three | no thinking mode; clean short replies; solved OSRS + navigated ToS |
| qwen3-vl:2b | 100% GPU | 15–43 s | grounding-trained; reached file-select | always thinks (~1k tokens); `think:false` and `/no_think` ignored by this Ollama build |
| qwen3.5:4b | ~50% GPU | 8–24 s | verbose; high invalid JSON early, format fixes helped | thinking eats budget unless capped generously |
| qwen3.5:9b | ~50% GPU | 60–125 s | - | too slow for the caps on this hardware |
| moondream | 100% GPU, 4–11 s | - | cannot follow the reflex contract | kept for experiments |

## Judge

- Agreement with ground truth: **83.9% over 31 runs** (calibrated on fake-game deterministic states + human labels). FP = 3.2%, FN = 12.9%.
- False negatives cluster on runs that succeeded without *displaying* proof (the strict prompt is by design).
- One live false-negative on Colosseum (damage dealt and a faint witnessed by the human, judge scored partial): keyframes missed the mid-battle damage frames — fixed with change-aware keyframe selection (`77763e5`).
- Self-judging bias exists (10 runs self-judged) and is flagged per run; cross-model judging is the default going forward.

## Failure taxonomy (observed)

| Category | Observed example |
|----------|-----------------|
| `grounding` | ToS: the 2.5vl model cycled menus but never pressed confirm; Colosseum: aim bias ~25 px below target |
| `research_wrong` | 3B researcher confabulated "bows and aiming wheels" for OSRS over real wiki text; invented "teams of 4-8 Pokémon" for Colosseum |
| `timing` | qwen3.5:9b: 60–125 s/call against task wall-caps |
| `premature_done` | fakegame runs claiming done with 0 hits (correctly caught by the judge/adapter) |
| `perception` | Zigzagoon misread as "Zizagagon/ZIGZAGOOM" at 384×288 |

## Fixes these runs drove (selection)

Frame calibration (per-model coordinate-frame measurement), GCN-dialect key translation, keys-only enforcement, change-aware judge keyframes, forced-final-brief research fallback, reflex mode (one-line bursty responses), stale-handle self-healing capture, evidence turn, cursor-verification safeguard, paused mode (psutil suspend), `num_ctx` right-sizing.

## Limitations

1. **VRAM ceiling** — 4 GB forces ~50/50 CPU/GPU offload: ~1.3 tok/s generation, prompt-eval dominated (~1.4k tokens/call). A ≥8 GB GPU or a hosted API is the structural fix.
2. **Image-token floor** — qwen2.5-vl's min-pixel resize makes 384×288 and 640×480 cost the same (~1.4k in-tokens); view-size is not a token lever.
3. **Thinking models** — `think:false` is ignored for qwen3-vl (template hard-codes it); reflex budgets must include thinking.
4. **Self-judging bias** — flagged per run; cross-model judging (2.5vl judging qwen3-vl and vice versa) is now default.
5. **n=1** — every game cell is exploratory; the testbed has larger n but is not a game.
6. **ToS battle confound** — AI allies win battles unaided; the task needs a contribution-based redesign (deferred).

## Ethics

Throwaway accounts and offline/emulated games only. OSRS ran on a dedicated throwaway (ban risk accepted). No credentials are ever handled by the agent. Kill switch armed every session; input clamped to the game window. The benchmark is for measuring agent capability, not for playing games competitively.

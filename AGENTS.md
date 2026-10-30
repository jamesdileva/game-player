# AGENTS.md

Working guide for AI agents (and humans) working in this repo. Read this before doing anything.

## What this project is

**AnyGame-Bench (`agb`)** — a local research harness that attaches to a running game window (emulated, offline, or throwaway account), gives an AI agent a one-line task, and measures whether and how efficiently it completes it using only screen pixels and mouse/keyboard input.

## Authoritative docs (repo root)

| Doc | Consult for |
|-----|-------------|
| `architecture.md` | System design, data contracts, judging rules, fairness, safety |
| `implementation-guide.md` | Stack, repo layout, module sketches, testing strategy, pitfalls |
| `sprint-roadmap.md` | Sprint plan, exit criteria, task backlog, definition of done |
| `addendum-attempt-mode.md` | Attempt-mode details (merged into the main docs; kept for provenance) |
| `experiment-hybrid-agent.md` | Hybrid/reflex experiment details (merged into the main docs; kept for provenance) |

When implementation diverges from `architecture.md`, update the doc in the same change set. New gotchas discovered while working go into `implementation-guide.md` (common pitfalls).

## Working agreement: every sprint runs four phases

1. **PLAN** — read the sprint's entry in `sprint-roadmap.md`; restate the goal and task list in plain language.
2. **SCOPE** — list the exact files/modules to create or touch, and turn the sprint's exit criteria into concrete testable checks. Present the scope to the user and get sign-off **before implementing**.
3. **IMPLEMENT** — the smallest change that satisfies the scope. Follow the code conventions below.
4. **VERIFY** — `pytest` must pass; walk through each exit criterion and show the evidence; produce the sprint's demo-able result.

Afterwards: **commit + push**. Use conventional commits with the sprint tag, e.g. `feat(sprint-0): window capture and input with calibration test`. One logical commit set per phase is fine; never mix unrelated changes.

No sprint is "done" with failing or skipped tests, and no sprint is "done" if an exit criterion is unverified.

## Code conventions

- Python 3.11+ (dev box runs 3.14), type hints everywhere, formatted with ruff.
- `pydantic` v2 models in `models.py` are the contracts; task specs, actions, and results validate against them.
- **Game-agnostic core:** game-specific knowledge (OCR regions, chat checks) lives in `adapters/`, never in `src/agb` core modules. If a game seems to need core changes, stop and scope an adapter instead.
- Windows-first; keep OS-specific code behind the `Capture` and `Input` interfaces.
- Tolerant parsing, strict recording: agent output is parsed leniently and every invalid output is counted, never hidden.
- Every module ships with tests in `tests/`; the fake game (`testbed/fakegame.py`) is the deterministic testbed — prove the harness there before touching any real game.
- The mock/scripted agent tests orchestration without model costs; never burn API tokens on tests.

## Safety rules (non-negotiable)

- Kill switch armed and tested before **every** session that injects input.
- Input is clamped to the game window; the agent cannot type into other apps.
- Throwaway accounts, emulators, and offline modes only. No online multiplayer, no kernel-anti-cheat titles. No credential handling by the agent.
- API keys live in environment variables; redact them from saved prompts and logs.
- Never commit `runs/`, `.env`, or anything containing keys.

## Repo layout

See `implementation-guide.md` §2 for the full tree. Short version: `src/agb/` (the harness), `testbed/` (fake game), `tasks/` (YAML task specs), `adapters/` (per-game helpers), `runs/` (gitignored run artifacts), `tests/`.

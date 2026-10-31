# AnyGame-Bench: Implementation Guide

Companion to `architecture.md`. This explains how to build it: stack, repo layout, and working sketches for each core module. Code is a starting point to adapt, not final.

## 1. Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Language | Python 3.11+ | Fast to iterate, best library coverage |
| Window capture | `mss` + `pygetwindow` (Windows) | Capture only the target window rect |
| Input | `pydirectinput` (Windows), `pyautogui` fallback | Many games ignore plain key events; DirectInput scancodes work more often |
| Kill switch | `pynput` global hotkey | Must work even if the game has focus |
| Process control | `psutil` | Paused-mode suspend/resume of native games; hardware logging |
| Image handling | `Pillow`, `opencv-python` | Resize, grid overlay, diffing |
| OCR (L2 assist, adapters) | `rapidocr-onnxruntime` or `pytesseract` | Local, free |
| HTTP/model calls | `httpx` | Talk to any OpenAI-compatible endpoint |
| Schemas | `pydantic` v2 | Validate specs, actions, results |
| CLI | `typer` | `agb run`, `agb judge`, `agb report` |
| Video | `ffmpeg` (subprocess) | Independent screen recording of the window |
| Storage | JSONL + files, SQLite for aggregated results | Simple, greppable, replayable |
| MCP mode | `mcp` Python SDK | Expose tools to opencode and others |

**Platform:** develop on Windows first (most target games run there). Linux works for emulators using `mss` + `xdotool`/`python-xlib`; keep OS-specific code behind `Capture` and `Input` interfaces.

## 2. Repo layout

```
game-player/
  pyproject.toml
  README.md
  AGENTS.md                   # working agreement: sprint workflow, conventions
  architecture.md             # docs live at the repo root
  implementation-guide.md
  sprint-roadmap.md
  tasks/
    osrs/kill-goblin.yaml
    osrs/gain-level.yaml
    emu/pokemon-first-battle.yaml
    testbed/click-the-red-square.yaml
  adapters/
    osrs.py                   # optional OCR/regions
  testbed/
    fakegame.py               # tiny pygame game for harness tests
    aimscene.py               # calibration micro-benchmark scene (hybrid experiment)
  src/agb/
    models.py                 # pydantic: TaskSpec, Action, StepRecord, Result
    config.py                 # load env, defaults, model profiles
    capture.py
    inputs.py
    killswitch.py
    perception.py             # downscale, grid overlay, OCR
    agent/
      base.py                 # Agent protocol
      openai_compat.py        # Mode A client
      hybrid.py               # planner + reflex topology
      parsing.py              # tolerant action parsing
      prompts.py
    intents.py                # planner -> reflex intent protocol
    reflex/
      classical.py            # CV tracking reflex
      detector.py             # small trained detector reflex
      vlm.py                  # fast small VLM reflex
    checkpoint.py             # attempt mode: persist/resume run state
    compaction.py             # context compaction for long runs
    casefile.py               # attempt-mode case file generator
    mcp_server.py             # Mode B
    research.py
    planner.py
    loop.py                   # execute phase
    orchestrator.py           # lifecycle + caps
    recorder.py
    judge.py
    postmortem.py
    report.py                 # aggregate tables
    cli.py                    # run, judge, report, attach, resume
  runs/                       # gitignored; one folder per run
  tests/
```

## 3. Core models

```python
# src/agb/models.py
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field

class Click(BaseModel):
    type: Literal["click"] = "click"
    x: int; y: int
    button: Literal["left", "right", "middle"] = "left"

class Key(BaseModel):
    type: Literal["key"] = "key"
    key: str
    hold_ms: int = 0

class Type_(BaseModel):
    type: Literal["type"] = "type"
    text: str

class Wait(BaseModel):
    type: Literal["wait"] = "wait"
    ms: int = 500

class Note(BaseModel):
    type: Literal["note"] = "note"
    text: str

class Done(BaseModel):
    type: Literal["done"] = "done"
    claim: str = ""

# add DoubleClick, Drag, Move, Scroll the same way
Action = Union[Click, DoubleClick, Drag, Move, Key, Type_, Scroll, Wait, Note, Done]

class Limits(BaseModel):
    max_steps: int = 300
    max_wall_minutes: float = 45
    max_wall_hours: Optional[float] = None  # attempt mode: primary cap
    max_cost_usd: float = 5.0

class SuccessConfig(BaseModel):
    evidence: str
    evidence_step: Optional[str] = None
    verifiers: list[str] = ["vlm"]

class ResearchConfig(BaseModel):
    mode: Literal["web", "none", "provided"] = "web"
    max_minutes: int = 10

class LoopConfig(BaseModel):
    time_mode: Literal["realtime", "paused"] = "realtime"
    assist_level: Literal["L0", "L1", "L2"] = "L0"
    topology: Literal["single", "hybrid"] = "single"
    decision_hz: Optional[float] = None

# Task spec fields mirror the nested YAML contract in architecture.md 7.1
class TaskSpec(BaseModel):
    id: str
    game: str
    title: str = ""
    goal: str
    tier: int = 1
    mode: Literal["study", "attempt"] = "study"
    start_state: str = ""
    success: SuccessConfig
    limits: Limits = Limits()
    checkpoint_every_steps: int = 25
    research: ResearchConfig = ResearchConfig()
    loop: LoopConfig = LoopConfig()
```

## 4. Capture and input

```python
# src/agb/capture.py
import time, mss
from PIL import Image
import pygetwindow as gw

class WindowCapture:
    def __init__(self, title_substring: str, max_w=1280, max_h=720):
        wins = [w for w in gw.getAllWindows() if title_substring.lower() in w.title.lower()]
        if not wins:
            raise RuntimeError(f"No window matching {title_substring!r}")
        self.win = wins[0]
        self.max_w, self.max_h = max_w, max_h
        self.sct = mss.mss()

    def rect(self):
        w = self.win
        return {"left": w.left, "top": w.top, "width": w.width, "height": w.height}

    def grab(self):
        """Returns (full_res, agent_view, scale) where scale maps agent coords -> window px."""
        shot = self.sct.grab(self.rect())
        full = Image.frombytes("RGB", shot.size, shot.rgb)
        scale = min(self.max_w / full.width, self.max_h / full.height, 1.0)
        view = full.resize((int(full.width * scale), int(full.height * scale)))
        return full, view, scale, time.time()
```

```python
# src/agb/inputs.py
import time, pydirectinput as pdi

pdi.PAUSE = 0.02

class WindowInput:
    def __init__(self, capture):
        self.cap = capture

    def _to_screen(self, x, y, scale):
        r = self.cap.rect()
        sx = r["left"] + int(x / scale)
        sy = r["top"] + int(y / scale)
        # Clamp to the game window; refuse anything outside
        if not (r["left"] <= sx < r["left"] + r["width"] and r["top"] <= sy < r["top"] + r["height"]):
            raise ValueError("Action outside game window")
        return sx, sy

    def click(self, x, y, scale, button="left"):
        sx, sy = self._to_screen(x, y, scale)
        pdi.moveTo(sx, sy); time.sleep(0.03)
        pdi.click(button=button)

    def key(self, key, hold_ms=0):
        if hold_ms:
            pdi.keyDown(key); time.sleep(hold_ms / 1000); pdi.keyUp(key)
        else:
            pdi.press(key)
```

Tips:
- Bring the game window to the foreground at run start and re-check focus before each action batch.
- Some games need windowed or borderless mode for capture to work. Exclusive fullscreen often captures black.
- Use a fixed window size via a setup script so all runs match.

## 5. Kill switch

```python
# src/agb/killswitch.py
import threading
from pynput import keyboard

class KillSwitch:
    def __init__(self, combo="<ctrl>+<alt>+q"):
        self.event = threading.Event()
        self._listener = keyboard.GlobalHotKeys({combo: self.event.set})
        self._listener.daemon = True
        self._listener.start()

    @property
    def tripped(self):
        return self.event.is_set()
```

Check `kill.tripped` before every action and every model call. Test it before every long run.

## 6. Perception helpers

```python
# src/agb/perception.py
from PIL import Image, ImageDraw

def grid_overlay(img: Image.Image, step=80):
    out = img.copy()
    d = ImageDraw.Draw(out)
    for x in range(0, out.width, step):
        d.line([(x, 0), (x, out.height)], fill=(255, 255, 0), width=1)
        d.text((x + 2, 2), str(x), fill=(255, 255, 0))
    for y in range(0, out.height, step):
        d.line([(0, y), (out.width, y)], fill=(255, 255, 0), width=1)
        d.text((2, y + 2), str(y), fill=(255, 255, 0))
    return out
```

Apply this only when `assist_level >= L1`. At L0 the agent sees the raw frame.

## 7. Agent interface (Mode A)

```python
# src/agb/agent/base.py
from typing import Protocol
class Agent(Protocol):
    def decide(self, system: str, history: list[dict], images: list[bytes]) -> "Decision": ...
```

```python
# src/agb/agent/openai_compat.py
import base64, io, time, httpx

class OpenAICompatAgent:
    def __init__(self, base_url, api_key, model, price_in=0.0, price_out=0.0):
        self.client = httpx.Client(base_url=base_url, timeout=120,
                                   headers={"Authorization": f"Bearer {api_key}"})
        self.model, self.pi, self.po = model, price_in, price_out

    @staticmethod
    def _img(jpeg: bytes):
        b64 = base64.b64encode(jpeg).decode()
        return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}

    def decide(self, system, user_text, jpegs):
        content = [{"type": "text", "text": user_text}] + [self._img(j) for j in jpegs]
        body = {"model": self.model, "temperature": 0.3,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}]}
        t0 = time.time()
        r = self.client.post("/chat/completions", json=body); r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {})
        cost = usage.get("prompt_tokens", 0) * self.pi + usage.get("completion_tokens", 0) * self.po
        return data["choices"][0]["message"]["content"], {
            "in_tokens": usage.get("prompt_tokens", 0),
            "out_tokens": usage.get("completion_tokens", 0),
            "cost_usd": cost, "latency_ms": int((time.time() - t0) * 1000)}
```

This one client covers OpenRouter, Ollama (`http://localhost:11434/v1`), LM Studio, and most vendor APIs. Put per-model settings (base URL, price, vision support) in a `models.yaml` profile file.

### Tolerant parsing

```python
# src/agb/agent/parsing.py
import json, re
from pydantic import TypeAdapter
from ..models import Action

_adapter = TypeAdapter(list[Action])

def parse_actions(text: str):
    """Extract a JSON object like {"thought": "...", "actions": [...]}.
    Handles code fences and surrounding prose. Returns (thought, actions, error)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return "", [], "no_json"
    try:
        obj = json.loads(m.group(0))
        return obj.get("thought", ""), _adapter.validate_python(obj.get("actions", [])), None
    except Exception as e:
        return "", [], f"parse_error: {e}"
```

On an error, re-ask once with the error message. Count every invalid output in `invalid_actions`.

### Prompts (sketch)

```python
SYSTEM = """You control a computer to complete a goal in a video game, using only the screen.
You see screenshots of the game window and act with mouse and keyboard.
Reply ONLY with JSON: {"thought": "...", "actions": [ ... ]}
Actions: click(x,y,button), double_click, drag, move, key(key,hold_ms), type(text),
scroll, wait(ms), note(text), done(claim).
Coordinates are pixels in the screenshot you see (origin top-left).
Use note to keep a scratchpad; it is shown back to you every step.
Send 1-3 actions per turn. Only call done when you believe the goal is met,
and be ready to show evidence on screen."""
```

Each turn's user message includes: goal, plan and current subgoal, scratchpad, last few action outcomes, and the latest frames.

## 8. Research and planning

```python
# src/agb/research.py (sketch)
RESEARCH_PROMPT = """Goal: {goal}
Game: {game}
Research how to accomplish this goal. Produce a brief covering: controls,
the relevant mechanics, where to go and what to click, risks, and how to
tell the goal is achieved. Be concise and cite what you used."""
```

- With `research_mode=web`, run a tool-calling loop (search + fetch) capped by `max_minutes`. For models without tool calling, run a harness-driven loop: model emits `SEARCH: <query>`, harness fetches top results, summarizes, repeats.
- With `none`, ask the model to write the brief from memory only.
- With `provided`, copy a fixed human-written brief. This isolates execution ability from research ability.

Planner: one call producing JSON subgoals, each with a `check` string. Store as `plan.md`. The loop includes the current subgoal in every prompt, and the agent may issue `{"type":"note","text":"REPLAN: ..."}` or the loop triggers a replan after N steps without progress.

## 9. The execute loop

```python
# src/agb/loop.py (sketch)
def execute(task, agent, cap, inp, rec, kill, state):
    for step in range(task.limits.max_steps):
        if kill.tripped or state.over_budget(): return "aborted"
        full, view, scale, ts = cap.grab()
        view = apply_assist(view, task.assist_level)
        rec.save_frame(step, full)
        prompt = build_prompt(task, state)          # plan, scratchpad, history
        if task.time_mode == "paused": state.game.pause()
        raw, usage = agent.decide(SYSTEM, prompt, state.recent_jpegs(view))
        if task.time_mode == "paused": state.game.resume()
        thought, actions, err = parse_actions(raw)
        if err: state.invalid += 1; continue
        for a in actions:
            if a.type == "done": return "claimed_done"
            if a.type == "note": state.scratchpad = a.text; continue
            perform(a, inp, scale)
        state.update(step, thought, actions, usage)
        rec.log_step(step, thought, actions, usage, err)
        detect_stuck(state)                         # frame diff; trigger replan or fail-fast
```

`detect_stuck`: compare successive downscaled frames and action repeats. If the screen hasn't meaningfully changed for N steps while actions repeat, record a `stuck_event` and inject a hint into the next prompt ("Your last 5 actions did not change the screen"). Keep the hint identical across all models.

### 9.1 Long-run support (attempt mode)

- **Checkpointing:** every `checkpoint_every_steps` steps, dump plan, scratchpad, compacted history, and counters to `checkpoint.json` in the run folder. `agb resume <run_dir>` reloads and continues; the gap is logged and excluded from thinking time.
- **Compaction:** every K steps, summarize old history into a running "story so far"; keep only recent frames; log what was dropped.
- **Rate-limit tolerance:** back off and retry on free-tier limits; log waits separately from inference time.
- **Hardware record:** log CPU, GPU, RAM, runtime, and tokens/second (`psutil`) in every result; local results mean little without them.
- **Grammar-constrained decoding:** where the local runtime supports it, enforce the action JSON schema to cut invalid actions; reported as its own switch.

## 10. Recorder

- Start `ffmpeg` at run begin to capture the window region at ~10 fps (gdigrab on Windows, x11grab on Linux), writing `run.mp4`.
- Write `steps.jsonl` line by line (flush each step so crashes still leave data).
- Save frames as JPEG quality ~80; keep full-res only for sampled keyframes if disk is a concern.
- Run folder layout: `runs/<date>_<task>_<model>_<n>/{task.yaml, brief.md, plan.md, steps.jsonl, frames/, run.mp4, result.json, postmortem.md}`.
- Timestamp every frame at grab time with both the wall clock and a monotonic clock, so reaction times (`reaction_ms` in hybrid experiments) can be computed from the recording.

## 11. Judge

```python
# src/agb/judge.py (sketch)
JUDGE_PROMPT = """Task: {goal}
Success evidence required: {evidence}
You are given a baseline screenshot from before the run, and keyframes from the run.
Decide whether the task was accomplished. You must cite frame numbers.
Reply JSON: {{"verdict": "success|partial|fail", "confidence": 0-1,
"cited_frames": [..], "reasoning": "..."}}
Be strict: if the required evidence is not visible, answer fail."""
```

Keyframe selection: frames around the claim, the evidence-step frames, a uniform sample, and frames where the screen changed most. Do not pass the agent's thoughts. Run the judge twice with different frame orders and require agreement, or escalate to a stronger model on disagreement.

Adapters add deterministic checks. Example OSRS adapter idea: OCR the chat box region each N frames, look for "defeated" or "killed", and compare XP numbers in the skills tab before and after.

## 12. Mode B: MCP server

Expose the same `Capture` and `WindowInput` through MCP tools:

```python
# src/agb/mcp_server.py (sketch)
from mcp.server.fastmcp import FastMCP, Image
mcp = FastMCP("anygame")

@mcp.tool()
def screenshot() -> Image: ...
@mcp.tool()
def click(x: int, y: int, button: str = "left") -> str: ...
@mcp.tool()
def key(key: str, hold_ms: int = 0) -> str: ...
@mcp.tool()
def note(text: str) -> str: ...
@mcp.tool()
def done(claim: str) -> str: ...
```

Register it in opencode's MCP config, then give the agent the task text. Count tool calls server-side, and enforce the same caps (the server starts refusing after `max_steps`). Mode B needs a vision-capable model in opencode; pure text models can't use `screenshot`.

## 13. Testing strategy

1. **Fake game** (`testbed/fakegame.py`): a small pygame window with a red square to click, then a door, then an enemy. Gives deterministic ground truth to test capture, input mapping, caps, and the judge before touching a real game.
2. **Replay test:** feed a recorded run through the judge and post-mortem without calling the game.
3. **Coordinate calibration test:** the harness clicks known targets and verifies via the fake game that the mapping is exact at several window sizes and DPI scalings. (Set DPI awareness at startup; mismatched scaling is the most common bug.)
4. **Kill switch test** before each session.
5. **Mock agent:** a scripted agent that returns canned actions, to test the orchestrator without model costs.

## 14. Reporting

`agb report` reads `result.json` files into SQLite and prints per (task, model, config):
success rate, median/IQR steps, median wall time, median cost, failure-category histogram, and judge agreement. Always show the number of runs `n`, and never rank models on `n < 5`.

## 15. Common pitfalls

- **DPI scaling** shifting click positions. Fix with `ctypes.windll.shcore.SetProcessDpiAwareness(2)`.
- **Black captures** from exclusive fullscreen or protected content. Use windowed/borderless.
- **Window decorations offset.** A windowed game's outer rect (816x639 for an 800x600 client) includes the title bar and borders. Capture and click-map the CLIENT area (`GetClientRect` + `ClientToScreen`), or every coordinate is offset by the decorations and the agent can click the title bar and drag the window.
- **Occluded captures.** The capture grabs the screen region at the window rect, so any window overlapping the game pollutes frames and breaks frame-diff stuck detection. Bring the game to the foreground at run start and re-check focus each step.
- **Injected input silently swallowed.** A live human mouse overrides synthetic moves, and UIPI drops injected input while an elevated window is foreground. Verify the cursor actually reached the target (`GetCursorPos`) before every click and refuse the action otherwise — a stray click lands in whatever app the cursor is really over.
- **Games ignoring injected input.** Try DirectInput scancodes, run the harness as administrator, or use an emulator.
- **Agent clicking before the screen updates.** Add a short settle delay (e.g., 300 ms) after actions before the next capture.
- **Weak-model JSON failures.** Keep the schema small, show one example, and limit to 1-3 actions per turn. Expect function-call syntax (`click(430, 330)`) and string/float coordinates (`"x": "430"`) regardless of the prompt contract — the tolerant parser coerces both and counts what remains.
- **Cost surprises.** Enforce `max_cost_usd`, downscale frames, and send only the last few frames.
- **Judge leakage.** Never let the judge see agent thoughts or the done claim as evidence.

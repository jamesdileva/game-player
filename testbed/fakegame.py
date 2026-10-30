"""Fake game: deterministic testbed for the harness (implementation-guide 13.1).

A tiny pygame-ce window with three click-only stages:
  1. click the red square (default 3 hits)   2. click the door   3. tag the enemy

The state machine (FakeGameState) is pure Python and unit-testable without a
display; the pygame loop below only renders it. Window title mirrors progress
(``FakeGame | stage N | hits k/N``) so scripts can read state without OCR.

Usage:
    python testbed/fakegame.py [--size WxH] [--square X,Y] [--hits N]

Prints one JSON line per state change (flushed) so a harness can follow along.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # run without install

SQUARE_SIZE = 60
DOOR = (60, 60, 80, 160)  # x, y, w, h
ENEMY = (600, 420, 48, 48)


def _inside(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


@dataclass
class FakeGameState:
    """Pure state machine; all coordinates are window-space pixels."""

    width: int = 800
    height: int = 600
    square_xy: tuple[int, int] = (400, 300)  # top-left of the square
    hits_needed: int = 3
    hits: int = 0
    stage: int = 1  # 1 square, 2 door, 3 enemy, 4 complete
    events: list[str] = field(default_factory=list)

    @property
    def square_rect(self) -> tuple[int, int, int, int]:
        return (*self.square_xy, SQUARE_SIZE, SQUARE_SIZE)

    def register_click(self, x: int, y: int) -> str | None:
        """Register a window-space click; returns the event name or None."""
        event: str | None = None
        if self.stage == 1 and _inside(x, y, self.square_rect):
            self.hits += 1
            if self.hits >= self.hits_needed:
                self.stage, event = 2, "stage_door"
            else:
                event = "hit_square"
        elif self.stage == 2 and _inside(x, y, DOOR):
            self.stage, event = 3, "stage_enemy"
        elif self.stage == 3 and _inside(x, y, ENEMY):
            self.stage, event = 4, "complete"
        if event:
            self.events.append(event)
        return event


def run(width: int, height: int, square_xy: tuple[int, int], hits_needed: int) -> None:
    import pygame  # imported here so FakeGameState stays importable headless

    from agb.config import ensure_dpi_awareness

    ensure_dpi_awareness()
    pygame.init()
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("FakeGame")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 30)
    state = FakeGameState(width, height, square_xy, hits_needed)
    colors = {
        "bg": (30, 30, 34),
        "square": (211, 47, 47),
        "door": (139, 94, 60),
        "enemy": (211, 47, 47),
        "text": (240, 240, 240),
    }

    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                running = False
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                ev = state.register_click(*e.pos)
                if ev:
                    print(
                        json.dumps({"event": ev, "hits": state.hits, "stage": state.stage}),
                        flush=True,
                    )

        screen.fill(colors["bg"])
        if state.stage >= 1:
            pygame.draw.rect(screen, colors["square"], state.square_rect)
        if state.stage >= 2:
            pygame.draw.rect(screen, colors["door"], DOOR)
        if state.stage >= 3:
            ex, ey, es, _ = ENEMY
            pygame.draw.circle(screen, colors["enemy"], (ex + es // 2, ey + es // 2), es // 2)
        hud = f"stage {state.stage} | hits {state.hits}/{state.hits_needed}"
        screen.blit(font.render(hud, True, colors["text"]), (16, 12))
        pygame.display.set_caption(f"FakeGame | {hud}")
        pygame.display.flip()
        clock.tick(30)
    pygame.quit()


def main() -> None:
    p = argparse.ArgumentParser(description="AnyGame-Bench fake game testbed")
    p.add_argument("--size", default="800x600", help="window size, e.g. 800x600")
    p.add_argument("--square", default="400,300", help="red square top-left, e.g. 400,300")
    p.add_argument("--hits", type=int, default=3, help="hits needed to clear stage 1")
    args = p.parse_args()
    w, h = (int(v) for v in args.size.split("x"))
    sx, sy = (int(v) for v in args.square.split(","))
    run(w, h, (sx, sy), args.hits)


if __name__ == "__main__":
    main()

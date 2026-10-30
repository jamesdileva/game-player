"""agb command line. Sprint 0 provides capture-debugging helpers only."""

from __future__ import annotations

import typer

from agb.config import ensure_dpi_awareness

app = typer.Typer(help="AnyGame-Bench harness", no_args_is_help=True)


@app.command()
def windows() -> None:
    """List visible windows (title, size, position) to debug capture targets."""
    ensure_dpi_awareness()
    import pygetwindow as gw

    for w in gw.getAllWindows():
        if w.title and w.width > 0 and w.height > 0:
            print(f"{w.width:>5}x{w.height:<5} @ ({w.left:>5},{w.top:>5})  {w.title}")


if __name__ == "__main__":
    app()

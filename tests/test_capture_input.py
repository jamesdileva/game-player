"""UI tests: window capture, coordinate mapping, input injection, window clamping.

These open a real window and move the real cursor (marked `ui`).
"""

from __future__ import annotations

import time

import pytest

from agb.capture import WindowCapture, WindowNotFoundError
from agb.inputs import InputRejected, WindowInput

pytestmark = pytest.mark.ui


def _red_centroid(img):
    """Ground-truth position of the red square: mean of pure-red pixels."""
    data = img.tobytes()  # RGB, 3 bytes per pixel
    w = img.width
    xs = ys = n = 0
    for i in range(0, len(data), 3):
        if data[i] > 180 and data[i + 1] < 80 and data[i + 2] < 80:
            p = i // 3
            xs += p % w
            ys += p // w
            n += 1
    if n == 0:
        pytest.fail("No red pixels found in capture; is the fake game rendering?")
    return xs / n, ys / n


def _round_trip_click(win):
    """Capture -> ground truth -> coordinate mapping -> click -> verify the hit."""
    cap = WindowCapture("FakeGame")
    inp = WindowInput(cap)
    full, _, scale, _ = cap.grab()
    wx, wy = _red_centroid(full)
    ax, ay = wx * scale, wy * scale  # window px -> agent view px

    try:
        win.activate()
    except Exception:
        pass  # focus stealing can be blocked; the click still lands under the cursor
    time.sleep(0.2)

    inp.click(ax, ay, scale)

    deadline = time.time() + 5
    while time.time() < deadline and "hits 1/3" not in win.title:
        time.sleep(0.1)
    assert "hits 1/3" in win.title, f"title={win.title!r}"


class TestCapture:
    def test_no_window_raises(self):
        with pytest.raises(WindowNotFoundError):
            WindowCapture("DefinitelyNotARealWindow12345")

    def test_grab_downscales_and_returns_scale(self, fakegame):
        cap = WindowCapture("FakeGame", max_w=640, max_h=480)
        full, view, scale, ts = cap.grab()
        assert full.width == fakegame.width and full.height == fakegame.height
        assert view.width <= 640 and view.height <= 480
        expected = min(640 / full.width, 480 / full.height, 1.0)
        assert abs(scale - expected) < 1e-6
        assert ts > 0
        # Agent view preserves aspect ratio
        assert abs(view.width / view.height - full.width / full.height) < 0.01


class TestInputMapping:
    def test_out_of_window_clicks_refused(self, fakegame):
        cap = WindowCapture("FakeGame")
        inp = WindowInput(cap)
        _, _, scale, _ = cap.grab()
        with pytest.raises(InputRejected):
            inp.click(-30, -30, scale)  # negative agent coords
        with pytest.raises(InputRejected):
            inp.click(10_000, 10_000, scale)  # far past the right/bottom edge

    def test_scripted_click_hits_the_square(self, fakegame):
        """Exit criterion 1: a scripted action list clicks the red square exactly.

        The capture itself provides ground truth (red-pixel centroid), so this
        validates the full capture -> coordinate mapping -> injection round trip.
        """
        _round_trip_click(fakegame)

    @pytest.mark.parametrize(
        "size,square", [("800x600", "400,300"), ("1024x768", "250,150")]
    )
    def test_click_calibration_across_window_sizes(self, spawn, size, square):
        """Calibration: the mapping must stay exact at several window sizes (guide 13.3)."""
        with spawn(size=size, square=square) as win:
            _round_trip_click(win)

# OSRS start state (human checklist)

Do this once per session BEFORE running `agb run`. The harness never touches
credentials; you log in.

1. Launch the client (official launcher or RuneLite) and log in on the
   **throwaway** account.
2. Set the client to **windowed FIXED layout** and a stable size (the classic
   fixed layout keeps UI regions stable for capture and future OCR).
3. Walk the character to the goblin area **east of Lumbridge** (across the
   bridge) and stop near a goblin spawn.
4. Test the kill switch: run `agb calibrate`-style check or the kill-switch
   test once, then press Ctrl+Alt+Q yourself and confirm the listener trips
   (the harness also refuses to run unarmed).
5. Confirm the window title: hover `agb windows` — the official client is
   titled `RuneScape`, RuneLite is `RuneLite`. Pass
   `agb run --window-title <title>` if it differs from the adapter default.
6. Do NOT position other windows over the client. The capture grabs the
   client region only, but overlap pollutes frames.
7. Kill-switch armed check is automatic: the harness refuses to run if the
   listener is not alive.

Ban risk is accepted on the throwaway only. Never let the agent act while you
are typing elsewhere; the input is clamped to the client window and the
cursor-verification safeguard refuses clicks whose cursor did not arrive.

# Kaiagotchi Dashboard — Fix Action Plan

## Root Cause Summary

All three symptoms share one root cause: **the display architecture is fundamentally different from the reference**. `btop_dashboard_v2.py` uses `curses.wrapper` with a snapshot model. Kaiagotchi's `terminal_display.py` uses raw ANSI escape sequences written from multiple competing asyncio coroutines. You can't patch your way to a stable display from this base — the architecture itself is what's broken.

---

## Why Each Symptom Happens

### 1. Chatter window flipping between chatter and mood lines

The display has no single source of truth for what to show. Six different code paths all call `render()` independently with partial state dicts:

- `View._chatter_loop()` — every 5s, sends `state["status"] = new mood voice line`
- `View.async_update()` — every monitoring update, sends `recent_captures`
- `View._run_loop()` — every 3s, sends `chatter_log`
- `View.update_mood()` — on every mood change, sends `status = mood line`
- `Automata._apply_mood()` — on mood transition, calls `view.update_mood()`
- `Automata._maybe_drift()` — random drift, calls `_apply_mood()`

Each call passes a *different* partial dict. Whichever one runs last wins. The System Chatter box reads `state.get("recent_captures") or state.get("chatter_log")`. The speech bubble reads `state.get("status")`. These keys are populated by different callers at different times. The chatter loop overwrites `status` with a voice line every 5 seconds, which wipes out the network event that just appeared. Then the next monitoring update pushes the network capture back. You see it flip because it IS flipping — two separate async tasks are fighting over the same display field.

In the reference: `_take_snapshot()` is the only place state is read. It runs once per frame. One immutable `DashboardState` object is created. `_draw_frame()` reads from it. Nothing else touches the display. No fights possible.

### 2. Q doesn't quit

`TerminalDisplay` has zero keyboard input handling. There is no `getch()` call anywhere. Q goes to the shell or is dropped. Only Ctrl+C works because that's caught by `asyncio`'s signal handler in `cli.py`. Even then you have to mash it because the signal handler sets `_shutdown_event` and then waits for async tasks to cancel — which takes several seconds if any task is slow.

In the reference: `stdscr.nodelay(True)` + `stdscr.getch()` runs every frame. Q is caught immediately, sets the `stop_event`, and the loop exits. One keypress, clean exit.

### 3. Output left in terminal after exit

On startup `terminal_display.py` writes `\033[?1049h` (enter alternate screen buffer). On exit, `atexit` callbacks write `\033[?1049l` (leave alternate screen). The problem is threefold:

1. If you Ctrl+C repeatedly, you're sending SIGINT multiple times. The second SIGINT in `cli.py` calls `os._exit(0)` — hard exit, **atexit does not run**, the alternate buffer never closes, the last rendered frame stays on screen.
2. Even on clean exit, the asyncio loop teardown happens in `cli.py`'s `finally` block. Background tasks may still write to `sys.__stdout__` during teardown, corrupting the terminal state before `atexit` fires.
3. `curses.wrapper` handles none of this — because there is no `curses.wrapper`.

In the reference: `curses.wrapper(self._main_loop)` wraps the entire session. `curses.wrapper` calls `curses.endwin()` in a `try/finally`. Terminal is restored even if an exception is thrown. This is the correct, guaranteed mechanism.

---

## The Fix: What Needs to Change

### File 1: `kaiagotchi/ui/terminal_display.py` — Full rewrite to curses

Replace the raw ANSI renderer with a `curses.wrapper`-based renderer following the reference architecture exactly:

**Structure to implement:**

```
KaiagotchiDisplay
├── __init__(stop_event, shared_state_getter)
│   └── stop_event: threading.Event (set by Q key or external shutdown)
│   └── shared_state_getter: callable returning current dict
├── _init_curses(stdscr)
│   └── curs_set(0), nodelay(True), timeout(100), keypad(True), init colors
├── _take_snapshot() -> KaiDisplayState   ← THE KEY CHANGE
│   └── Reads from shared_state_getter ONCE per frame
│   └── Returns immutable dataclass
├── _handle_input() -> bool
│   └── getch(), if Q/q → stop_event.set(), return False
│   └── Called every frame before drawing
├── _draw_frame(state: KaiDisplayState)
│   └── stdscr.erase()
│   └── _draw_bot_status_pane(state)
│   └── _draw_scoreboard_pane(state)
│   └── _draw_spectrum_pane(state)
│   └── _draw_ap_table_pane(state)
│   └── _draw_stations_pane(state)
│   └── _draw_chatter_pane(state)   ← fed from single deque
│   └── stdscr.refresh()
├── _main_loop(stdscr)
│   └── _init_curses(stdscr)
│   └── while not stop_event.is_set():
│       └── _handle_input()
│       └── state = _take_snapshot()
│       └── _draw_frame(state)
│       └── time.sleep(frame_interval)
└── run()
    └── curses.wrapper(self._main_loop)   ← GUARANTEED cleanup
```

**Key changes vs current:**
- `stdscr.erase()` at the start of every frame — no stale content
- Chatter fed from a `deque(maxlen=50)` that is only appended to, never overwritten
- All network events, thoughts, and mood lines go INTO the deque — nothing replaces the deque
- Status/speech bubble shows the LATEST entry in the deque, not a separate volatile field
- `curses.wrapper` — terminal restore is guaranteed

---

### File 2: `kaiagotchi/ui/view.py` — Stop calling render() from everywhere

The View's job changes to **state aggregation only**. It should never call `render()` directly.

Changes needed:

1. **Remove all `display.render()` calls** from `async_update()`, `update_mood()`, `_chatter_loop()`, `_run_loop()`, `_handle_recent_captures()`, and `on_starting()`.

2. **`async_update()` becomes a pure state merger** — it merges incoming state into `self.state`, appends events to the chatter deque, and returns. That's it.

3. **`update_mood()` becomes a pure state setter** — sets mood fields, appends a mood line to the chatter deque, returns. Does not call render.

4. **`_chatter_loop()` is deleted entirely** — the display's own frame loop handles chatter timing by reading from the deque at render time.

5. **`_run_loop()` is deleted entirely** — the display's frame loop handles refresh.

6. **Expose one method: `get_snapshot_dict()` or a property `current_state`** — returns the current merged state dict for the display to snapshot from.

The display calls `view.get_snapshot_dict()` once per frame inside `_take_snapshot()`. The View only ever writes to its internal state. The display only ever reads from it. No more bidirectional coupling.

---

### File 3: `kaiagotchi/cli.py` — Fix the shutdown double-SIGINT kill

The second Ctrl+C calls `os._exit(0)`. This prevents atexit from running and was needed to escape stuck async tasks. With `curses.wrapper`, it's no longer necessary — Q exits cleanly. But the signal handler still needs fixing so a single Ctrl+C doesn't take 30 seconds:

```python
# Replace the current handle_signal with:
def handle_signal():
    logger.info("Signal received, initiating shutdown...")
    _shutdown_event.set()
    # Also signal the display to stop immediately
    if display_stop_event:
        display_stop_event.set()
```

Set a short timeout on task cancellation (5 seconds max), then hard-exit if tasks don't comply. Don't wait indefinitely for `MonitoringAgent` or `Agent` to finish gracefully while the user is staring at a frozen terminal.

---

### File 4: `kaiagotchi/ui/view.py` — The chatter deque

Add a `threading.deque` to View as the single source of truth for all chatter:

```python
self._chatter_deque: deque = deque(maxlen=50)
```

Every source of display events appends to this deque:
- Network events from `async_update()` → `deque.append()`
- Mood transitions from `update_mood()` → `deque.append()`  
- Thoughts from `_handle_recent_captures()` → `deque.append()`
- System events from Agent → `deque.append()`

The display reads `list(deque)[-visible_lines:]` when rendering the chatter pane. It never sees a half-replaced list. It never gets a state where chatter was wiped and replaced with a mood line. It just sees the last N entries in chronological order.

---

## Implementation Order

Do these in order — each step is independently testable:

**Step 1** — Rewrite `terminal_display.py` with curses.wrapper and snapshot model. At this point Q works and terminal restores correctly. Chatter will still be unstable because View is still pushing conflicting state.

**Step 2** — Add the chatter deque to `view.py`. Wire all event sources (async_update, update_mood, _handle_recent_captures) to append to it instead of setting `state["status"]`. Remove the `_chatter_loop` asyncio task. Expose `get_snapshot_dict()`.

**Step 3** — Remove all `display.render()` calls from `view.py`. Display is now the only thing that calls render, exactly once per frame.

**Step 4** — Fix `cli.py` shutdown to use `display_stop_event` and a hard timeout.

**Step 5** — Test: run the agent, verify chatter scrolls correctly, verify Q exits in <1 second, verify terminal is clean after exit.

---

## What NOT to Do

- Do not try to fix the flipping by adding more debounce/throttle logic to the current render paths. You will reduce the frequency of the jank, not eliminate it.
- Do not try to add Q-key handling by reading stdin in a separate thread while the ANSI renderer runs in asyncio. This adds a second input mechanism and creates stdin ownership conflicts.
- Do not keep atexit as the primary terminal cleanup mechanism. It's a fallback, not a guarantee. `curses.wrapper` is the guarantee.

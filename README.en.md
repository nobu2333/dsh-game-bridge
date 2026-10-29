# dsh-game-bridge

**Give DeepSeek Harness eyes and hands on your games.**

> Status: **M2/M3 in progress (not published yet).** Screen capture + OCR work and
> the engine installs itself on first activation. Control is **dry-run by default**
> (it records actions instead of injecting input); the real gamepad backend has not
> been verified on hardware yet.

DSH has a brain (models, tools, sessions) but no eyes or hands: it can read files,
run commands and browse the web, yet it cannot see the game you are playing or press
a button. dsh-game-bridge plugs a thin plugin shell into DSH and backs it with a
local engine:

- **eyes** — screen capture (DXcam), frame differencing, OCR (RapidOCR), 20 Hz entity tracking (planned);
- **hands** — virtual gamepad (XInput via ViGEmBus), keyboard/mouse (planned);
- **cerebellum** — a local ~20 Hz closed loop; the model picks goals, not keystrokes;
- **safety** — takeover hotkey, anti-cheat refusal, unattended guard, local audit log.

## Why target-level tools, not per-step tools

A model tool call takes 3–5 seconds. Deciding "move right one step" through tool
calls makes the companion comatose in-game. Tools therefore expose goals only
(attach a window, look once, run one bounded loop, stop), while reflexes stay in the
local loop.

## Install (after release)

```bash
dsh plugin --profile web add dsh-game-bridge
```

- Requires DSH `>= 0.2.1-rc.2 < 0.3.0`, Node `>= 22`.
- On first activation the plugin installs its Python engine into a user cache
  (`uv venv` + `uv pip install dsh-game-core`); no system Python is required,
  but `uv` must be available.
- Platform: **Windows 10/11 only** for v1 (capture, virtual gamepad and input
  injection are Win32).

## Tools

| Tool | Meaning |
|:--|:--|
| `game_selftest` | Is the plugin loaded, is the engine ready |
| `game_snapshot` | One frame as an image + OCR text |
| `game_windows` | List visible windows (title, process, size) |
| `game_events` | Cheap frame-difference event (baseline / static / changed / scene_cut) |
| `game_attach` | Attach to a window (the user-authorization step) |
| `game_act` | Press one gamepad button (dry-run by default) |
| `game_plan` | Bounded local ~20 Hz loop (hold / tap / advance with stuck-detection sidestep) |
| `game_status` | Attach state, safety verdict, loop progress, audit tail |
| `game_stop` | Stop the loop, release everything, detach |

## Safety commitments

1. **Always take back control** — a local F12 hotkey latches takeover without the model;
2. **No unattended self-play** — no human input for `DSH_GAME_BRIDGE_UNATTENDED_S`
   (default 180 s), or no input telemetry at all, means output is refused;
3. **No anti-cheat games** — EAC / BattlEye / Vanguard / ACE processes hard-block all output;
4. **Read-only default** — capture + gamepad only; no memory reading, no injection.

## Development

See [README.md](README.md) (Chinese) for the full test matrix, engine self-check and
bootstrap verification, and [docs/DESIGN.md](docs/DESIGN.md) for the design decisions.

## License

MIT. See [LICENSE](LICENSE).


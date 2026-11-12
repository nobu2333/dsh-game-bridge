# dsh-game-bridge

**Let DeepSeek Harness models see and play slow-paced games.**

[中文](README.md) · [Status](docs/STATUS.md) · [Play protocol](docs/PLAY.md) · [Design](docs/DESIGN.md) · [Controls](docs/CONTROLS.md)
(the docs under `docs/` are in Chinese)

> Status: **0.0.1 released** (npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`); 0.0.2 is not published yet.
> Windows only. **Dry-run by default**: actions are recorded, not injected.
> Current milestone: the model plays a full game of 2048 through this plugin and beats a random-input baseline (see [STATUS](docs/STATUS.md)).

## What it is

DSH has models, tools and sessions, but it cannot see the game on your screen or press a key.
This plugin adds both:

- **eyes**: screen capture (DXcam, or window-level PrintWindow), OCR (RapidOCR), frame-diff events;
- **hands**: keyboard (SendInput), mouse clicks, virtual Xbox gamepad (ViGEmBus);
- **safety**: anti-cheat refusal, F12 takeover, DSH approval for real input, foreground-only input, optional audit log.

**The model decides how to play**: it looks at the screenshot, reads the OCR text, picks an action, then looks again.

## What it is for

A model decision takes 5–10 seconds, so the plugin **targets slow-paced games only**:

| Good fit | Out of scope |
|:--|:--|
| 2048, Minesweeper, Sudoku, card games, board games | action, platformers, bullet hell |
| visual novels, management sims, idle games | racing, FPS, fighting games |
| turn-based strategy / RPG, menu navigation | anything that needs sub-second reactions |

Real-time action games are out of scope; [STATUS](docs/STATUS.md) explains why.

## Tools

| Tool | Purpose |
|:--|:--|
| `game_selftest` | is the plugin installed, are the engine and backend ready |
| `game_windows` | list visible windows |
| `game_attach` | bind a game window (real backends need approval) |
| `game_snapshot` | screenshot + OCR text + foreground/occlusion info |
| `game_events` | cheap frame-diff events (static / changed / scene cut) |
| `game_controls` | key names the current backend accepts |
| `game_act` | press one key / gamepad button, or click the mouse |
| `game_plan` | a bounded local input loop (hold / tap / advance with wall escape) |
| `game_status` | binding, safety verdict, loop progress, audit tail |
| `game_stop` | stop everything, release inputs, detach |
| `game_state` | optional: generic visual WorldState ([STATE](docs/STATE.md)) |
| `game_memory` | optional: local game profile CRUD; **does not read game memory** |
| `game_policy` / `game_intent` | **frozen**: a 60 Hz local policy left over from the real-time track; no further work |

A typical game: `game_selftest` → `game_windows` → `game_attach` → loop `game_snapshot` → `game_act` → `game_stop`.

## Install

Each DSH profile is an independent plugin tree. Install into the wrong one and the `game_*` tools never appear.

| Host | How | Profile |
|:--|:--|:--|
| Desktop app (Electron) | **Settings → Plugins** in the app | `desktop` (the CLI cannot manage it) |
| `dsh web` | `dsh plugin --profile web add dsh-game-bridge` | `web` |
| `dsh headless` | `dsh plugin --profile headless add dsh-game-bridge` | `headless` |

Other sources: `file:<repo>` (local development), `github:nobu2333/dsh-game-bridge`.

- Requires DSH `>= 0.2.1-rc.2 < 0.3.0`, Node `>= 22`, and **`uv` on the machine**.
- **Restart the host after installing**, then call `game_selftest` once to confirm.
- On first activation the plugin uses `uv` to create a venv in the user cache and install the engine (about 20 s). Until the engine is ready, only the self-test tool is registered.
- The package has no install / postinstall scripts.

## Configuration (environment variables, read at host start; restart the host after changing them)

| Variable | Values |
|:--|:--|
| `DSH_GAME_BRIDGE_CONTROL` | `dry-run` (default) / `keyboard` (SendInput keyboard and mouse) / `vgamepad` (Xbox pad, needs ViGEmBus) |
| `DSH_GAME_BRIDGE_CAPTURE` | `screen` (default: grab the whole screen, crop to the window) / `window` (PrintWindow, works when the window is covered) |
| `DSH_GAME_BRIDGE_AUDIT_LOG` | path for the audit JSONL; unset means no audit log |
| `DSH_GAME_BRIDGE_PROFILE_DIR` | local profile directory |

**Approval**: real backends (`keyboard` / `vgamepad`) need a one-time DSH approval on `game_attach`.
Deployments with `approval: never`, and headless / CI with no one to approve, refuse outright.
This fail-closed behavior is intentional. Switch the preset to `ask`, or stay on dry-run.

## Safety promises

1. **Takeover at any time**: F12 latches output off, without going through the model; re-attach to clear it.
2. **No anti-cheat games**: if EAC / BattlEye / Vanguard / ACE or similar processes are running, all output is refused.
3. **No memory reading, no process injection**: screen capture and simulated input only.
4. **Real input needs approval** and only goes to the foreground window (otherwise the call fails with `FOREGROUND_MISMATCH`).
5. **Auditable**: with the audit log on, every attach / act / plan / stop and every refused attempt is written to a local JSONL file.

## Development

```powershell
npm test                                   # plugin contract tests
cd engine; python -m pytest tests -q       # engine unit tests
cd ..
$env:DSH_HOME='<repo>/.dsh-test'           # isolated DSH home
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # full integration (fake model, offline)
```

Current test counts and the date of the last run are in [STATUS](docs/STATUS.md). The release process is in [RELEASE](docs/RELEASE.md).

## License

MIT.

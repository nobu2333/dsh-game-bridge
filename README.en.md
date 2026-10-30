# dsh-game-bridge

**Give DeepSeek Harness eyes and hands on your games.**

> Status: **released 0.0.1** (npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`).
> **0.0.2 is packaged and installed locally (not published yet)**; publishing is pending.
> Verified end to end from the published artifact: install → engine bootstrap from PyPI →
> real screen capture + OCR → 20 Hz closed loop. Control is **dry-run by default**
> (it records actions instead of injecting input); real injection was verified on
> hardware on 2026-10-29 (gamepad A read back via XInput, keyboard W read back via
> AsyncKeyState), but a long 20 Hz loop has not yet been run on a real game. Windows only.

DSH has a brain (models, tools, sessions) but no eyes or hands: it can read files,
run commands and browse the web, yet it cannot see the game you are playing or press
a button. dsh-game-bridge plugs a thin plugin shell into DSH and backs it with a
local engine:

- **eyes** — screen capture (DXcam), frame differencing, OCR (RapidOCR), 20 Hz entity tracking (planned);
- **hands** — virtual gamepad (XInput via ViGEmBus), keyboard/mouse (planned);
- **cerebellum** — a local ~20 Hz closed loop; the model picks goals, not keystrokes;
- **safety** — takeover hotkey, anti-cheat refusal, local audit log.

## Why target-level tools, not per-step tools

A model tool call takes 3–5 seconds. Deciding "move right one step" through tool
calls makes the companion comatose in-game. Tools therefore expose goals only
(attach a window, look once, run one bounded loop, stop), while reflexes stay in the
local loop.

## Install (three hosts, three separate profiles)

A DSH profile is an independent plugin tree: install into the wrong profile and the
`game_*` tools never show up in a new session. Pick your host:

| Host | How | Profile | Notes |
|:--|:--|:--|:--|
| Desktop app (Electron) | **Settings → Plugins** inside the app | `desktop` (hard-wired) | the CLI cannot manage it: `dsh plugin --profile desktop ...` fails with `profile "desktop" is managed exclusively by the Electron application` |
| `dsh web` | `dsh plugin --profile web add dsh-game-bridge` | `web` | does not share plugins with the desktop app |
| `dsh headless` | `dsh plugin --profile headless add dsh-game-bridge` | `headless` | CI / no UI |

**Restart the host after installing** — plugins load at host startup. Quit and reopen the
desktop app, or restart the `dsh web` / `dsh headless` process, then call `game_selftest`
once to confirm the install (see "What `game_selftest` reports now").

Install sources (the commands below are for CLI profiles such as `web` / `headless`; the
desktop app picks its source in the in-app plugin panel):

```powershell
# registry (recommended after release)
dsh plugin --profile web add dsh-game-bridge
# local directory / tarball (development or offline)
dsh plugin --profile web add file:<repo>
# GitHub (the repo is public)
dsh plugin --profile web add github:nobu2333/dsh-game-bridge
```

- Requires DSH `>= 0.2.1-rc.2 < 0.3.0`, Node `>= 22`.
- On first activation the plugin installs its Python engine into a user cache
  (`uv venv` + `uv pip install dsh-game-core`); no system Python is required,
  but `uv` must be available.
- Platform: **Windows 10/11 only** for v1 (capture, virtual gamepad and input
  injection are Win32).
- No install/postinstall script and no second install step.

## Switching backends (`DSH_GAME_BRIDGE_CONTROL`)

| Value | Behaviour |
|:--|:--|
| unset / `dry-run` (default) | records actions, touches no device; capture/OCR/loop demos still work |
| `vgamepad` | virtual Xbox pad injected through XInput (needs the ViGEmBus driver) |
| `keyboard` | SendInput keyboard |

The backend is read **at host startup** (once when the plugin module loads, once when the
engine process starts); changing the environment mid-session has no effect. To switch:
set the variable, fully quit the host, restart it, then check `backend.name` and
`backend.ready` in `game_selftest`.

```powershell
# CLI (dsh web / dsh headless): set it in the launching shell
$env:DSH_GAME_BRIDGE_CONTROL='vgamepad'
dsh web

# Desktop app: persist a user environment variable, then restart the app (setx only
# affects processes started afterwards)
setx DSH_GAME_BRIDGE_CONTROL vgamepad
```

The `vgamepad` backend also needs the ViGEmBus driver and the `vgamepad` package in the
engine venv; the release bootstrap selects the `[gamepad]` extra for the chosen backend.
If the cached venv has no pip, install it with
`uv pip install --python <venv>\Scripts\python.exe vgamepad`.
The XInput slot (= player index) is reported in `game_attach` / `game_status` /
`game_selftest` output.

## Approval policy: why real backends get auto-rejected

`game_attach` with a real backend (`vgamepad` / `keyboard`) requires a one-shot **DSH
approval**. If the deployment's permission preset is `approval: never` (for example
`danger-full-access`), DSH automatically rejects every action that requires approval, so
`game_attach` fails instead of prompting.

Two workable options:

1. switch the permission preset to one that asks (`ask`), or run under a deployment that
   provides an approval responder — then approve attach once;
2. keep the `dry-run` backend: capture / OCR / loop demos need no approval at all.

Headless / CI hosts have no approver and fail closed the same way (as intended).

## What `game_selftest` reports now

Call it after restarting: it answers both "did I install it into the right place?" and
"is the selected backend usable?".

| Field | Meaning |
|:--|:--|
| text summary | plugin version / platform / engine status; contains `answered` when the engine ping succeeded |
| `install` | `package_dir`, `profile`, `profile_dir`, `dependency`, `source` (`registry` / `local-file` / `link` / `github` / `unknown`), `warnings` |
| `backend` | selected backend readiness: `name`, `ready`, `detail`, `xinput_slot`, `warnings` |
| `report` | raw engine self-test: dependency versions, monitors, OCR, foreground window (`foreground`), connected XInput slots, … |

- `source=local-file` with a dependency path under a temp directory (`/tmp/`, `\tmp\`,
  `/temp/`, `\temp/`) produces a warning: once the temp artifact is cleaned up the plugin
  will fail to load on the next host start — switch to a registry / github source;
- with `backend.name=vgamepad` it creates a virtual pad once and closes it (**no button is
  pressed**), reports whether creation worked and which XInput slot it landed on; a slot
  other than 0 (= player 2) triggers re-creation attempts and a `warnings` entry;
- when the engine or backend is not ready, tool results say so instead of pretending.

## Tools

| Tool | Meaning |
|:--|:--|
| `game_selftest` | Is the plugin loaded, where is it installed, and is the selected backend ready |
| `game_snapshot` | One frame as an image + OCR text, with foreground/occlusion metadata |
| `game_controls` | Button/key names accepted by the current backend |
| `game_windows` | List visible windows (title, process, size) |
| `game_events` | Cheap frame-difference event (baseline / static / changed / scene_cut) |
| `game_attach` | Attach to a window (the user-authorization step) |
| `game_act` | Press one gamepad button (dry-run by default; real backends refuse when the attached window is not foreground) |
| `game_plan` | Bounded local ~20 Hz loop (hold / tap / advance with stuck-detection sidestep) |
| `game_status` | Attach state, safety verdict, loop progress, audit tail |
| `game_stop` | Stop the loop, release everything, detach |

## Known limits (v1)

- **Capture is a full-monitor grab cropped to the window rectangle, not true window
  capture**: when another window covers the game, the snapshot shows the occluder. The
  `foreground` / `occluded` metadata flags it, but the pixels cannot bypass occlusion.
  True window capture (`PrintWindow(PW_RENDERFULLCONTENT)` / Windows Graphics Capture) is
  future work.
- **Real backends only deliver to the foreground window**: `game_act` refuses with
  `FOREGROUND_MISMATCH` and `game_plan` aborts when the attached window loses the
  foreground — no more silent "success" with no delivery.
- **The XInput slot is reported, not guaranteed**: the virtual pad can land on slot 1+
  (= player 2); the plugin retries up to 2 times and warns, but some games may still
  ignore non-zero slots.
- **`approval: never` deployments cannot use real backends**: attach is auto-rejected
  (see "Approval policy" above).
- **The new foreground/occlusion metadata and refusal logic are covered by unit and
  integration tests, but have not been re-verified on a real game yet** (the field
  evidence predates the fix).
- Windows only; multi-monitor edge cases and per-game threshold calibration are still
  open (see [docs/STATUS.md](docs/STATUS.md)).

## Safety commitments

1. **Always take back control** — a local F12 hotkey latches takeover without the model;
2. **No anti-cheat games** — EAC / BattlEye / Vanguard / ACE processes hard-block all output;
3. **Read-only default** — capture + gamepad only; no memory reading, no injection;
4. **Foreground check** — real backends verify the attached window is in the foreground
   before acting and refuse otherwise.

Unattended play is allowed by design: the "stop when nobody is at the keyboard" guard
inherited from the host project was removed on 2026-10-30 because it misfires for
gamepad players and is self-masked by injected keyboard input. Real output backends
still require a one-shot DSH approval, and F12 still takes control back.

## Development

See [README.md](README.md) (Chinese) for the full test matrix, engine self-check and
bootstrap verification, and [docs/DESIGN.md](docs/DESIGN.md) for the design decisions.

## License

MIT. See [LICENSE](LICENSE).


# v0.0.1

First public release of **dsh-game-bridge** — it gives DeepSeek Harness eyes and hands on games.

## What it does

A local Python engine does screen capture, OCR, frame differencing and a bounded
~20 Hz closed loop; the model only chooses targets:

- `game_selftest` / `game_snapshot` / `game_controls` / `game_windows` / `game_events`
- `game_attach` → `game_act` / `game_plan` (hold / tap / advance with stuck-detection sidestep)
- `game_status` / `game_stop`

Images travel through the harness attachment store (screenshots as image blocks),
not as base64 in the conversation text.

## Safety

- anti-cheat processes (EAC / BattlEye / Vanguard / ACE …) hard-block every output channel;
- no human input for a while (or no input telemetry) means output is refused;
- F12 latches a local takeover;
- real input backends require a one-shot DSH approval (`game_attach`);
- dry-run is the default; optional JSONL audit log.

## Hardware verification (2026-10-29)

- virtual gamepad inserted into XInput slot 0, A press read back via XInput (`True` → released `False`);
- `SendInput` W press read back via `GetAsyncKeyState` (`True` → released `True`);
- engine session-level actions on both backends report `dry_run=False`, safety `allowed=True`.

## Known limits

- **Windows only** (capture, virtual gamepad and input injection are Win32);
- the control backends **are** hardware-verified for single actions, but a long
  ~20 Hz loop has not been run on a real game yet;
- frame-diff thresholds and OCR regions are not calibrated per game;
- control is **dry-run by default** — set `DSH_GAME_BRIDGE_CONTROL=vgamepad|keyboard` to opt in.

## Install

```bash
dsh plugin --profile web add dsh-game-bridge
```

First activation installs the engine (`uv` required) from PyPI (`dsh-game-core`).

## Packages

- npm: `dsh-game-bridge@0.0.1`
- PyPI: `dsh-game-core==0.0.1`
- engine wheel / sdist attached below

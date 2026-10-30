# v0.0.2 (packaged locally, not published yet)

## Removed: the inherited "no unattended self-play" gate (2026-10-30)

- The engine no longer reads `GetLastInputInfo`; `DSH_GAME_BRIDGE_UNATTENDED_S` and
  the `safety.idle_seconds` field are gone.
- Rationale: the rule came from the host project's companion scenario and does not
  fit this plugin. Unattended play is the intended use; the gate misfired for human
  gamepad players and could be self-masked by injected keyboard input, so it was
  removed rather than patched.
- Anti-cheat refusal and the F12 takeover latch remain; real output backends still
  require a one-shot DSH approval.
- Version 0.0.2 is bumped in all four places (`package.json`, `lib/bootstrap.js`,
  `engine/pyproject.toml`, `engine/dsh_game_core/__init__.py`); publishing to npm/PyPI
  is still pending.

## Added: `game_selftest` readiness report (2026-10-30)

- `game_selftest` now returns, alongside the existing text summary:
  - `install`: `package_dir`, `profile`, `profile_dir`, `dependency`, `source`
    (`registry` / `local-file` / `link` / `github` / `unknown`, inferred from the profile's
    `package.json` dependency spec) and `warnings` (a `local-file` dependency under a temp
    directory warns because the artifact can be cleaned up and break the next host start);
  - `backend`: chosen backend readiness (`name`, `ready`, `detail`, `xinput_slot`,
    `warnings`); for `vgamepad` it creates a pad once and closes it without pressing any
    button (`probe_devices`);
  - `report`: the raw engine self-test result.
- The engine self-test now also reports `foreground` (current foreground window),
  `backend` (selected from `DSH_GAME_BRIDGE_CONTROL`), `xinput_slots_connected`, and
  always probes the `vgamepad` dependency.

## Added: foreground / occlusion metadata (2026-10-30)

- Capture is a full-monitor DXcam grab cropped to the window rectangle, so another window
  covering the game is what gets captured. The plugin now exposes that instead of hiding it:
  - `game_snapshot` returns `foreground` and `occluded` (`available`, `occluded_ratio`,
    `occluded`, `covered_by` top 3) and renders `Foreground: ...` plus a `⚠` warning when
    the attached window is not foreground or is occluded;
  - `game_attach`, `game_act`, `game_plan` and `game_status` also carry `foreground`;
    `game_act` carries `delivery`.
- Real backends (`vgamepad` / `keyboard`) now refuse `game_act` with
  `FOREGROUND_MISMATCH` when the attached window is not in the foreground, and
  `game_plan` aborts the loop when the foreground is lost. Attach runs a backend preflight
  and fails fast with `BACKEND_UNAVAILABLE` instead of failing at the first act.
- `vgamepad` controllers scan XInput slots 0–3 after creation, record `xinput_slot`, and
  retry pad creation up to twice when the slot is not 0 (warn, never raise just for that).
  `game_attach` / `game_status` / `game_selftest` report the slot and warnings.
- `session.stop()` / `close()` now release and close real controllers, so repeated
  attach/stop cycles do not accumulate ghost virtual gamepads.

## Docs (2026-10-30)

- README (zh + en): install matrix for the desktop app (Settings → Plugins, profile
  `desktop`, CLI cannot manage it), `dsh web` and `dsh headless`; restart the host after
  install; how to switch `DSH_GAME_BRIDGE_CONTROL` (requires a host restart); what to do
  when the deployment's approval policy is `never`; and what `game_selftest` reports.
- `docs/DESIGN.md` §3.5 corrected: capture is a full-monitor grab + window-rect crop, not
  true window capture; foreground/occlusion metadata is the low-cost signal; true window
  capture (PrintWindow / Windows Graphics Capture) is future work.
- `docs/STATUS.md` / `docs/CONTROLS.md` updated with the above; `docs/FIELD-2026-10-29.md`
  and its evidence package are now in the repo with local paths/usernames genericized
  (historical record; conclusions and evidence unchanged).
- npm package now ships `README.en.md`, `docs/STATUS.md` and `docs/CONTROLS.md`
  (the full docs tree and evidence images are intentionally not shipped).

Note: the new foreground/occlusion behavior and refusal paths are covered by unit and
integration tests, but have not been re-verified on a real game yet; the 2026-10-29 field
evidence predates the fix.

# v0.0.1

First public release of **dsh-game-bridge** — it gives DeepSeek Harness eyes and hands on games.

## Packaging (local, 2026-10-30)

- Built `dsh_game_core-0.0.2` wheel + sdist and `dsh-game-bridge-0.0.2.tgz` with
  `scripts/release.ps1`; the npm tarball ships 11 files including `README.en.md`,
  `docs/STATUS.md` and `docs/CONTROLS.md`.
- Installed the tarball into the desktop profile and verified it live: `game_selftest`
  reports plugin 0.0.2 / engine 0.0.2, `game_snapshot` flags a fully occluded target,
  and dry-run `attach → snapshot → act → plan → stop` works.
- The local install comes from a temporary tarball path, so `game_selftest` warns until
  the registry version is installed.

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

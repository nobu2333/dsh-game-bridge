# 交接（HANDOFF）

> 生成：2026-11-10 00:15；更新：2026-11-11 00:25
> 当前 goal：**complete**（`goal-3030a123-...`，revision 2）；没有 active goal。
> 新会话先读本文，再读 [GENERAL-PLUGIN-V3.md](GENERAL-PLUGIN-V3.md)、[RUN-STATE.md](RUN-STATE.md)、[STATUS.md](STATUS.md)。

## 一句话状态

`dsh-game-bridge` 已完成 v3 第一轮：**T1 4 个不同游戏 / 5 个 pack、T2 2**（按文档定义；T2 允许死亡/重开）。
**T1-auto=1**（Dino 零手写 pack，33.96s，0 interventions）；**strict T2=0**（现有 T2 有 restart/多棋盘）。
测试：引擎 **353**、插件 **45**；集成 11/11 是之前记录，未复跑。

## 证据

- T1：Cuphead、2048、Dinosaur Game、T-Rex（Dino 有 assisted + auto 两个 pack）
- T1-auto：`experiments/games/packs/web.dino.auto.t1.json`；报告 `experiments/results/auto-onboard-dino-2026-11-10.md`
- T2：本地 T-Rex（301.55s，score 53→89）、本地 2048（302.14s，340 actions，5 次 pack restart）；strict_t2 均为 false
- Pack：`experiments/games/packs/`
- 矩阵：`experiments/games/matrix.json`；coverage 去重按 `game_key`
- 运行记录：`docs/RUN-STATE.md` 顶部

## 本轮 P0/P1 已做

- P0：`evaluate.py` / `review.py` 的 `--game` / `--level` 改为必填，不再默认 Cuphead；
- P0：核心模块去掉游戏名（新增 `test_no_game_names.py`）；
- P0：`autoplay.py` 增加 5 分钟会话有效性检查（时长/stop phrase/actions/resets/progress）；
- T1-auto：`onboarding.py` + `scripts/auto_onboard.py`，Dino 自动推断 confirm/jump/方向并生成 `origin=auto` pack；
- coverage：区分 `t1_total`（不同游戏）与 `t1_packs`，Dino 的 assisted+auto 不再重复计为 2 个游戏；
- P1 切片：探针记录按键后 OCR + `menu_transition`，`infer_controls` 增加 `verified_confirm`。

## 你需要 review 的边界

1. **strict T2=0**：T-Rex 有死亡/重开，2048 有 5 次 New Game reset；不是“单局/单棋盘连续 5 分钟”。如果要求严格单局，T2 需要重做。
2. **T1-auto 目前只有 Dino**：第二款不同类型游戏还未自动 onboarding。
3. **Block Blast**：微信小游戏 WebGL 导出，点击报 `getGameDataMonitor`，未算 T1。
4. **SuperTux / FCEUX**：本次没有可用二进制；FCEUX 下载多次失败。
5. **Cuphead 10/7**：未做；按 v3 不是完成条件，仅 depth regression。

## 下一会话建议（P1/P2）

1. **T1-auto 泛化**：用同一套 `auto_onboard.py` 跑第二款不同类型游戏（平台/益智/动作），记录 interventions=0。
2. **strict T2**：选一个不依赖 restart 的目标，跑单局/单棋盘连续 5 分钟；修 `play_pack` 的分数停滞检测。
3. **扩覆盖**：5+ 不同 T1（策略/回合/3D/模拟器），3 款 T2；优先本地合法游戏。
4. **产品化**：GamePack schema v1、集成测试、0.0.2 发布、marketplace 文档。

## 常用命令

```powershell
# 引擎测试
cd E:\dsh-game-bridge\engine
$env:PYTHONPATH='E:\dsh-game-bridge\engine'
.\.venv\Scripts\python.exe -m pytest tests -q

# 插件测试
cd E:\dsh-game-bridge
npm test

# 探针（窗口级抓屏）
python scripts\probe_game.py --window "<title>" --window-capture --keys "ENTER,SPACE,UP,DOWN"

# 5 分钟 autoplay
python scripts\play_pack.py --pack experiments\games\packs\<pack>.json --duration 300
```

## 注意

- 真实输入前确认窗口前台；`force_foreground` 可用但不保证所有窗口；
- `PrintWindow` 对部分硬件加速窗口可能黑帧，先检查帧方差；
- 游戏资源/ROM/录像只在本地，不入库；
- 不要恢复 Cuphead 10/7 参数扫描，除非用户明确要求单独开 depth goal。

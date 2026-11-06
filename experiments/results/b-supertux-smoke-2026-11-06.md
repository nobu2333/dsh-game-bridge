# B 轨 SuperTux 泛化烟测报告（2026-11-06）

## 结论

**B 烟测通过（有明确 caveat）**：零引擎改动下完成 attach、抓屏/OCR、键盘/鼠标控制、进入关卡、首次动作、`game_id=supertux` LevelMemory 加载/隔离，并生成 traces/health 记录。

不要求通关；本报告不改变 Cuphead A 轨结论。

## 环境

- Windows x64 SuperTux 0.7.0 portable：`F:\SuperTux-portable`；
- 窗口：`SuperTux v0.7.0`，1280×831；
- 本地 driver：`tmp/play_server.py`，127.0.0.1:47655；
- profile：`profiles/supertux.json`（方向键 / Space / Ctrl / Shift / Enter；`player.track=false`）。

## 验收结果

| 项 | 结果 | 证据 |
|:--|:--|:--|
| 窗口启动/attach | ✅ | attach 成功，截图/OCR 正常 |
| 抓屏/OCR 菜单 | ✅ | 主菜单/暂停菜单/世界地图 OCR |
| 键盘控制 | ✅（需激活） | `AppActivate` 后 ESC 打开暂停菜单；直接按住 RIGHT 后镜头/敌人位置变化 |
| 鼠标控制 | ✅ | 点“否”关联网弹窗、点“开始游戏” |
| 进入关卡 | ✅（人工辅助） | 用户手动进入 gameplay；画面有金币/敌人/关卡 HUD |
| 首次有效动作 | ✅ | policy 运行 actions=17，31.8Hz；attach→首次动作 **3.1s** |
| LevelMemory 加载 | ✅ | `memory_context`: `scope=level, game=supertux, level=frosted-fields` |
| LevelMemory 隔离 | ✅ | 切换到 `other-level` 后 context 只显示 other-level，不串 frosted-fields |
| trace/health 留痕 | ✅ | `b-supertux-smoke` 单局 18 条 trace；自动报告 `experiments/results/b-supertux-smoke.md` |
| 引擎游戏专用分支 | ✅ 无 | 只新增 `profiles/supertux.json`；引擎通用 |
| 安全闸 | ✅ | 未绕过；无真实反作弊 |

## 产物

- 单局账本：`tmp/experiments/b-supertux-smoke.jsonl`（本地）；
- 轨迹：`tmp/experiments/traces/b-supertux-smoke/b-supertux-smoke-01.jsonl`（18 条）；
- 自动报告：`experiments/results/b-supertux-smoke.md`；
- 本地 memory：`%LOCALAPPDATA%\dsh-game-bridge\memory\games\supertux\levels\frosted-fields.json`、`other-level.json`；
- Cuphead memory 文件时间戳未更新（未污染）。

## Caveat（必须保留）

1. **time_to_controls 的口径**：3.1s 是 **driver attach → policy 首次 action**；完整“游戏启动→可操作”包含人工过剧情，不是 3.1s，也不能宣称全自动冷启动 ≤5 分钟。
2. **scene 分类**：SuperTux gameplay 被 OCR 分类为 `loading`/`dialogue`，`peak_screens` 为 0；这影响指标，不影响 attach/控制/记忆验证。
3. **玩家追踪**：`player.track=false`，`player_stale_ratio=1.0` 是预期（未配置 SuperTux 玩家外观）；不是感知修复回退。
4. 本次只做烟测，没有通关，也没有对 Cuphead A 轨做任何结论修改。

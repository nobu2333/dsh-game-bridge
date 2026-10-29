# 控制表（CONTROLS）

> 模型先调 `game_controls` 拿到「当前后端真实支持的按键名」，再调 `game_act` /
> `game_plan`。不要凭记忆猜键名——后端会拒绝未知键。

## 后端与适用场景

| 后端 | 开启方式 | 适合 |
|:--|:--|:--|
| `dry-run`（默认） | 不设 `DSH_GAME_BRIDGE_CONTROL` | 演练、看画面、验证链路；不碰设备 |
| `vgamepad` | `DSH_GAME_BRIDGE_CONTROL=vgamepad` | 原生支持手柄的 3D/横版/合作游戏（市场主流） |
| `keyboard` | `DSH_GAME_BRIDGE_CONTROL=keyboard` | 只吃键鼠的独立游戏、老游戏、模拟器 |

非 dry-run 后端在 `game_attach` 时会要求 DSH 一次性审批；headless/CI 无应答者时
fail-closed 拒绝。

## 手柄按钮（vgamepad）

`A` `B` `X` `Y` `START` `BACK` `LB` `RB`
`DPAD_UP` `DPAD_DOWN` `DPAD_LEFT` `DPAD_RIGHT`

`game_plan` 的方向类原语（`advance`）只对 `DPAD_*` 做撞墙侧移。

## 键盘按键（keyboard）

字母：`W` `A` `S` `D` `Q` `E` `F` `R`
功能：`SPACE` `ENTER` `ESC` `TAB` `SHIFT` `CTRL` `ALT`
方向：`UP` `DOWN` `LEFT` `RIGHT`
数字：`1` `2` `3` `4`

## 按游戏类型的建议

| 游戏类型 | 推荐后端 | 典型用法 |
|:--|:--|:--|
| 3D 动作 / 开放世界 | `vgamepad` | `advance` 走位 + `A` 交互；`events` 判断是否撞墙 |
| 2D 横版平台 | `vgamepad` | `DPAD_RIGHT` + `A` 跳；静止即卡住 |
| 俯视合作（胡闹厨房类） | `vgamepad` | 面向目标 `advance`，到台面 `A` |
| 弹幕生存（土豆兄弟类） | `vgamepad` | 方向 `advance` 绕场；`events` 感知危险帧 |
| 只吃键盘的老游戏/模拟器 | `keyboard` | `advance` 用 `RIGHT`；交互 `SPACE`/`ENTER` |
| 纯观看/解说 | `dry-run` | 只用 `game_snapshot` / `game_events`，不操作 |

## 一个典型回合

```
game_controls                       → 当前后端支持哪些键
game_windows                        → 找到目标窗口
game_attach {window: "<标题子串>"}   → 绑定（真实后端需批准）
game_snapshot                       → 看一眼（图 + OCR）
game_plan {mode:"advance", button:"DPAD_RIGHT", duration_ms:1500}
game_status                         → ticks/hz/escapes
game_stop                           → 松手、解绑
```

## 边界

- 每拍都过安全闸（反作弊 / 无人 / F12），任何一条命中立即松手；
- `game_plan` 有上限（最长 120s），不是挂机脚本；
- 真实注入已于 2026-10-29 实机回读验证（手柄 A + XInput、键盘 W + AsyncKeyState）；长闭环尚未在真实游戏里跑。


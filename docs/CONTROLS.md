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
fail-closed 拒绝。权限预设是 `approval: never`（如 `danger-full-access`）的部署会对
需要审批的动作**一律自动拒绝**——要么把预设切成会询问的（`ask`），要么保持 dry-run。

后端在**宿主启动时**读取 `DSH_GAME_BRIDGE_CONTROL`，会话中途改环境变量不生效；
切换后必须完全重启宿主，再用 `game_selftest` 的 `backend` 字段确认 `name` /
`ready` / `xinput_slot` / `warnings`。

## 手柄按钮（vgamepad）

`A` `B` `X` `Y` `START` `BACK` `LB` `RB`
`DPAD_UP` `DPAD_DOWN` `DPAD_LEFT` `DPAD_RIGHT`

`game_plan` 的方向类原语（`advance`）只对 `DPAD_*` 做撞墙侧移。

**XInput 槽位 = 玩家序号**：插件创建虚拟手柄后会扫描 0–3 槽位并记录实际落点；
不是 0（= 玩家 2）时会尝试重建最多 2 次，并在 `game_attach` / `game_status` /
`game_selftest` 的 `warnings` 里说明。有些游戏只认 1P（slot 0），这是已知限制，
不是重试一定能解决的问题。

## 键盘按键（keyboard）

字母：`W` `A` `S` `D` `Q` `E` `F` `R`
功能：`SPACE` `ENTER` `ESC` `TAB` `SHIFT` `CTRL` `ALT`
方向：`UP` `DOWN` `LEFT` `RIGHT`
数字：`1` `2` `3` `4`

## 前台与遮挡（真实后端必读）

真实后端（`vgamepad` / `keyboard`）的输入**只对前台窗口生效**：

- `game_attach` 返回 `foreground`（当前前台窗口的 `hwnd` / `title` / 进程；与
  `attached.hwnd` 对比即可知道目标是否在前台）；
- `game_act` 在 attached 窗口不在前台时直接拒绝（`FOREGROUND_MISMATCH`），
  并在 `delivery` 里说明投递状态——不再出现「返回成功但游戏没收到」；
- `game_plan` 逐拍检查，前台丢失即中止并把原因写进 `stop_reason`；
- `game_snapshot` 返回 `foreground` / `occluded`（`occluded_ratio` + `covered_by`），
  遮挡比例 ≥ 0.5 或不在前台时文本里打 `⚠`。注意抓屏是「整屏 grab + 窗口矩形裁剪」：
  被别的窗口盖住时画面就是遮盖物，元数据只是把这件事显式化（真窗口抓屏是后续工作，
  见 DESIGN §3.5）。

插件不会自己抢焦点：需要游戏回到前台时，先由用户把游戏切到前台，再调用 act / plan。

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
game_selftest                       → 装对 profile 没有？后端就绪？XInput 槽位？
game_controls                       → 当前后端支持哪些键
game_windows                        → 找到目标窗口
game_attach {window: "<标题子串>"}   → 绑定（真实后端需批准；返回 foreground）
game_snapshot                       → 看一眼（图 + OCR + foreground/occluded）
game_plan {mode:"advance", button:"DPAD_RIGHT", duration_ms:1500}
game_status                         → ticks/hz/escapes + 前台/槽位
game_stop                           → 松手、解绑
```

## 边界

- 每拍都过安全闸（反作弊 / F12），任何一条命中立即松手；
- 真实后端还要求 attached 窗口在前台：不在前台时 `game_act` 拒绝、`game_plan` 中止；
- `game_plan` 有上限（最长 120s），不是挂机脚本；
- 真实注入已于 2026-10-29 实机回读验证（手柄 A + XInput、键盘 W + AsyncKeyState）；
  新的前台/遮挡元数据与拒绝逻辑已有单测/集成覆盖，但尚未在真实游戏里复验；
- 抓屏是整屏抓 + 窗口矩形裁剪，不是真正的窗口级抓屏；遮挡/前台状态以
  `game_snapshot` 的元数据为准。


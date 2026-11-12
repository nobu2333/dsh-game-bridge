# 控制表（CONTROLS）

> 模型先调 `game_controls` 拿到「当前后端真实支持的按键名」，再调 `game_act` /
> `game_plan`。不要凭记忆猜键名——后端会拒绝未知键。

## 后端与适用场景

| 后端 | 开启方式 | 适合 |
|:--|:--|:--|
| `dry-run`（默认） | 不设 `DSH_GAME_BRIDGE_CONTROL` | 演练、看画面、验证链路；不碰设备 |
| `keyboard` | `DSH_GAME_BRIDGE_CONTROL=keyboard` | 键鼠操作的游戏：浏览器小游戏、益智、回合制、视觉小说（本项目主力） |
| `vgamepad` | `DSH_GAME_BRIDGE_CONTROL=vgamepad` | 只认手柄的游戏（需要 ViGEmBus） |

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

字母：`A`–`Z`
数字：`0`–`9`
功能：`SPACE` `ENTER` `ESC` `TAB` `SHIFT` `CTRL` `ALT`
方向：`UP` `DOWN` `LEFT` `RIGHT`

大小写不敏感。以 `game_controls` 的返回为准（来源：`engine/dsh_game_core/control.py` 的 `VK_CODES`）。

## 鼠标点击（keyboard 后端）

`game_act {x, y, mouse_button}`：`mouse_button` 取 `LEFT`（默认）/ `RIGHT` / `MIDDLE`。

**注意：`x` / `y` 目前是屏幕绝对坐标**，不是截图里的坐标。`game_snapshot` 的画面经过窗口裁剪，
可能还缩放过，模型不能直接用截图像素去点。改成相对截图的坐标，是点击类游戏的前置缺口（见 [STATUS](STATUS.md)「下一步」第 3 项）；2048 这类只用方向键的游戏不受影响。

## 前台与遮挡（真实后端必读）

真实后端（`vgamepad` / `keyboard`）的输入**只对前台窗口生效**：

- `game_attach` 返回 `foreground`（当前前台窗口的 `hwnd` / `title` / 进程；与
  `attached.hwnd` 对比即可知道目标是否在前台）；
- `game_act` 在 attached 窗口不在前台时直接拒绝（`FOREGROUND_MISMATCH`），
  并在 `delivery` 里说明投递状态——不再出现「返回成功但游戏没收到」；
- `game_plan` 逐拍检查，前台丢失即中止并把原因写进 `stop_reason`；
- `game_snapshot` 返回 `foreground` / `occluded`（`occluded_ratio` + `covered_by`），
  遮挡比例 ≥ 0.5 或不在前台时文本里打 `⚠`。默认抓屏是「整屏 grab + 窗口矩形裁剪」：
  被别的窗口盖住时画面就是遮盖物；设 `DSH_GAME_BRIDGE_CAPTURE=window` 改用 PrintWindow
  窗口级抓屏可以绕开遮挡（部分游戏会黑帧，见 DESIGN §3.5）。

插件不会自己抢焦点：需要游戏回到前台时，先由用户把游戏切到前台，再调用 act / plan。

## 按游戏类型的建议

| 游戏类型 | 推荐后端 | 典型用法 |
|:--|:--|:--|
| 方向键益智（2048 类） | `keyboard` | 每步 `game_snapshot` 看棋盘，`game_act` 按 `UP`/`DOWN`/`LEFT`/`RIGHT` |
| 点击类益智（扫雷、纸牌） | `keyboard` | `game_act {x, y}` 点击（注意坐标限制，见上文） |
| 视觉小说 / 菜单 | `keyboard` | OCR 读选项，`ENTER`/`SPACE` 推进，方向键选择 |
| 回合制策略 / RPG | `keyboard` 或 `vgamepad` | 每回合看一眼再操作；长按移动可以用 `game_plan hold` |
| 纯观看 / 解说 | `dry-run` | 只用 `game_snapshot` / `game_events`，不操作 |

实时动作游戏不在本项目范围内（见 [STATUS](STATUS.md)）。

## 一个典型回合

```
game_selftest                       → 装对 profile 没有？后端就绪？XInput 槽位？
game_controls                       → 当前后端支持哪些键
game_windows                        → 找到目标窗口
game_attach {window: "<标题子串>"}   → 绑定（真实后端需批准；返回 foreground）
game_snapshot                       → 看一眼（图 + OCR + foreground/occluded）
game_act {button:"RIGHT"}           → 走一步
game_snapshot                       → 看结果，决定下一步（循环）
game_stop                           → 松手、解绑
```

## 边界

- 每拍都过安全闸（反作弊 / F12），任何一条命中立即松手；
- 真实后端还要求 attached 窗口在前台：不在前台时 `game_act` 拒绝、`game_plan` 中止；
- `game_plan` 有上限（最长 120s），不是挂机脚本；
- 真实注入已于 2026-10-29 实机回读验证（手柄 A + XInput、键盘 W + AsyncKeyState）；
  前台/遮挡元数据与拒绝逻辑有单测/集成覆盖；
- 默认抓屏是整屏抓 + 窗口矩形裁剪，窗口级抓屏需要设 `DSH_GAME_BRIDGE_CAPTURE=window`；
  遮挡/前台状态以 `game_snapshot` 的元数据为准。


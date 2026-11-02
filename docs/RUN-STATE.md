# RUN STATE（本地续跑笔记，不入库）

> 作用：上下文被压缩/会话中断后，先读这份文件恢复状态。
> 最后更新：2026-11-02 21:50（顶部为当前判断；下面是按时间追加的续跑记录）

## 当前判断（2026-11-02 整理）

> 结论：**通关卡点是 L1 执行，不是 L3 决策；决策时间卡的是「主模型进 1–2Hz 战术环」这条路线。** 这两件事要分开。

1. **通关卡点：Forest Follies 约 6.4 屏的平台/障碍段。** 10-30 实机最好 6.401 屏；11-02 模型 intent 实验最好 6.158 屏；都停在坑/双层平台/木桩-花妖-红蘑菇组合区。现有 L1 的跳/冲刺/gap/ledge/route macro 还不能稳定通过该段，需要针对该段的 episode 复盘和落点/路线技能。
2. **决策时间：9.12s / 8.93s，p95≈9s，TTL 2.5–3s。** 按 30–60Hz 算，一次决策覆盖 270–540 帧；Cuphead 的跳跃/弹幕窗口是 0.2–0.5s，9s 慢约 20–45 倍。主模型可以做 10s 级姿态/策略/复盘，不能做逐跳/逐弹幕，也不适合 1–2Hz 的 L3 环。
3. **当前决策：**
   - 通关优先：补 L1 平台段技能与该段 episode 复盘，不把主模型放进快环；
   - L3：事件驱动（卡住/死亡/低置信才问模型），或用更快的 L3（小模型/子 agent）；主模型 9s 不做 1–2Hz；
   - 先验收 L2 准确率和 A/B，再扩大模型环。
4. **仍未通关；README 不能写「已通关」。**

## Goal

- id: `goal-283c1ac6-f742-4469-b1ae-5b4968ae946b`
- revision: 7（objective 已改成文档版，max rounds 80）
- **phase: paused / disarmed** —— 模型不能自行 resume，需要用户在 DSH 界面点一次「恢复 goal」。
- 若 goal 未恢复，自动轮次不会继续；下一次用户消息后需手动继续。

## 目标摘要

按 `docs/PROJECT-STRATEGY.md` 完成「看/玩/学」：
- P0：稳定≥40Hz、有卡/无卡 A/B 统计、坐标漂移<0.2；
- P1：对象级理解（ID+外观签名+角色 chaser/harmful/projectile+聚类）、chaser 优先 + turn_and_shoot、静态危险物、技能库/仲裁器、战术姿态、地图入口导航；
- P2：game_review 工具化、参数 preset、可选攻略、副本游戏矩阵、通关稳定性；
- 最终验收：Cuphead Forest Follies 从大地图 10 局≥7 通关 + 可复现 A/B 证据；引擎无游戏专用代码。

## 当前进度（2026-11-02）

- HEAD: `d509cb8`；测试：引擎 **242**、插件 **45**、集成 11/11（本地实测）。
- 目标未变：Forest Follies 从大地图 10 局 ≥7 通关；**仍未通关**。
- 实机最好进度：10-30 **6.401 屏**；11-02 模型 intent 最后 **6.158 屏**；卡点仍是 6.4 屏平台段。
- 架构：L1 反射 + L2 SituationReport + L3 Intent/arbiter；冷启动/Instant Play 已接线；主模型决策 p95≈9s，不能进 1–2Hz。
- 工具面已补 `game_intent`（stdio `submit_intent` + 插件工具）：默认 advisory，执行还需 `profile.instant_play.intent_enabled=true`。
- L2 准确率：10 点采样中 3 个 stale 正确、7 个 gameplay 位置与截图一致；仍有人工核对缺口。
- goal：paused，需要用户在 DSH 界面恢复。

### 历史进度（2026-10-30，提交 `8e4d8fa`）

- 帧率：分阶段计时已接入；样本 grab 5.3ms / entities 4.2 / player 2.6 / memory 1.3；单次样本 **41.6Hz**，另一次 44Hz；仍会波动，目标稳定 ≥40。
- 玩家追踪：每 8 拍一次 + 颜色校验；Cuphead profile `face_back=false`、`engage_max_ms=2500`。
- 坐标漂移：卡片链式合并修复后 `cards=2 mean=0.089 max=0.100 <= 0.2`。
- DangerCard：结果回写/换技能阶梯已实机验证；A/B 只有单对样本（knowledge off -0.087 屏 / on -2.295 屏），样本不足。
- 卡账本：约 22 张；response tries 9 / avoided 4 / failures 5（avoid_rate 0.444），mean efficacy ~0.496。
- 录制：异步录制线程；episode 有 meta/events/frames。
- 已知问题（当时）：匿名运动簇、face_back 关闭、静态危险物漏检、A/B 无跑批、帧率波动、地图入口无导航。

## 后续计划建议（2026-11-02）

> 原则：先拿证据，再改执行；先通关，再扩模型环；不把主模型放进快环。

### P0 先拿到「为什么过不去」的证据（1–2 天）

1. 恢复 goal；清理残留 driver；用当前 HEAD 跑 10 局 baseline（record=true, game=cuphead, level=forest-follies）。
2. 对 6.4 屏附近的 episode 做 review：把死亡分类为坠落 / 蘑菇 / 花妖弹幕 / 跳早 / 跳晚 / 其他，统计每类次数。
3. 固定指标：clear rate、best progress、damage/run、death location、hz、time-to-control。
4. 决策延迟 A/B：同一批 20 个 SituationReport，比较 `deepseek-flash + max`（当前主会话）、`deepseek-flash + off/low`（直接 LLM 调用，最小 prompt，maxTokens≤128）、可选本地小模型；记录 p50/p95 与 intent 正确率。p95 > 1s 就不做 1–2Hz 模型环。
5. 同步 STATUS/README 的当前状态（或明确指向本文件）。

### P1 打通 6.4 屏（2–4 天）

1. 用 episode 证据补 L1 平台技能：retreat-align、jump-to-landing、apex dash、ledge/gap with target x；全部走 profile 参数化。
2. 用 profile `macros` 做该段的确定性路线（scroll_s 触发 + 分步 hold/tap），先拿 first clear；不写进引擎。
3. 10 局 A/B：baseline vs route；≥7/10 过 6.4，再冲 full clear。
4. 如果 route 仍不过，回到 episode 找具体帧，不继续全局参数扫描。

### P2 稳定通关 + 从地图出发（3–5 天）

1. 10–20 局 full runs；修 top 3 death causes；每改一项做 A/B。
2. 地图入口：profile 航点/宏，或改进 walk-until-affordance；验收从大地图 10 局 ≥7 通关。
3. L2 准确率 10 点人工核对；A/B 证据留本地，不提交录像/账本。

### P3 模型 L3（可与 P1/P2 并行，但不阻塞）

1. 主模型只做事件驱动（卡住/死亡/低置信），TTL 5–10s 的姿态/路线建议；不做 1–2Hz。
2. 若要实时 L3，单独接一个快速 L3（直接 `ctx.llm` 调用或本地小模型，不复用主会话/完整 agent loop）；先测 p95 < 1s（含解析/提交）再接线。
3. 验收：模型介入提升 clear rate / 降低 damage，且不增加卡死。

### 不建议做

- 不要用调 TTL/伪造新鲜度来迁就 9s 模型；
- 不要在 6.4 屏打通前继续堆感知/对象记忆特性；
- 不要把 Cuphead 专用逻辑写进引擎；路线宏只能放 profile；
- 不要在 10 局 ≥7 通关前写「已通关」。

## 运行环境/命令

- 仓库：`<repo>`
- 引擎缓存：`%LOCALAPPDATA%\dsh-game-bridge\engine\0.0.2`
- 本地 profile：`%LOCALAPPDATA%\dsh-game-bridge\profiles\cuphead.json`
- 知识/录像：`%LOCALAPPDATA%\dsh-game-bridge\knowledge`、`...\episodes`
- 驱动：`tmp\play_server.py`（端口 47655，键盘后端）；`tmp\play_ctl.py`
- **注意**：启动新 driver 前先杀掉所有残留 `play_server.py` python 进程，否则旧代码/端口占用会造成假象。
- 测试：
  - `tmp/dev-venv/Scripts/python.exe -m pytest engine/tests -q`
  - `npm test`
  - 评测：`$env:PYTHONPATH='<repo>\engine'; python -m dsh_game_core.evaluate --game cuphead --level forest-follies`
  - 复盘：`python -m dsh_game_core.review <episode 路径>`

## 安全

- 真实输入前确认用户已交还电脑；结束/暂停立即 `policy_stop` + `close`，并杀掉 driver 进程。
- F12 夺回、反作弊检查保持启用。
- 公共仓库不要提交本地 profile/模板/录像/账本/本机路径。

## 2026-10-30 20:08 夜间自主运行记录

- 用户授权长时间自主游玩；policy 已保持运行（driver 端口 47655），当前 scene=death，自动重试中。
- 当前 rush 调参（cache profile，仅本地）：engage_radius=0.0, jump_every_ms=550, turn_and_shoot=false；repo profile 仍是 engage 0.2 / jump 0 / turn_and_shoot true。
- 当前进度：ticks ~6358, hz ~33.7, scroll_s ~-2.4（死亡后重置，不代表总进度）。
- 仍 **未通关**；README 不能写「茶杯头已通关」。
- 下一轮检查：state/OCR 是否出现 LEVEL COMPLETE / KNOCKOUT；若有，立即写 README 并提交；若仍死亡循环，改回 repo 参数或继续调参。
- 注意：如果 driver 进程被系统清理，重新启动前先杀掉所有 play_server.py 残留进程。

## 2026-10-30 20:29 进展

- 已实现并提交：对象级理解（role/cluster）、turn_and_shoot 短点转身、death/equip 恢复预算（40/10）、静态危险物颜色检测 + 跳跃反射。
- 最新提交：`72270ec`（静态危险物）；测试 197 engine / 44 plugin。
- 实机累计：212 episodes；best progress 6.401 screens；response tries 118 avoided 84 failures 39（avoid_rate 0.712）；frame ~34Hz。
- 仍 **未通关**，README 未写。
- 当前死亡卡点：约 6.4 屏处（木桩/花妖/红蘑菇组合区域）；策略能打一段但过不去。
- 已停止策略/驱动/按键。
- 下一步想法：
  1. 针对 6.4 屏区域人工/回放分析（episode 帧），做专用 DangerCard + 时机；
  2. 战斗中“先清场再推进”的战术仲裁；
  3. 静态危险物颜色范围需要按截图校准（红蘑菇 vs 花/角色红 shorts）；
  4. A/B 跑批仍未完成。

## 2026-10-30 20:35 更新

- 静态危险物检测已在真实死亡帧验证：能检测到 red_mushroom（x≈0.648,y≈0.572,area 37）。
- 多种 profile（rush、periodic jump、no-jump、turn/static）仍卡在 best progress 6.401 screens；累计 231 episodes，avoid_rate ~0.699。
- 结论：6.4 屏处是当前硬卡点，需要针对该区域做专用清场/跳跃策略或回放级分析。
- 已停止策略/驱动/按键；README 未写（未通关）。

## 2026-10-30 20:43

- turn_and_shoot 扩展到 harmful/behind 簇；仍卡 best 6.401。
- 多组参数（静态危险物、周期跳、rush、清场/转身）都无法通过 6.4 屏；累计 233 episodes，avoid ~0.696。
- 结论：需要针对该段的专用战术/路线，不是全局参数能解决。
- 已停止驱动/按键；README 未写。

## 2026-10-30 20:47

- 手动宏实验：RIGHT+X + 周期跳可活 100s（HP1），但坑/双层平台段过不去；
- 跳跃+冲刺组合 60s 内死亡；
- 手动短步尝试：从坑里左移可回到低台，但右跳上高台失败并死亡；
- 结论：该段需要精确平台路线（低台→高台），宏/周期跳无法通过；best 仍 6.401。
- 已停止驱动/按键；README 未写。

## 2026-10-30 20:53 世界地图/Boss 尝试

- 从 Forest Follies 退到地图，尝试找 Botanic Panic（首个 Boss）的 signpost。
- 左侧商店附近 signpost 仍是 Forest Follies；右侧河对岸有一个 signpost，但当前没有走到/进入。
- 地图导航仍是薄弱点（walk-until-affordance 未完成）。
- 未通关；README 未写。已停止驱动/按键。

## 2026-10-30 20:55 地图探索

- 地图右侧河对岸有 signpost；从下方走到上层崖，仍被河隔开，未找到过桥路径。
- 右上方有建筑（可能是 Mausoleum/其他），未进入。
- 未通关；README 未写；驱动已停。

## 2026-10-30 21:00

- 实现并提交 walk-until-affordance（ee6cbb4）；地图测试：按住 RIGHT 30s 没有碰到 prompt 图标，走到地图上边缘；单一方向不够，需要路径/方向切换。
- 未通关；README 未写；驱动已停。

## 2026-10-30 21:07

- A/B 分组基础设施完成（feea465）；但实机 A/B 跑在地图（未进关），episodes 无有效战斗数据。
- 地图：右侧 cake 建筑（疑似 Botanic Panic）与当前悬崖隔河，未找到过桥路径；Mausoleum 建筑可见。
- 仍未通关；README 未写；驱动已停。

## 2026-10-30 21:02

- 地图右侧仍被河隔开；cake/帐篷建筑看得见但走不到，猜是后续关卡/其他入口。
- 未通关；README 未写；驱动已停。
- 下一步：不要继续盲走地图，先做“可站立边缘/过桥”视觉检测，或用 map 截图人工标航点。

## 2026-10-30 21:10 关卡内 A/B（首批有效）

- knowledge off: episodes 6, damage 3 (0.5/ep), best progress 4.005
- knowledge on:  episodes 4, damage 1 (0.25/ep), best progress 1.708
- 样本小；on 组受击更少但推进更短（可能因为停步/恢复）。不能下结论，但 A/B 管道已通。
- 仍未通关；README 未写；驱动已停。

## 2026-10-30 21:14 A/B 第二批

- knowledge off: episodes 9, damage 4 (0.44/ep), best progress 4.005
- knowledge on:  episodes 7, damage 2 (0.29/ep), best progress 1.708
- 两批趋势一致：on 受击更少，但推进更短（保守/停步）。
- 仍未通关；README 未写；驱动已停。

## 2026-10-30 21:14 A/B 收敛

- knowledge on (only DangerCards, turn/static off): 10 episodes, damage 2 (0.20/ep), progress 3.87
- knowledge off: 9 episodes, damage 4 (0.44/ep), progress 4.005
- profile 已固化：entity_memory=true, turn_and_shoot=false, static_hazards=false。
- 仍未通关（平台段/地图入口）；README 未写。
- 下一步优先级：平台段专用 macro/ledge 导航 > 扩大 A/B > 通关验收。

## 2026-10-30 21:22 路线宏实验

- 实现 route macro（e4da297，200 tests）；在 cache profile 设了坑附近宏（左移→右跳→再右跳），实机 120s。
- 结果 best progress 仍 6.401，宏未突破；可能触发坐标/时机不对，或宏本身不匹配平台。
- 仍在坑段；README 未写；驱动已停。

## 2026-10-30 21:28

- 新增 ground-gap 探测 + 跳跃反射（b0d22cd）；route macro 机制已提交（e4da297）。
- 尚未实机验证 gap 效果；平台段仍未有通关证据。
- 测试 201 engine / 44 plugin；README 未写。

## 2026-10-30 21:30 状态：仍卡平台段

- gap 检测实机 120s：best progress 仍 6.401；未突破。
- 累计 278 episodes；avoid_rate 0.773。
- 连续多轮（约 20+）同一卡点：Forest Follies 平台段（木桩/双层平台）+ 地图 Boss 入口过河。
- 当前视觉只有颜色/亮度启发式，缺平台边缘/落点建模；宏/手动/gap 都未通过。
- README 未写。

## 2026-10-30 21:35 轮次 40

- 本轮未继续盲试；确认工作区干净、无 driver/按键。
- 连续多轮同一卡点：Forest Follies 平台段（6.401）与 Boss 入口过河；现有颜色/亮度启发式不足。
- 需要的下一步是 ledge segmentation/人工标定，而不是继续调参或宏。
- 未通关；README 未写；goal 保持 active。

## 2026-10-30 21:40 地形标定

- 从真实死亡帧采样地面颜色（BGR 约 [98,158,148] / [81,101,89] 等），准备用于 terrain.ground_colors。
- 地面与灌木颜色接近，直接全屏分割会误判；需要限定下半区或按边缘筛选，暂未启用 ledge_jump（避免误跳）。
- 未通关；README 未写。

## 2026-11-02 11:26 冷启动进展

- game_probe：引擎/配置/键位扫描（Unity/Unreal/Godot/GameMaker），Cuphead 识别为 Unity，但无 InputManager.ini 键位，需要 probe/web 兜底。
- controls_probe：候选键调度 + 画面变化判定。
- coldstart：file/web/probe/prior 合并，带 conflicts/alternatives；CLI 可跑。
- driver 已加 probe_controls（未调用）；等 11:41 用户交接后实测 Cuphead 按键。
- 测试 213；HEAD 965898c；未控制游戏。

## 2026-11-02 11:50 实机按键探测（Cuphead）

- 在 gameplay 下跑 probe_controls（12 候选键）：
  - RIGHT: player_dx +0.0465 → 右移确认
  - LEFT: player_dx -0.0540 → 左移确认
  - DOWN: player_dy -0.0098（待定：下蹲/下看）
  - Z: 画面变化 3.8（此前实机确认=跳跃；本次玩家检测短暂丢失，未记位移）
  - X: 画面变化 4.1（此前实机确认=射击；无位移）
  - C/V/SHIFT/SPACE/ENTER: 画面变化，但未自动分类
  - ESC: 大变化（暂停/返回）
- 说明“画面差分 + 玩家位移”能区分方向键，但跳跃/攻击/冲刺需要更长 settle 或语义上下文；下一步可用“玩家 y 轨迹”专门测跳/冲刺。
- 驱动已关闭；游戏在 gameplay HP3；未通关。

## 2026-11-02 11:58 跳跃/冲刺动作测量

- Z：采样 y 从 0.512→0.789，max_abs_dy≈0.277 → 跳跃确认。
- SHIFT：max_abs_dx≈0.102 → 冲刺位移确认。
- X：玩家检测受射击特效干扰（max_dx 0.35 明显是误匹配），不能靠单次位置判定射击。
- RIGHT/LEFT 在屏幕中心时主要体现为镜头滚动，玩家屏幕 x 变化小；应结合 scroll_s 而不是只看玩家屏幕坐标。
- 结论：冷启动探测需要“按键效果签名”分类器，而不是只看画面 diff 或玩家 dx。
- 驱动已关闭；未通关；README 未写。

## 2026-11-02 12:22 冷启动端到端

- 实机 probe_controls 12 键耗时 7.38s；motion 测 Z/SHIFT/X 约 3s；总 time-to-controls ~11s。
- Z: max_dy 0.282 -> jump；SHIFT: max_dx 0.161 -> dash；X: 无位移（attack 由键名先验补充）。
- 合并 profile（tmp/coldstart-cuphead-profile.json）：move_right/left/up/down, jump(z), dash(shift), attack(x), menu(esc)；jump 冲突 alternatives space。
- 测试 217；HEAD a5e75e1；驱动已关闭；未通关；README 未写。

## 2026-11-02 12:45 Instant Play 实机验证

- 冷启动 profile → to_engine_profile → 覆盖本地 controls/combat → 20s PolicyRunner。
- 结果：ticks 700, hz 34.8, scroll_s -3.625, scene gameplay；驱动/按键已停，profile 已恢复。
- 说明「探测→profile→运行」链路可用；仍未通关，README 未写。

## 2026-11-02 13:35 Instant Play metrics

- 新增 InstantPlayMetrics：time_to_first_action / controls / menu / gameplay，首次标记幂等。
- 测试 220 engine / 44 plugin；HEAD 92fa31b。
- 未控制游戏；未通关；README 未写。

## 2026-11-02 15:10 实机 intent 验证

- gameplay 短跑 45s：ticks 1450, hz 32.2, scroll_s -0.439, HP 2。
- observation: enemy_ahead=True, enemy_distance=0.31, enemy_role=approaching。
- intent: attack / "enemy ahead role=approaching" —— 与画面（花妖在脸上）一致。
- 但策略被花妖挡住，推进只有 0.44 屏；说明 intent 观察正确，执行层仍会卡在交战。
- 驱动已关闭；未通关；README 未写。

## 2026-11-02 15:16 卡死修复

- attack stall：45s scroll -0.439 -> -3.633（一局），但第二局仍 -0.543，不稳定。
- 加 progress guard（3s 不涨 -> suppress engage + tap jump）：60s scroll -1.554。
- 仍未通关；README 未写；驱动已关闭。

## 2026-11-02 15:34 多局统计

- 5x60s：scroll -1.71 / -3.78 / -2.68 / -2.34 / -2.85，平均 -2.672，最好 -3.781，4/5 存活。
- 追加 120s：scroll -0.185，又卡在花妖；稳定性不足。
- 说明 progress guard 有效但不稳定；需要更强的“绕怪”动作（不只是抑制 engage）。
- 仍未通关；README 未写；驱动已关闭。

## 2026-11-02 16:20 绕行实验

- 强制 advance+jump+dash 绕行：5x60s scroll -3.22/-0.80/-0.10/-1.97/-0.14，平均 -1.247，比上一版 -2.672 更差。
- 结论：激进绕行会把角色送进危险/打乱节奏，不可取；已 git checkout 回退到 8ea8daf。
- 仍未通关；README 未写；驱动已关闭。

## 2026-11-02 16:38 默认不跳 A/B

- jump=0, engage=0.2：5x60 平均 -1.38。
- jump=0, engage=0：5x60 平均 -1.59。
- jump=420, engage=0（旧）：5x60 平均 -2.67。
- 结论：Cuphead 前段“周期跳”反而帮助推进/躲地面敌人；默认不跳的假设在本关不成立。已恢复 jump=420, engage=0。
- 仍未通关；README 未写；驱动已关闭。

## 2026-11-02 17:40 目标改为五层架构（revision 13, active）

- L0 感知/执行：Python 30–60Hz，抓帧/输入/前台/安全，无语义。
- L1 反射/技能：Python 30–60Hz，WorldState + 短时缓冲 + ttc + 微技能 + 卡死/assist_request。
- L2 情境描述：Python 先做，可选小 VLM，1–5Hz，SituationReport（事件/置信/证据），只描述不决策。
- L3 战术决策：我/子 agent，0.5–2Hz，输出 Intent（goal/skill/target/risk/TTL），不碰按键。
- L4 战略学习：离线复盘、profile/规则、A/B、知识库。
- 落地顺序：schema → L1 时序/ttc → L2 Python → IntentArbiter + 低频模型环 → A/B。
- 真实通关前不写 README「茶杯头已通关」。

## 2026-11-02 17:55 L2/L3 实机验证

- situation：识别 4 个 threat_charging，ttc 0.138/0.289/0.313/0.442，side center/right；options 含 jump/dodge_left。
- planner_intent：goal=avoid, skill=jump, risk=high, priority=9, target_id=709, reason=charging ttc=0.138。
- 25s scroll -1.614, hz 32.9；说明 L2 事件与 L3 intent 已能实时输出（但尚未执行 intent）。
- 驱动已关闭；未通关；README 未写。

## 2026-11-02 18:15 模型 Intent 通道

- PolicyRunner.submit_intent + session.submit_intent：外部低频模型可向运行中的 arbiter 推 Intent。
- 修复竞态：arbiter 创建/更新共用锁，模型 entry 不再被 planner 新实例覆盖。
- 验证：模型下发 advance(TTL 4s)，2 秒后 active_intent 仍 source=model/arbiter=model；scroll -0.428。
- 说明：模型现在可以按 0.5–1Hz 在关内做高层决策，不再只是写死 Python；执行仍由 L1 完成。
- 未通关；README 未写；HEAD 372df3c。

## 2026-11-02 19:40 L1/L2 准确率与模型延迟实测

### 10 点同步采样
- 新命前/陈旧阶段：player_age 1.3s→8s、missing 22，L2 仍曾用旧锚点报 threat_charging；已修：新命重置 anchor/player/temporal，age>400ms 或 missing>5 时 temporal 输入清空，L2 标 player_stale。
- 修复后 10 点：3 个 death/dialogue/开局样本正确标 stale、无幽灵威胁；7 个 gameplay 样本玩家位置与截图一致（如 x=0.245/0.462/0.513），HP3 与截图一致。
- 剩余：HP 偶发滞后、玩家 confidence 0.55 偏低、threat 里仍可能混入特效；需要继续观察。

### 模型决策延迟
- decision-log 实测两次间隔：**9.12s / 8.93s**；p95 ≈ 9s。
- 目标要求 TTL 覆盖 p95（2500–3000ms），实际远超。
- 结论：当前主模型不能做 1–2Hz 战术决策，更不可能做逐弹幕反射；只能做 10s 级姿态/策略，或需要更快的 L3（小模型/子 agent/事件驱动）。
- 模型 intent 通道本身可用：TTL 3s 内 active_intent=model；最后一次 scroll -6.158, HP1。

### 当前阻塞/需要的决定
- 继续用主模型在关内做战术决策，延迟不可接受；
- 可选：A) 事件驱动，只在卡住/低置信时由模型介入；B) 用更快的 L3 小模型；C) 模型只做姿态/参数，Python 做战术。
- goal 仍为 paused（模型无法自行 resume，需要用户在界面恢复）。

### 未完成
- 未通关；README 未写；L2 准确率还没到“10 点全部人工核对”的严格标准；无模型 A/B。

## 2026-11-02 22:05 工具面接线

- 新增 `game_intent`（引擎 stdio `submit_intent` + 插件工具）：低频战术 Intent，默认 advisory；本地 60 Hz 策略继续跑，执行还需 `profile.instant_play.intent_enabled=true`。
- 测试：插件 45、引擎 242、集成 11/11。
- Cuphead 仍在下载；暂无实机新数据。

# RUN STATE（仓库内续跑笔记；本地路径用占位符）

> 作用：上下文被压缩/会话中断后，先读这份文件恢复状态。
> 最后更新：2026-11-06 10:45（顶部为当前判断；下面是按时间追加的续跑记录）

## 2026-11-06 深度复盘与策略 v2.1（修复感知断路 + 反应式策略 + 全量过程留痕）

> 结论：P4 首批单机制 Canary（`dash_through` / `jump_over` / `stop_shoot`）全部 `no_gain` 的根本原因已定位——不是顶层理论问题，而是**底层感知到执行之间存在 4 个代码级断路**，导致上层策略在开局 2 秒后形同失明，且角色被 420ms 周期盲跳完全占满物理状态。

### 定位到的 4 个代码级根因
1. **玩家追踪永久锁死（`player_stale` 断路）**：`cuphead.json` 颜色追踪固定 `color_score=0.55`，而 `policy.py:_update_player` 对位移 `>0.25` 要求 `score>=0.9`，导致冲刺/大跳后玩家坐标永久拒绝更新（实测 `player_age_ms=16387ms`）；进而触发 `_update_observation` 在 `player_age_ms>400` 时直接 `break` 清空全部威胁轨迹（`entities=0, enemies=0`）。
2. **87% 运动威胁被归为 `parry` 并在 `WorldModel` 中丢弃**：实机 8 个运动轨迹中 7 个为 `parry`，而 `world_model.py` 只读取 `kind=="threat"`。
3. **周期盲跳（`jump_every_ms=420`）架空上层策略**：角色几乎 100% 处于半空或冲刺硬直中，上层选出的动作无法在合适的地面时机响应。
4. **`scroll_s` 开环漂移**：受阻挡时仍累加或漂移，绝对坐标热点跨局失准。

### 迭代计划（策略 v2.1 + 全量测试留痕闭环）
- **核心原则**：可以接受新方案依然无法通关，但**每次测试过程必须完整记录（轨迹 `traces` + 单局健康度 `runs.jsonl` + 入库复盘报告 `experiments/results/*.md`）**，支持复盘 → 定位 → 迭代 → 量化验证的循环优化。
- **Stage 0（留痕与复盘基建）**：扩展跑批与策略遥测，记录每局 `player_stale_ratio`、`threat_active_ratio`、`damage_events` 及 5–10Hz 关键决策时间线 `traces/<run_id>.jsonl`，支持自动生成批次复盘报告。
- **Stage 1（修复感知断路）**：修好 `_update_player` 锁死 Bug、取消 `player_stale` 清空 `_tracks`、实时 `_anchor` 过滤自身、将接近的 `parry` 纳入 `WorldModel.threats`；用离线单测 + 实机短测验证 `player_stale_ratio < 20%`。
- **Stage 2（反应式策略替代周期盲跳）**：实现可切换的反应式模式（平时地面推进射击，按前方同高度威胁/缺口触发轻重跳、中距威胁 `stop_shoot`、近迫威胁 `dash_through`），消除盲跳干扰。
- **Stage 3（批次对比与循环复盘）**：10 局批次测试，无论是否提升/通关，均输出完整时间线剖析与死因归因报告，驱动下一轮迭代。

## 2026-11-04 策略 v2 决策

> 结论：继续调参数/开关已到尽头。局内策略要从“反射规则汤”升级为 **WorldModel → Mode → Option → UtilityArbiter → Executor**；每条机制必须有运行时计数与 A/B 统计，才能算生效。

- 调研与架构：`docs/STRATEGY-V2.md`（Utility AI / GOAP / BT / Options / MPC / Cradle / Voyager / AlphaStar 取舍）。
- 检测基础设施已实现：
  - `engine/dsh_game_core/mechanisms.py`：机制注册表 + evaluated/triggered/applied/vetoed/noop/error 计数；`status.mechanisms`。
  - `engine/dsh_game_core/experiment.py`：RunMetrics、批次统计、bootstrap 中位数 CI、promote/no_gain/regression/insufficient 判定。
  - 已接入 periodic_jump / periodic_dash / edge_escape / shadow_advice / memory_context；`edge_escape=false` 可观测到 applied=0。
- 当前测试：引擎 **278**、插件 **45**。
- 下一步：Option 合约 + 5 个 option（shadow）→ UtilityArbiter（安全否决+承诺）→ 单机制 canary → 连续 3 批 A/B 才 promotion。
- 仍然未通关；README 不写「已通关」。

## 当前判断（2026-11-03 23:10 合并）

> 结论：**A 轨仍未通关；今天的最好 11.15 屏是离群值，20–30 局平均 4.1–4.2 屏，没有稳定到 6.5。继续自动扫参数/开关没有稳定收益。**

1. **A 轨现状：** 平均约 4.1–4.2 屏，最高 11.15（单局离群）；6.4 只在个别长局越过，7.0 仍不稳定可达；没有 LEVEL COMPLETE。
2. **已证明无稳定收益：** 学习 action bandit / shadow top1 / grounded gating / hit_dash / edge threshold / engage / jump 参数扫描；edge_escape 开/关平均都约 4.1–4.2。
3. **当前保留：** `dash_every_ms=800`、`dodge.press_ms=260`、`jump_every_ms=420`、`engage_radius=0.2`、`edge_escape=false`；memory / guide / death_context 目前只读。
4. **决策时间 9s 级**（9.12s / 8.93s，p95≈9s），仍不能进 1–2Hz 快环；L3 保持事件驱动。
5. **B 轨未完成：** Brotato 启动入口点错误，Overcooked 只有菜单/双人过场；需要可用的 Windows 单机游戏。
6. **仍未通关；README 不能写「已通关」。**

## Goal（另一台 DSH 主机，不是当前会话）

- id: `goal-283c1ac6-f742-4469-b1ae-5b4968ae946b`
- revision: 33（objective 已改成策略 v2 + 检测/量化，max rounds 120）
- **phase: blocked / disarmed（需用户在 DSH 界面恢复；本轮不自行 resume）** —— 模型不能自行 resume，需要用户在那台机器的 DSH 界面点一次「恢复 goal」。
- 若 goal 未恢复，那边的自动轮次不会继续。

> **2026-11-02 注**：这个 goal 属于另一台电脑上的 DSH 运行；当前 `dsh-game-bridge` 工作区另有本次会话的 goal（`goal-80d14fcf-...`，用户已暂停）。两者不要混用：旧 goal 的 resume 只对那台机器有效。

## 目标摘要

按 `docs/PROJECT-STRATEGY.md` 完成「看/玩/学」：
- P0：稳定≥40Hz、有卡/无卡 A/B 统计、坐标漂移<0.2；
- P1：对象级理解（ID+外观签名+角色 chaser/harmful/projectile+聚类）、chaser 优先 + turn_and_shoot、静态危险物、技能库/仲裁器、战术姿态、地图入口导航；
- P2：game_review 工具化、参数 preset、可选攻略、副本游戏矩阵、通关稳定性；
- 最终验收：Cuphead Forest Follies 从大地图 10 局≥7 通关 + 可复现 A/B 证据；引擎无游戏专用代码。

## 当前进度（2026-11-03）

- HEAD: 最新 `main`（见 `git log`）；测试：引擎 **273**、插件 **45**、集成 11/11（本地实测）。
- 目标未变：Forest Follies 从大地图 10 局 ≥7 通关；**仍未通关**。
- 实机 best：7.339 屏（旧）/ 6.812 屏（玩家修复后）/ 11.15 屏（今日离群）；20–30 局平均约 4.1–4.2。
- 架构：L1 反射 + L2 SituationReport + L3 Intent/arbiter；冷启动/Instant Play 已接线；主模型决策 p95≈9s，不能进 1–2Hz。
- 工具面已补 `game_intent`（stdio `submit_intent` + 插件工具）：默认 advisory，执行当前只覆盖 jump/dodge/retreat；需 `game_policy start intent_enabled=true` 或 `profile.instant_play.intent_enabled=true`。
- L2 准确率：10 点采样中 3 个 stale 正确、7 个 gameplay 位置与截图一致；仍有人工核对缺口。
- 当前会话 goal：`goal-80d14fcf-...`，用户已暂停（phase paused, revision 4）；今天 A 轨运行结束后驱动已关闭，实机是否在运行以用户为准。

### 历史进度（2026-10-30，提交 `8e4d8fa`）

- 帧率：分阶段计时已接入；样本 grab 5.3ms / entities 4.2 / player 2.6 / memory 1.3；单次样本 **41.6Hz**，另一次 44Hz；仍会波动，目标稳定 ≥40。
- 玩家追踪：每 8 拍一次 + 颜色校验；Cuphead profile `face_back=false`、`engage_max_ms=2500`。
- 坐标漂移：卡片链式合并修复后 `cards=2 mean=0.089 max=0.100 <= 0.2`。
- DangerCard：结果回写/换技能阶梯已实机验证；A/B 只有单对样本（knowledge off -0.087 屏 / on -2.295 屏），样本不足。
- 卡账本：约 22 张；response tries 9 / avoided 4 / failures 5（avoid_rate 0.444），mean efficacy ~0.496。
- 录制：异步录制线程；episode 有 meta/events/frames。
- 已知问题（当时）：匿名运动簇、face_back 关闭、静态危险物漏检、A/B 无跑批、帧率波动、地图入口无导航。

## 后续计划（2026-11-03 23:10）

> 前提：A 仍未通关；今天已证明“继续自动扫参数/开关”没有稳定收益。下一步先冻结配置、做证据/demo，不再做全局参数扫描。

### A 轨：Cuphead Forest Follies（优先）

**A0 冻结配置 + 基线（先做）**
- 固定 `dash_every_ms=800` / `jump_every_ms=420` / `dodge.press_ms=260` / `engage_radius=0.2` / `edge_escape=false`，不再改参数。
- 跑 10–20 条干净一命（record=true），记录 peak、时长、death cause/position、hz；先看死亡分布，不只看均值。
- 验收：10+ 条完整记录；11.15 离群局与 2–4 屏典型局有帧级差异证据。

**A1 死因复盘（1–2 天）**
- 用 `death_context` + episode 帧，把死亡分为 `cornered` / `hit` / `fall` / `stuck`，对比 11.15 离群局与典型局。
- 找出第一个分歧帧（站位、弹幕、输入时机）；不要先加反射。

**A2 一次只改一个通用技能（每个 10 条 A/B）**
- 候选 1：预判弹幕的提前 jump/dash（不是受击后的 hit_dash）。
- 候选 2：被击退后的回中/避免贴左边缘。
- 候选 3：近身花妖的停火/清场时机。
- 通过标准：均值 ≥ +0.5 屏且最差局不恶化；否则回退。两个实验无收益就停，转 A3。

**A3 人工示范 / route macro（若 A2 无收益）**
- 人工打通 0–6.5 屏的一段，录 episode 帧+输入；把路线写成 profile macro（scroll 触发、分步 hold/tap），引擎不加 Cuphead 分支。
- 先验证稳定到 6.5；再处理 7.0 平台/飞花；最后用 10 局 ≥7 通关验收。

### B 轨：泛化烟测（不阻塞 A）

- 目标：第二款 Windows 单机、键盘、可快速进 gameplay 的游戏；零引擎改动。
- 优先 Brotato 的正规 Steam 安装（当前入口点错误是 DLL/破解问题，不再替换系统 DLL）；备选 VVVVVV/Celeste demo 或 itch.io 的 Godot demo。
- 验收：attach、菜单、按键映射、首次有效动作、time_to_controls≤5 分钟、LevelMemory 加载/卸载；不要求通关。
- 若本周找不到可用游戏，标记 B blocked，A 继续。

### 工程/文档

- 更新 README/STATUS 测试数为 **273 engine / 45 plugin**；集成 11/11 复跑一次。
- 不提交本地 profile/录像/账本/guide；引擎保持零游戏分支。
- 通关前不写「已通关」。

### 停止规则

- 不再做全局参数扫描（jump/dash/engage/edge 已扫完，平均无提升）。
- A2 两个实验无收益 → 走 A3 人工示范/route，不无限自动调参。
- B 找不到游戏 → B blocked，A 继续。

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
- （另一台机器）goal 仍为 paused（模型无法自行 resume，需要用户在那台机器的界面恢复）。

### 未完成
- 未通关；README 未写；L2 准确率还没到“10 点全部人工核对”的严格标准；无模型 A/B。

## 2026-11-02 22:05 工具面接线

- 新增 `game_intent`（引擎 stdio `submit_intent` + 插件工具）：低频战术 Intent，默认 advisory；本地 60 Hz 策略继续跑，执行当前只覆盖 jump/dodge/retreat；需 `game_policy start intent_enabled=true` 或 `profile.instant_play.intent_enabled=true`。
- `game_policy start` 新增 `intent_enabled` 开关，可显式开启 intent 执行（默认关）。
- 测试：插件 45、引擎 243、集成 11/11。

## 2026-11-02 23:10 首轮实机启动（Cuphead 下载完成）

- 游戏：`<game-dir>\Cuphead.exe`；必须用 `-screen-fullscreen 0 -screen-width 960 -screen-height 540 -popupwindow` 启动，否则全屏窗口抓不到（DXcam 只看到桌面）。
- 修复 DPI bug：Windows 125% 缩放下，`GetMonitorInfoW` 给 1536x864、DXcam 给 1920x1080，attach 报“没有显示器与窗口匹配”。`windows.py` 现在在导入时设 per-monitor v2 DPI awareness，attach/snapshot 正常拿到 960x540。
- 实机：policy 45s、约 38.5Hz；但角色还在老茶壶家/大地图，`scroll_s≈-0.03`，没有进入 Forest Follies；地图入口仍未找到。
- 现状：游戏窗口已 topmost、engine 可 attach/capture；需要人工把角色走到 Forest Follies 入口（或下一步做地图航点），才能开始关卡内 baseline。

## 2026-11-02 23:35 Forest Follies 首轮 baseline（用户已进关）

- 60s policy：ticks 2096、约 33.3Hz、actions 573、escapes 16；scroll 最好到 -2.521，约 37.8s 出现一次 death/reset，结束在 -1.845。
- `evaluate --game cuphead --level forest-follies`：episodes 5、damage 1、deaths 0、best progress **2.639 screens**、DangerCard 4 张全是 candidate。
- 结论：首轮只到约 2.6 屏，离旧记录的 6.4 屏还有明显差距；先继续采 60s episode，再按死亡位置分类。仍未通关。

## 2026-11-03 00:00 第二轮 baseline：6.4 屏已过，卡点移到 7.0 屏

- 180s（base profile）：15 episodes、7 damage、**7 deaths**、best progress **7.339 screens**；旧 6.4 屏平台段已经越过。
- 7.0 屏全分辨率帧：下层平台 + 一只橙色飞花（射紫色弹）+ 两只地面花，玩家 HP1，policy 在同一位置停约 10s 后死亡。
- A/B：
  - `jump_every_ms=420, engage_radius=0`：best 5.675、6 deaths，**更差**；
  - base + `macros` 在 -7.0 触发（jump/right）：best 4.538、7 deaths，**没跑到触发点**，不能评估宏本身。
- 结论：**不要继续全局调参**；当前卡点是 7.0 屏下层平台→上层平台的跳跃 + 飞花弹幕。下一轮用固定序列/手动 handoff 验证这一小段，再决定 profile 宏。
- 记录修正：death scene 现在会额外写 `{"type":"death"}`，evaluate 才能统计 deaths。

## 2026-11-03 00:15 Player continuity fix + 7.0 evidence

- 7.0 全分辨率帧暴露玩家追踪误判：颜色 fallback 把左下的红/橙花当成玩家（(0.056,0.948)），真实 Cuphead 在 (0.50,0.56)；HP1，右上有飞花。
- 已修 `_find_player_color`：有 previous anchor 时只考虑 search_radius 内的 blob，取最近而非最大；离线在 7.0 帧上返回 (0.502,0.559)。测试 245。
- 修复后 base 180s：17 episodes、10 damage、6 deaths、best **6.797**；仍未通关，7.0 未过。
- 其它尝试：handoff 没跑到 7.0（best 4.751）；knowledge-on best 6.293；周期跳/route-macro 变体均更差。run-to-run 方差仍大。
- 下一步：用修复后的 base 多跑几局，观察 player_age/stale 是否下降；再在 7.0 做 handoff/宏。

## 2026-11-03 00:20 Round 3：玩家修复后的 300s baseline

- base + player continuity，300s：29 episodes、15 damage、**13 deaths**、best **6.812**；13 次死亡尝试，仍未通关。
- 6.4 已过，7.0 仍没过；player_age 仍会出现 1–2s 的 stale，confidence 固定 0.55，颜色追踪的连续性还不够稳。
- handoff 尝试：目标 -6.6 的 run 最好只到 5.587，没触发；目标 -6.9 的 run 最好 4.751，也没触发。固定序列仍无法评估。
- 结论：玩家误判已修，但**到达 6.5 的可靠性不足**是当前前提问题；下一轮先做“稳定到 6.5”（而不是继续在 7.0 调宏），再 handoff。

## 2026-11-03 00:35 Round 4：template A/B 与可靠性

- 本地 Cuphead 模板（从 7.0 帧裁剪，仅 tmp，不入库）离线匹配 7.0 帧 score 0.98/0.83；但实机运行时模板阈值未命中，仍回落到颜色（confidence 0.55），180s best 只有 **3.529**、7 deaths。模板路线暂不采用。
- 颜色 continuity 版本 300s：13 deaths、best **6.812**；handoff 在 -6.6/-6.9 均未触发（best 5.587/4.751）。
- 当前真正瓶颈是**从起点稳定到达 6.5 屏**，而不是 7.0 宏本身。
- 下一轮：A/B 闪避半径/冷却与交战距离（提高生存），或重复跑到 6.5 后立即 handoff；不再折腾模板。

## 2026-11-03 00:40 Round 5：clean reset 失败，游戏需重新进关

- 发现暂停菜单有 `RESUME / RETRY / OPTIONS / EXIT TO MAP`；本想把 `ESC → DOWN → Z` 固定成“RETRY 重置”，但自动化选到了 **OPTIONS**，把分辨率从 960x540 改成了 400x300（后又循环到 1280x600）。
- 随后 5 次所谓 clean baseline 实际是在 options/大地图上跑：peak ≈0、hz 20–26，**数据无效，不要使用**。
- 游戏当前停在大地图（1280x600，商店附近），还没有回到 Forest Follies。
- 有效的仍是之前 300s base：13 deaths、best 6.812；player continuity fix 保留。
- 下一轮前提：人工进入 Forest Follies；之后再修 reset（先 OCR 确认 pause，再选 RETRY，不能盲按 DOWN）。

## 2026-11-03 00:50 Round 6：reset 已加 OCR 门，仍卡在进关

- 游戏进程还在，但窗口被最小化；恢复后仍在大地图（1280x600，商店附近），不在 Forest Follies。
- 地图上试了商店/红白靶点附近移动，仍未找到 Forest Follies 入口；红白靶点不是该关入口。
- clean reset 已改成 OCR 门控：只有 pause 文本里出现 `RETRY` 才按 DOWN+Z；大地图 pause（RESUME/OPTIONS/EXIT TO TITLE/QUIT）只关闭菜单。实机在 map 上验证 `reset=False`，分辨率未再改变。
- 本轮没有新的关卡内数据；有效 baseline 仍是 13 deaths / best 6.812；玩家连续性修复保留。
- 下一轮必须人工进关，否则只能在 map 上空转。

## 2026-11-03 01:05 Round 7-8：clean 一命一局 baseline

- 用户手动进关；OCR 门控 reset 实机通过（5 次 reset=True），不再误开 OPTIONS。
- 1280x600、45s 固定窗口：5 runs，peak 2.19–3.82 屏，hz 29.8–31.0；evaluate 23 episodes / 10 damage / 8 deaths / best 3.822。
- 分辨率影响明显：1280x720 一命一局 5 条命 peak 1.07–2.61，hz 25.4–28.8；用 DPI-aware 进程把窗口缩回 960x540 后，5 条命 peak 1.21–2.56，hz 34.7–36.9，每条命 16–22s 全部 death。
- 结论：**典型一局死在 1–2.6 屏**；6.812 / 7.339 是少数长局的 best，不代表常态。当前主卡点是早期生存，不是 6.4/7.0 的宏。没有 LEVEL COMPLETE。
- 用户已暂停 goal 并关闭游戏；今天到此。下一步：10 条干净一命 baseline + 按死亡位置分类，先降 0–3 屏死亡率。

## 2026-11-03 10:10 目标改为双轨：垂直切片 + 泛化烟测（revision 18）

- A 垂直切片（Cuphead）：先 0–3 屏早期生存；10 条干净一命 baseline + 死亡位置分类；稳定到 6.5 后，再评估 7.0 平台/飞花；最后通关。7.0 宏不再提前。
- B 泛化烟测：第二款不同游戏，零引擎改动，验收 time_to_controls≤5 分钟、首次有效动作、菜单/开局。
- 硬约束：引擎零游戏名/关卡坐标分支；游戏差异只进 profile；L2 采样/准确率门槛；主模型 p95≈9s，只做姿态/事件驱动；真实通关前不写 README。
- goal phase 仍为 paused：模型无法自行 resume，需要用户在界面恢复。

## 2026-11-03 12:20 经验学习闭环首测（未成功曲线）

- 实现：experience Context/Outcome/SkillStats、Learner（死亡回传/持久化）、PolicyRunner 在线学习（Context→动作→400ms 回写）。
- 第一批 10 局（清除学习）：peak 2.69/6.29/3.00/2.30/2.59/2.42/9.33/3.09/2.02/3.49；平均 3.72；全死亡。前5 3.38，后5 4.07；9.33 是离群值。
- 第二批 10 局（持久化）：平均 2.82；无保持/提升。
- 粗粒度 Context + 死亡回传后 10 局：平均 2.71；前5 2.82，后5 2.61；无曲线。
- 统计：49 contexts / 440 samples；`advance` 占绝大多数，jump/dodge 极少被尝试；多数 context 只 1–2 样本；奖励多为接近 0 的小 progress，死亡只回传给最近 10 步。
- 结论：机制已通，但当前 UCB/探索与信用分配不足以产生稳定学习；9.33 不能当证据。需要改：动作探索策略、outcome 窗口、context 粗化/泛化、死亡回传范围。
- 未通关；README 未写；驱动已关闭。

## 2026-11-03 12:35 学习修正后仍无曲线

- 修复 learner 读写 key 不一致（apply 写细 key/choose 读粗 key）；强制每动作 min_tries=2；outcome 窗口 1s；死亡回传 20 步。
- 清空学习状态后 10 局：2.27/2.68/3.30/1.97/3.08/2.55/1.77/3.15/2.65/1.83；平均 2.53；前5 2.66，后5 2.39；全死亡。
- 结论：机制已正确接线，但“在线执行 UCB 选择”没有带来生存提升，反而略低于 baseline；根因是 sparse reward + 探索动作直接执行 + context/信用仍不足。
- 下一步：学习先 shadow 评估（不直接执行），只有统计置信的优势动作才 promotion；限制探索到低风险 context；否则学习会拖累表现。
- 未通关；README 未写；驱动已关闭。

## 2026-11-03 12:50 学习 promotion 后 10 局

- 策略：只有 10% 探索或「粗 context 优势 >=0.02 且样本>=4」才执行非 advance 动作。
- 结果：2.88/2.83/2.36/2.10/3.24/5.48/2.51/2.42/1.80/2.50；平均 2.81；前5 2.68，后5 2.94；全死亡。
- 结论：不再明显拖累，但没有证明学习收益；5.48 是单局高值。学习机制仍处于“可运行、未证明”。
- 下一步：把学习从 action bandit 转为参数/shadow 评估，或先专注早期生存的通用技能（不是再跑更多随机探索）。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 12:46 engage A/B

- jump=420, engage=0.2，10 条一命：1.24/5.10/3.60/2.30/1.46/3.67/1.26/1.74/4.49/1.63；平均 2.65；全死亡。
- 对照 jump=420, engage=0：平均 3.27。
- 结论：停下来射击没有改善早期生存，反而略差；早期死亡主要不是“没停下来打”，而是移动/躲避/时机。
- 下一步：按死亡位置与死亡前 1–2 秒帧分类（贴脸/弹幕/坑/平台），只修最高频一类；不再盲调 engage/jump 全局参数。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 13:00 角落脱困 A/B

- 通用 left-edge escape（x<0.10 持续0.5s → 松前进、跳/冲、恢复前进）：10 条 peak 4.26/3.36/2.72/3.28/3.90/3.36/2.25/3.66/2.48/2.06；平均 3.13，前5 3.50，后5 2.76；全死亡。
- 对照 jump=420/engage=0：3.27。无显著提升，但也没有明显退化；保留为通用保护。
- 死亡帧分类：多次死在左边缘（x≈0.008/0.10），伴随飞行花妖/弹幕；但脱困规则没有解决弹幕/接触伤害。
- 当前早期生存仍未解决；学习/参数 A/B 均未产生稳定收益。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 13:10 周期冲刺 A/B（有效）

- 配置：jump=420, engage=0, dash_every_ms=800；保留通用 left-edge escape。
- 第一批 10 局：3.51/3.46/4.62/7.33/2.37/2.51/3.75/2.64/4.09/9.04；平均 4.33。
- 第二批 10 局：7.18/3.49/4.34/3.53/2.85/2.65/3.17/2.42/4.61/4.03；平均 3.83。
- 合计 20 局平均 4.08；对照 baseline 3.27；提升约 25%，两局到 7+。
- 解释：dash 可能提供无敌帧/位移，改善弹幕与贴脸威胁；仍全死亡，未过 6.5 稳定门槛。
- 已将 repo profile dash_every_ms 从 0 改为 800（游戏数据，非引擎特判）。

## 2026-11-03 13:12 dash 间隔 A/B

- dash=800：20 局平均 4.08。
- dash=600：10 局平均 2.67（3.33/2.62/2.37/3.03/3.55/3.52/1.29/3.50/2.44/1.04）；明显更差。
- 结论：800ms 附近是当前较好值；dash 是有效的通用机动/无敌帧技能，但不是通关解。
- 已恢复 cache/repo dash=800；未通关；README 未写；驱动关闭。

## 2026-11-03 13:20 dash reflex A/B（负）

- 配置：dash=800 + 威胁 ttc<=0.45 时额外 dash；10 条平均 3.29（3.45/3.59/3.88/2.28/3.64/3.90/2.25/2.95/4.22/2.71），低于周期 dash 的 4.08。
- 结论：威胁触发 extra dash 没有收益，已回退代码、关闭 dash_reflex；保留 dash=800。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 13:30 跳跃按住时长 A/B

- dash=800 固定，jump press 160ms -> 260ms。
- 第一批 10 局：3.89/4.41/3.35/4.28/4.63/8.35/4.48/4.03/2.38/3.86；平均 4.37；其中 1 局 60s 未死亡。
- 第二批 10 局：3.93/4.66/2.86/4.59/4.13/3.89/1.13/9.92/2.98/2.05；平均 4.02；最高 9.92。
- 合计 20 局平均 4.19；对照 160ms 的 4.08；小幅提升，且有 1 局活满 60s。
- 已把 repo profile dodge.press_ms 从 160 改为 260（游戏数据）。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 13:35 jump interval A/B

- dash=800, jump hold 260, jump_every 420 -> 20 局平均 4.19。
- jump_every 520：10 局 3.40/3.71/3.88/3.71/4.03/3.78/2.41/5.19/2.11/2.37；平均 3.46；全死亡。
- 结论：520 明显更差；恢复 jump_every=420。参数扫描到此为止，避免过拟合。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 13:45 受击后 dash A/B（负）与暂停

- hit_dash（受击后 600ms 内 dash 脱离）：10 局 2.44/2.02/3.26/4.22/2.32/2.29/2.82/3.68/3.54/2.66；平均 2.92，低于当前最佳 4.19。
- 已回退 policy 代码（未提交实验）、关闭 hit_dash，恢复 jump=420/dash=800/press=260。
- 用户要求暂停：驱动已关闭、按键释放、无 play_server 进程；goal 暂停。
- 未通关；README 未写。

## 2026-11-03 14:55 记忆架构代码化

- 新增 `level_memory.py`：scroll 分段的死亡/受击/动作成功率、hotspot/preferred、JSON 持久化。
- 新增 `memory_loader.py`：游戏级 attach 加载、关卡级进入加载/离开卸载、安全 id 防穿越。
- 新增 `docs/MEMORY.md`：作用域/目录/加载/攻略边界/元记忆/待办。
- 测试 260 passed。未启动游戏（按要求）。
- 待接入 Session/PolicyRunner：attach/进关/离关加载；death/damage/success 更新；hotspot 接候选评分。

## 2026-11-03 15:15 记忆接线

- Session.policy_start：加载 game memory + 当前 level memory（路径可由 DSH_GAME_BRIDGE_MEMORY_DIR 覆盖，默认 data_root/memory）。
- Session.policy_stop：保存并卸载 level memory。
- PolicyRunner：按 tick 记录 segment visits；fresh hit 记 damage；death 记一次 death；status 暴露 level_memory summary/hotspot/preferred。
- 记忆暂不改变动作，只记录/显示。
- 测试 261 passed；未运行游戏。

## 2026-11-03 15:25 记忆/攻略离线接线完成

- MemoryLoader 接进 Session：policy_start 加载 game+level，policy_stop 保存/卸载。
- PolicyRunner 记录 segment visits/damage/death，status 暴露 level_memory summary/hotspot/preferred；暂不改动作。
- GuideStore 扩展：scope=game/level/boss、source_type、assisted；game 级卡不要求 level，支持 load_game。
- docs/MEMORY.md 已记录架构；测试 262 passed。
- 未运行游戏（按要求）；下一步：hotspot/preferred 接候选评分（shadow），再跑游戏验证。

## 2026-11-03 15:40 离线记忆闭环完成

- LevelMemory + MemoryLoader + Session/Policy 接线：完成。
- GuideStore 扩展 game/level/boss、source/assisted：完成。
- shadow 候选评分（hotspot/preferred 只影响分数）：完成，status.shadow_advice。
- memory_context：按当前 scope + guide + 字符预算压缩上下文：完成。
- 测试 268 passed；未运行游戏。

## 2026-11-03 19:30 记忆实机验证

- 进关后 policy_start：session 正确加载 `memory/games/cuphead/levels/forest-follies.json`（不是空 level.json）。
- 发现 bug：死亡在 scene gate 分支，`_update_level_memory` 只在 gameplay 分支，deaths 不写；已把记录调用移入 scene gate。
- 修复后 4 条死亡：forest-follies 9 segments、deaths=4、damage=47、actions 仍为空。
- 死亡分布在相邻段 -8/-7/-6/-5（bucket 0.5），严格同段无 hotspot；新增通用邻域聚合（radius 1.5）：zone_deaths=4，hotspots=6。
- memory_report 可离线列出 hotspot；loading/saving 验证通过。
- 未验证：preferred action（actions 未记录）、shadow A/B；README 未写；驱动关闭。

## 2026-11-03 19:25 记忆完整验证（加载/保存/死亡/伤害/动作/shadow）

- 继续跑死亡后：forest-follies 13 segments、deaths=7、damage=75–78、hotspots=9。
- 新增动作→结果记录（1s 窗口，hp/进度判 good）：各 segment 已有 jump/dash/advance 的 n/good，preferred 开始出现（当前为 jump）。
- 实机 status：
  - level_memory.hotspot=true, preferred=jump；
  - shadow_advice top=jump，reasons=[level_memory_preferred, hotspot]，仍 shadow=true，不改变动作。
- 验证通过：进关加载、离开保存、死亡/受击/动作写入、hotspot 邻域聚合、shadow 使用记忆。
- 未验证：shadow vs 默认 A/B；README 未写；驱动关闭。

## 2026-11-03 19:35 shadow promotion A/B（负）

- hotspot 且 shadow top=jump/dash/retreat 时真正接管；10 局 1.86/3.40/3.23/2.47/5.04/3.18/4.07/2.25/2.59/2.70；平均 3.08；全死亡。
- 对照默认动作（dash800/jump260）20 局平均 4.19。
- 结论：shadow top 直接 promotion 不划算，已回退 promotion 代码、关闭 memory.promote；保留 shadow 只记录/展示。
- 说明：记忆内容/热点已可信，但“用记忆建议直接接管动作”还需要更好的时机/仲裁，不能靠 top1。

## 2026-11-03 19:40 动作状态

- PolicyRunner 新增 action_state：grounded/jumping/dashing/hurt/last_action。
- jump/dash/edge 设置窗口（jump 450ms、dash 250ms）；fresh hit 设 hurt 350ms。
- status.action_state 暴露；暂未用于接管动作。
- 测试 271 passed。

## 2026-11-03 19:50 gated shadow promotion A/B（仍负）

- 仅 hotspot + grounded + !hurt 时执行 shadow top；10 局 5.18/1.80/3.49/3.24/2.68/3.33/2.74/2.14/3.43/4.16；平均 3.22，仍低于默认 4.19。
- 结论：问题不是执行窗口，而是 shadow top 本身不够可靠/过于局部；继续 promotion 无意义。
- 已回退代码、关闭 memory.promote；保留 shadow 只读。
- 下一步：不要用 top1 接管；要么学习更好的打分，要么把记忆只作为风险提示给模型/仲裁。

## 2026-11-03 19:45 jump interval 360 A/B

- jump360/dash800/hold260：10 局 3.57/3.61/3.85/4.09/0.01/3.57/2.64/2.53/3.90/3.37；平均 3.11；全死亡。
- 对照 jump420：20 局平均 4.19。
- 结论：360 更差；恢复 420。参数扫描停止。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 19:55 攻略优先接线

- 从 Cuphead wiki 抓取 Forest Follies 的可用要点（Run&Gun/无 Boss/评分项/金币/粉色可弹反），只存要点，source_url、assisted=true。
- 本地 GuideStore：game 卡 1 张、level 卡 1 张（`%LOCALAPPDATA%\dsh-game-bridge\guides`，未入库）。
- Session.policy_start 现在还会加载 game/level guide cards，挂到 memory_loader.game_data["guides"]。
- memory_context 支持从 game_data.guides 取 facts（仍受 scope/字符预算约束）。
- 测试 271 passed。

## 2026-11-03 20:05 memory_context 接入 status

- PolicyRunner 接收 memory_loader，每 30 tick 组装 memory_context（当前 scope + guide facts + level memory，字符预算）。
- status.memory_context 暴露给模型/决策层；仍不改变动作。
- 测试 272 passed。

## 2026-11-03 20:15 memory_context 实机验证

- 进 Forest Follies 后 status.memory_context：
  - scope=level, game=cuphead, level=forest-follies；
  - guides=6 条（Run&Gun/评分项/金币/粉色弹反/无 Boss/提示），source URL 保留；
  - level_memory：segments 13、deaths 37、damage 320、hotspots 13；当前 s:-5 死亡8/伤害79，preferred=jump。
- 说明：按关加载、guide 注入、LevelMemory 热点/动作统计均已进入策略状态；仍不改变动作。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 20:00 grounded gating A/B（负）

- 周期 jump/dash 仅在 grounded 时触发：10 局 3.08/2.22/2.66/2.57/2.85/4.49/2.77/2.20/2.49/4.18；平均 2.95。
- 对照 4.19：明显更差；空中/冲刺中的跳跃其实在躲弹幕，不应一律禁止。
- 已回退代码；保留 action_state 只读。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 20:10 计划更新：B 选定 Brotato

- B 轨具体化：Brotato（Godot，单机，俯视自动射击），窗口化 960x540；零引擎改动验证 engine/attach/按键/菜单/开局/移动、time_to_controls≤5min、首次动作、game_id=brotato 的 LevelMemory 加载/卸载；不要求通关，不污染 A。
- Overcooked（双人）仅作为后续多 agent/协作专项，不纳入本次 B。
- A 保持不变：当前 4.19 平均、9.92 最高、未通关；下一步死亡原因分类/时序/安全方向。

## 2026-11-03 20:40 B 轨烟测

- Brotato：进程可启动但弹“Brotato.exe - 无法找到入口”；尝试用 steam_api64.rne 替换 DLL（已备份）仍失败，已还原原 DLL。
- Overcooked（备选）：窗口化启动成功；engine attach 成功；OCR 菜单/按键提示正常；probe_controls 9 键耗时 7.94s；可进主菜单/加入玩家/过场；ESC 可暂停。但它双人/过场为主，未进入可操作关卡，不作为完整 B 验证。
- 结论：B 轨未完成；需要可单机、键盘、可快速进 gameplay 的第二款游戏，或修复 Brotato 运行库/模拟 DLL。未改引擎；未通关；README 未写。

## 2026-11-03 21:15 死亡上下文

- PolicyRunner 新增 death_context：死亡瞬间记录 scroll/hp/last_hit/action_state/observation/situation/memory；status 暴露，新命重置。
- 实机第一条：scroll -2.388, observation hp1, x=0.049（左边缘）, last_hit before177→after0, grounded, 无 enemy_ahead；说明是“被击退到左角 + 接触/低血”。
- memory context 同帧含 guide + hotspot（s:-5 deaths11, preferred=advance）。
- 未通关；README 未写。

## 2026-11-03 21:25 角落脱困阈值 A/B（负）

- 死亡上下文样本：-2.388/x0.049、-4.13/x0.109、-3.425/x0.075，确认多次死在左边缘；一条 -0.001/x0.28 HP1。
- 把 left-edge 阈值 0.10→0.14 且受击时立即 jump/dash：10 局 4.57/3.82/3.36/2.12/3.65/3.87/1.84/3.93/2.82/3.87；平均 3.39，低于 4.19。
- 结论：更早/更频繁地从角落跳出会破坏节奏；回退。保留 death_context 和原 edge escape。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 21:25 死因落库

- PolicyRunner 将通用死因写入 LevelMemory：cornered/low_hp/hit/unknown（基于 x<0.15、hp<=1、last_hit）。
- 实机 3 条：cause=cornered scroll -4.074 x0.116 hp1；hit scroll -2.027 x0.209 hp2；cornered scroll -3.204 x0.021 hp?。
- LevelMemory causes Counter: {'cornered':2,'hit':1}。
- 结论：死因结构可用；最高频为 cornered，但之前“更早跳角落”A/B 为负，不能简单加反射。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 21:36 edge_escape A/B（关掉更好）

- 关闭 left-edge escape（保留周期 jump=420/dash=800/hold=260）：
  - 第一批 10 局：11.15/5.75/4.05/4.44/4.09/3.96/2.17/3.57/3.56/8.38；平均 5.11。
  - 第二批 10 局：3.32/2.61/3.78/3.29/2.63/7.00/0.00/4.35/4.31/4.62；平均 3.59。
  - 合计 20 局平均 4.35；旧基线 4.19；最高 11.15（历史最高）。
- 结论：edge_escape 没有收益，反而可能打断节奏；已把 profile `combat.edge_escape=false` 固化。仍未通关/未 6.5。
- 未通关；README 未写；驱动关闭。

## 2026-11-03 21:45 edge-off 第三批

- 第三批 10 局：2.81/3.55/3.30/4.39/2.70/4.39/3.87/4.65/4.25/2.90；平均 3.68；全死亡。
- edge-off 三批合计 30 局约 4.13；旧 edge-on 20 局 4.19；平均无差异，只有 11.15 单局高值。
- 结论：edge_escape 开关不是关键；保留 false 只因高值，不宣称提升。仍未通关。

## 2026-11-03 21:55 阶段总结（round 77）

- A：Cuphead Forest Follies 未通关。edge_escape 开关不开/关平均都约 4.1–4.2；最高 11.15 是离群值；20–30 局平均值没有达到 6.5。death_context/causes 已可用（cornered/hit），但“更早跳角落”A/B 为负。
- 已证明无效/无收益：周期/无跳/冲刺参数、engage、turn/static、route macro、shadow top1、grounded gating、hit_dash、edge threshold、在线 action bandit、纯 memorized LevelMemory promotion。
- B：Brotato（steam_api 入口点）、SuperTux beta（启动即退）、SuperTuxKart（下成 macOS .app）、Overcooked（双人/过场）均不适合当前 B 烟测；B 需要可用 Windows 单机游戏。
- 记忆/guide/按关加载/shadow 只读已验证；未通关；README 未写。
- 结论：继续自动调参/开关无法稳定通关；需要新的感知/时机能力或用户决定方向。

## 2026-11-03 23:10 文档合并

- 顶部判断合并到 round 77 阶段总结；后续计划改为 A0–A3 / B 轨 / 停止规则。
- 测试数统一为引擎 **273**、插件 **45**；README/STATUS/MEMORY 同步。
- 脱敏：去掉文档里的本机 Cuphead 路径和用户名路径，改用 `<game-dir>` / `%LOCALAPPDATA%`。
- 仍未通关；README 未写。

## 2026-11-04 16:20 离线 P1/P2（shadow）

- 用户今天无法提供电脑；按约定只做离线部分，不启动游戏。
- 新增 `world_model.py`：space（left/right/ground/edge/gap）、threats（type/side/lane/ttc/telegraph/distance）、self_state（hp/action）；`status.world_model`。
- 新增 `options.py`：OptionSpec（前置/效果/冷却/最短承诺）+ 5 个 option（advance/strafe/jump_over/dash_through/stop_shoot）+ UtilityArbiter（安全否决/迟滞/承诺）；`status.option_shadow`，shadow=true，不执行。
- 机制注册表新增 world_model / option_shadow 计数；`status.mechanisms`。
- 测试 284 passed；未实机，未通关，README 未写。
- 待电脑：验证 world_model/option_shadow 实际每帧更新、A/B、连续 3 批 promotion。

## 2026-11-04 16:45 P3 option canary（默认关闭）

- 新增 `option_canary` 机制：默认 disabled，applied=0；只有 profile `options.execute=true` 且 `canary=<id>` 才执行，且一次只允许一个 option。
- 支持 jump_over/dash_through/strafe_left/strafe_right；前置 gameplay/grounded/非 hurt/冷却/选中选项匹配。
- 测试：286 passed；默认关闭与单次执行均有测试；未实机，不能宣称收益。

## 2026-11-04 17:00 P4 离线工具

- experiment_cli：status→RunMetrics、summary/compare；支持 bootstrap 中位数 CI 与 promote/no_gain/regression。
- 机制完整性测试：默认机制都带 expected_trigger/effect/owner_test；option_canary 默认 disabled；periodic_jump/world_model applied>0；option_canary applied=0。
- 测试：290 passed；未实机。

## 2026-11-04 17:15 机制审计

- mechanism_audit：enabled 期望 vs 实际 applied；disabled 必须 applied=0；缺失机制 fail。
- experiment_cli 增加 audit 子命令；测试 295 passed。
- 未实机；等电脑后先 audit status，再跑 A/B。

## 2026-11-04 17:30 P4 跑批器

- 新增 batch.py：注入式 collect_batch，自动跑 N 局、写 RunMetrics JSONL、每局 audit，返回 summary/audit_failures。
- 不绑定 driver；实机只需注入 start/stop/status/reset/sleep。
- 测试 298 passed；未实机。

## 2026-11-04 17:45 P4 实机入口

- scripts/ab_batch.py：一条命令跑 N 局，自动 apply canary、写 JSONL、每局 audit、输出 summary。
- 用法：baseline / --canary jump_over；不启动 driver 时不会运行。
- 测试 299 passed；未实机。

## 2026-11-04 18:00 数据质量

- status 增加 started_at；metrics_from_status 的 duration 可用。
- canary 边界：非选中 option、冷却重复触发均有测试。
- 测试 300 passed；未实机。

## 2026-11-04 18:15 实验 spec 模板

- 新增 experiments/README.md：目录、spec 字段、3 批判定、跑法、audit。
- 新增 experiments/specs/option-canary-jump-over.json：P4 第一个单机制 canary 设计。
- .gitignore 排除本地 runs/frames/csv；只提交 spec/结论。
- canary 横移先松前进再按方向，避免左右同时按住失效。

## 2026-11-04 18:30 离线 P4 完成，等待电脑

- 离线链路已完整：world_model + option shadow + default-off canary + mechanism counters/audit + batch collector + experiment CLI + spec 模板。
- 测试 300 passed；未启动游戏。
- 唯一剩余：P4 实机 10 局 A/B（baseline vs canary）与连续 3 批 promotion；必须有 Cuphead 窗口 + driver。
- 今天用户无法提供电脑；继续离线只会重复小改动，不制造“进展”。

## 2026-11-05 21:45 P4 第一批结果

- baseline 10 局：mean 3.214 / median 3.383 / max 3.821。
- jump_over canary：audit 失败（enabled 但 applied=0，全 not_selected）→ 不能算行为 A/B。
- dash_through canary：audit 通过，mean 2.708 / median 3.174；compare baseline → no_gain（diff -0.209, CI [-1.491,0.516]）。
- 结论：不 promotion；option_canary 保持默认关闭。下一步先查 shadow 为什么不选 jump_over（world_model 威胁为空？），再试 stop_shoot。
- 仍未通关，README 未写；驱动已关闭。

## 2026-11-05 22:00 P4 jump retest / tracks

- 实机 tracks 有 threat 和 parry；WorldModel 已注入 tracks，能看到 threat。
- 但 option_shadow 仍选 strafe_right（commit），jump_over 未选中；jump canary 第二次 audit 仍 applied=0。
- dash canary 有效但 no_gain；不 promotion。
- 根因方向：选项选择/承诺/动作状态，不是感知完全为空。
- 测试 301 passed；驱动关闭；未通关。

## 2026-11-05 22:10 P4 首批完成

- jump_over 修复：允许空中选中，canary 落地才执行；解决 periodic_jump 占满 grounded 的问题。
- jump canary audit 通过，median 3.483 vs baseline 3.383；diff +0.10，CI [-1.35,0.42] → no_gain。
- dash canary audit 通过，median 3.174 → no_gain。
- 两个有效机制都未达 promotion 阈值；option_canary 保持默认关闭。
- 测试 301 passed；驱动关闭；未通关，README 未写。

## 2026-11-05 22:05 P4 首批最终

- stop_shoot canary 未触发（not_selected）；summary median 3.036。
- 有效 canary：dash（median 3.174）/ jump（median 3.483，CI 跨 0），均 no_gain。
- 无 promotion；option_canary 默认关闭。
- 结论：单机制 canary 不足以提升；下一步改选项选择/Arbitrator，不再逐个 option 试。
- 测试 301；驱动关闭；未通关，README 未写。

## 2026-11-05 22:15 option_stats

- UtilityArbiter 增加 per-option selected/rejected/reasons，status.option_stats。
- 实机 8s：advance 61 / jump 61 / dash 60 / stop 51；stop 不是选不中，而是 canary 不支持执行 stop_shoot。
- 结论：P4 no_gain 不是“没选中”，而是单机制执行不足；下一步改选择/仲裁或支持 stop 执行。
- 测试 302 passed；驱动关闭；未通关。

## 2026-11-05 22:15 P4 stop 最终

- 补 stop_shoot 执行（松前进 250ms），但跑批仍 not_selected；summary median 2.839。
- P4 首批：dash/jump 有效 no_gain；stop 不稳定选中；无 promotion。
- 测试 303 passed；驱动关闭；未通关，README 未写。
- 下一步：改选择/仲裁，不再逐个 option 试。

## 2026-11-06 11:20 Stage 0/1/2 离线完成

- Stage 0 留痕/复盘：perception_health、damage_events、trace_tail、traces 落盘、Markdown 报告。
- Stage 1 感知修复：大跳变两拍共识、过期玩家不清空 tracks、实时 anchor 过滤、parry 纳入/贴身过滤；短测 stale 14.2%、threat 100%。
- Stage 2 反应式模式：默认关闭 `combat.reactive_mode`；开启后禁周期盲跳/盲冲，由 reactive_control 按 ttc/距离触发 dash/jump/stop_shoot，带冷却与机制计数。
- 测试 310 passed；未实机验证 Stage2；未 10 局批次；未通关，README 未写；用户要求暂不控制电脑。

## 2026-11-06 11:59 Stage 3 首批结果

- baseline 10 局：median 2.551，p10 1.493，stale 0.256，threat 0.993。
- reactive 10 局（ttc=None 优先跳修正后）：median 1.936，p10 1.481，stale 0.192，threat 0.988。
- compare no_gain（median -0.615，CI [-1.065,0.048]）；感知修复有效，但纯反应式没有超过周期跳基线。
- 已生成并入库 experiments/results/v21-*.md；完整 traces 本地。
- 下一轮：Hybrid 保底跳 或 玩家初始捕获；不再重复相同 reactive 批次。
- 测试 312 passed；未通关，README 未写。

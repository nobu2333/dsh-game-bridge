# 现状（STATUS）

> 唯一的状态源。更新：2026-11-12。
> 设计理由看 [DESIGN](DESIGN.md)，键名看 [CONTROLS](CONTROLS.md)，发布看 [RELEASE](RELEASE.md)。
> 其他文档与本文冲突时，以本文为准。

## 一句话

`dsh-game-bridge` 是给 DeepSeek Harness（DSH）用的 npm 插件，提供看游戏（抓屏 + OCR）和
操作游戏（键盘 / 鼠标 / 虚拟手柄）的工具。**由模型决定怎么玩，插件只负责看清楚、按得准、守住安全边界。**
仅支持 Windows，默认 dry-run（只记录，不注入）。

## 方向与范围（2026-11-12 确定）

**目标游戏：慢节奏游戏**，也就是模型每次决策花 5–10 秒也不影响结果的游戏：

- 回合制 / 益智：2048、扫雷、数独、纸牌、棋类；
- 菜单重、节奏慢：视觉小说、模拟经营、放置类、回合制策略 / RPG。

**不做：需要实时快速反应的游戏**（动作、平台跳跃、弹幕、竞速、FPS）。原因：

- 模型一次决策实测约 9 秒（2026-11-02），进不了实时控制环；
- 在 Cuphead 上花了 2026-10-30 到 11-06 一整段时间，用本地启发式视觉 + 60 Hz 策略做实时玩法，
  三组 10 局对照全部没有收益（见下文「历史结论」）。只靠像素做实时玩法属于研究问题，
  超出一个插件该承担的范围。

**判断标准**：每一项新工作都要回答「它是否让**模型**通过工具把慢节奏游戏玩得更好」。
所有玩法证据都要和随机 / 固定按键的对照组比，赢不了对照组就不算。

## 现在有什么（已验证）

| 能力 | 状态 | 证据 |
|:--|:--|:--|
| 插件壳：14 个 `game_*` 工具、截图作为 image block 进模型 | ✅ | `npm test`；隔离 harness 集成测试 |
| 引擎自举：uv 建 venv 并安装 `dsh-game-core` | ✅ | 实测约 20 秒 / 17 个包 |
| 抓屏：整屏抓取 + 窗口裁剪（默认） | ✅ | 实测；被遮挡时会拍到遮挡物，有 `foreground` / `occluded` 标注 |
| 抓屏：窗口级 `PrintWindow`（`DSH_GAME_BRIDGE_CAPTURE=window`） | ✅ | 实测 Cuphead / Chrome 窗口被遮挡时也能截到；部分硬件加速窗口可能是黑帧 |
| OCR（RapidOCR） | ✅ | 实测中英文菜单、分数 |
| 键盘注入（SendInput，扫描码） | ✅ | 2026-10-29 用 AsyncKeyState 回读；2026-11 在浏览器游戏上实测 |
| 手柄注入（vgamepad / ViGEmBus） | ✅ | 2026-10-29 用 XInput 回读；槽位可能不是 0 |
| 鼠标点击（`game_act` 加 `x` / `y`） | ✅（有坑） | 实测能点到窗口；**坐标是屏幕绝对坐标**，见「下一步」第 3 项 |
| 安全：反作弊拒绝、F12 夺回、真实后端审批、前台校验、审计日志 | ✅ | 引擎单测 + 集成测试 |
| 发布 | 0.0.1 已发布 | npm `dsh-game-bridge@0.0.1`、PyPI `dsh-game-core==0.0.1`；0.0.2 尚未发布 |

**还没有的证据（最关键）**：从来没有一次是 DSH 模型通过插件工具从头到尾玩完一局游戏。
到目前为止，所有游玩记录都来自直接调用引擎的 Python 脚本。

## 能力层与代码去向

插件的能力分 8 层，每层对应不同的文档。2026-11-12 逐层对照代码后的结论如下。
**先读对应文档再动对应代码**；表里写「保留」不代表已经可用，「现状」一列是实际核对过的。

| # | 能力层 | 文档 | 去向 | 现状 |
|:--|:--|:--|:--|:--|
| 1 | 基础设施：抓屏、OCR、输入、安全闸、自举、发布 | [DESIGN](DESIGN.md)、[CONTROLS](CONTROLS.md)、[RELEASE](RELEASE.md)、[MARKETPLACE](MARKETPLACE.md)、[FIELD-2026-10-29](FIELD-2026-10-29.md) | **保留，主线** | 已验证（见上表） |
| 2 | 世界状态与档案：WorldState、GameProfile | [STATE](STATE.md) | **保留**（可选工具 `game_state` / `game_memory`） | 场景 / HP / UI 文字通用；威胁与实体检测偏动作游戏 |
| 3 | 实时战斗栈：60 Hz 策略、选项仲裁、玩家与实体追踪、地形 | 无现行文档；设计与失败记录见下方「已删除文档」 | **冻结** | 在 Cuphead 上验证无收益 |
| 4 | 记忆与学习 | [MEMORY](MEMORY.md) | **拆分**：通用部分保留并待重做，动作游戏部分存档 | 架构通用；游戏级记忆（M2–M5）只有读取代码，没有写入 |
| 5 | 冷启动与自动认键位 | [AI-NATIVE-PLAN](AI-NATIVE-PLAN.md)、[GENERAL-PLUGIN-V3](GENERAL-PLUGIN-V3.md) §5 | **保留，待收敛**（有两代重复实现） | 第一代未接入生产；第二代只在脚本里用 |
| 6 | GamePack（每款游戏的声明式数据） | [GENERAL-PLUGIN-V3](GENERAL-PLUGIN-V3.md) §4 | **保留合同**，覆盖指标作废 | 合同和校验可用；T1 / T2 计数不代表能力 |
| 7 | 实验与评测 | [experiments/README](../experiments/README.md) | **存档**，方法论保留 | 实现绑定 Cuphead 的「推进屏数」指标 |
| 8 | 模型回路：Intent、VLM 观察、模型复盘 | 无现行文档 | **冻结** | 新路线里模型直接读截图，用不上 |

### 各层的代码

**第 3、8 层（冻结）**：不再开发，不作为能力对外宣传；单测照常运行。
- `policy.py`、`arbiter.py`、`options.py`、`planner.py`、`situation.py`、`temporal.py`、`world_model.py`、
  `player_tracker.py`、`tracking.py`、`terrain.py`、`candidates.py`、`observation.py`、`contracts.py`、
  `mechanisms.py`、`vlm_observation.py`、`instant_play.py`
- 工具：`game_policy`、`game_intent`

**第 4、5、6 层（保留，待重新对齐）**：
- 记忆通用部分：`memory_loader.py`、`memory_context.py`、`memory.py` 里的 `GuideStore`
- 认键位第二代：`probe.py`、`onboarding.py`；GamePack：`gamepack.py`
- 通用录制：`recorder.py`（把一局记成时间线，M5 的证据需要它）
- 认键位第一代（**与第二代重复，未接入生产**）：`game_probe.py`、`controls_probe.py`、`effect_classifier.py`、
  `priors.py`、`coldstart.py`。收敛方案见 [DESIGN § 9](DESIGN.md#9-待定游戏数据与记忆的收敛)，在方案定下之前不要新增代码。

**第 4、7 层里只属于动作游戏的部分（存档，不再开发）**：
- 记忆：`level_memory.py`、`memory.py` 里的 `KnowledgeStore` / DangerCard / `LevelLocator`、
  `entity_memory.py`、`learner.py`、`experience.py`
- 评测：`evaluate.py`、`review.py`（读 DangerCard 和 episode）
- 通用统计（保留）：`experiment.py`（bootstrap 中位数差、promote / no_gain / regression 判定），M5 的对照组比较可以用它
- 通用脚本（保留）：`baseline.py` + `scripts/run_baseline.py`（M5 对照组）、`scripts/record_model_run.py`（模型局记分）、
  `autoplay.py` + `scripts/play_pack.py`、`scripts/auto_onboard.py`、`scripts/probe_game.py`、`scripts/serve_webgl.py`

### 2026-11-12 清理记录

已删除（没有任何生产调用，全部绑定 Cuphead 实时玩法或已作废的 T1 / T2 指标，对应的单测一并删除）：
`batch.py`、`mechanism_audit.py`、`experiment_cli.py`、`coverage.py`、`memory_report.py`、`scripts/ab_batch.py`。
可从提交 `a266676` 取回。

**保留（2026-11-12 决定）**：
- `evaluate.py`、`review.py`：读 DangerCard，`review` 的「把一局压缩成模型可读的复盘包」思路 M5 之后可能有用；
  **M5 不使用这两个模块**，也不把它们接进任何工具；
- `vlm_observation.py`：DSH 的模型可以直接看图（用户确认），这个模块将来是否用得上再说；
- `game_policy`、`game_intent` 和它们依赖的一整套（`policy.py` 及记忆 / 学习 / 追踪模块）：**先保留，不清理**。
  这两个工具是「本地 60 Hz 策略 + 低频战术建议」：模型给 Intent（推进 / 撤退 / 避免 / 攻击，带 TTL），
  本地循环逐拍执行并做闪避、脱困。它们属于已冻结的实时路线，M5 用不到；删它们要拆 `policy.py` 和它的依赖，
  暂时不动。

### 已删除的文档

下面这些设计 / 规划文档在 2026-11-12 从工作区移除，全部可以从提交 `a266676` 取回，例如
`git show a266676:docs/PROJECT-STRATEGY.md`：

| 文档 | 内容 | 对应层 |
|:--|:--|:--|
| `OPTIMIZATION-PLAN.md`、`OPTIMIZATION-PLAN.v2.md` | Cuphead 实时玩法的优化方案（实体级感知、技能库、阶段路线） | 3 |
| `STRATEGY-V2.md` | 选项 + 效用 + 承诺的策略设计、量化验证协议、v2.1 复盘 | 3、7 |
| `PROJECT-STRATEGY.md` | 「看、玩、学」总方案：WorldState、DangerCard、模型复盘 | 2、3、4、8 |
| `RUN-STATE.md`、`HANDOFF.md` | 逐日运行记录和交班（含大量 Cuphead 实机数据） | 历史 |
| `AUDIT.md` | 0.0.1 发布前审计 | 1 |
| `MIGRATION.md` | 把引擎复用到另一个本地项目的建议（结论：不迁移，保持两条独立代码线） | 1 |

`MEMORY.md`、`AI-NATIVE-PLAN.md`、`GENERAL-PLUGIN-V3.md` 保留在工作区，顶部有范围说明，标出哪些部分仍然适用。

## 下一步（M5：模型自己玩完一局）

玩法协议见 [PLAY](PLAY.md)。按顺序做，前一项没完成不开始下一项：

1. **端到端演示（2048，只用方向键）**：真实 DSH 会话加真实模型，只用 `game_attach` / `game_snapshot` /
   `game_act` / `game_stop`，打完一局并录屏。2048 不需要鼠标，所以不被下面第 3 项阻塞。
   **这一步需要你本人跑 DSH**，操作步骤和给模型的提示词在 [M5-RUNBOOK](M5-RUNBOOK.md)。
2. **对照组**：同一款游戏上跑随机按键 / 固定循环，各 5 局，比较得分。模型赢过对照组才算 M5 完成。
   工具已就绪：`scripts/run_baseline.py`（随机 / 固定循环，每局新开浏览器 profile），
   `scripts/record_model_run.py`（从模型那局的窗口 OCR 读分，和基线用同一个解析器）。
   2026-11-12 已在本机用真实键盘注入跑通（每步约 0.2–0.3 秒，分数读取稳定）。
3. **点击类游戏的前置缺口**（扫雷、纸牌这类要点击的游戏需要）：
   - `game_act` 的 `x` / `y` 目前是屏幕绝对坐标，要改成相对截图的坐标，由引擎换算；
   - `game_snapshot` 只把 OCR 的**文字和置信度**写进文本，**没有文字框坐标**，而且最多 12 行；
     需要补上归一化的框坐标，模型才能「点那行字」。
4. **发布 0.0.2**，按 [MARKETPLACE](MARKETPLACE.md) 提交市场收录。

**在做下面这些之前先停下**：新的感知模块、学习层、动作游戏适配、新的游戏覆盖指标，以及任何新的「每款游戏的数据格式」。
游戏数据与记忆怎么收敛，先在 [DESIGN § 9](DESIGN.md#9-待定游戏数据与记忆的收敛) 定下来。

## 已知限制

- 仅支持 Windows 10/11；
- 默认抓屏方式在窗口被遮挡时拍到的是遮挡物；窗口级抓屏要手动开，部分游戏会返回黑帧；
- 真实后端只对前台窗口生效，插件不会自动把游戏切到前台；
- 虚拟手柄可能落在 XInput 槽位 1 以上（也就是 2P），部分游戏不认；
- 鼠标坐标是屏幕绝对坐标，`game_snapshot` 不返回 OCR 文字框坐标（见「下一步」第 3 项）；
- `approval: never` 的部署无法使用真实后端（attach 会被自动拒绝）；
- 机器上需要安装 `uv`。

## 验证

```powershell
npm test                                   # 插件：45/45（2026-11-12 实跑）
cd engine; python -m pytest tests -q       # 引擎：351/351（2026-11-12 实跑）
cd ..
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # 集成 11 条；最近一次 11/11 是 2026-10-30，之后没有重跑
```

## 历史结论（只记结论，不再展开）

- **2026-10-29 发布 0.0.1**：真实抓屏 / OCR / 注入链路打通，首次实机记录见 [FIELD-2026-10-29](FIELD-2026-10-29.md)。
- **2026-10-30 至 11-06，Cuphead 实时玩法**：WorldState、60 Hz 策略、玩家追踪、记忆和学习层都做了。
  单局最好推进 11.15 屏（离群值；20–30 局平均约 4.1–4.2 屏），从未通关。v2.1 三组各 10 局对照
  （每局上限 75 秒，中位数 baseline 2.55 屏 / reactive 1.94 / hybrid 2.11），
  全部没有收益；感知指标改善了，策略表现没有跟着提升。报告见 `experiments/results/v21-*.md`。
- **2026-11-09 至 11-11，v3「跨游戏覆盖」**：新增 GamePack、窗口级抓屏、鼠标点击、自动探针。
  宣布的 T1/T2 大多依赖手写 pack；两个「5 分钟游玩」实际是固定节拍按键循环，不代表有玩法能力。
  唯一一次零手写接入是 Dino（只需按空格），SuperTux 的自动接入失败。该路线已停止。
  证据在 `experiments/games/`。

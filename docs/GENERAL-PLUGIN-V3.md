# 通用游戏插件 v3：GamePack + 自动探针 + 分层感知

> 状态：**active / 方案稿**（2026-11-09）
> 目标读者：后续负责实现的模型/开发者。
> 目标：让 DSH 通过 `dsh-game-bridge` **以尽可能少的游戏专用代码，游玩尽可能多的游戏**。
> 本文是方向文档；测试数字、实机证据仍以 [RUN-STATE.md](RUN-STATE.md) 和 `experiments/results/` 为准。

## 0. 先 review 上一版计划

上一版（Cuphead 垂直切片 + 参数/记忆/学习 A/B）不是没有价值，但它**把“一个游戏的深度”当成了总目标**。

保留：

- 通用抓屏/OCR/输入/录制/回放/实验/trace；
- 引擎与游戏 profile 分离；
- 主模型不进 30Hz 快环；
- 不伪造通关、负结果入库；
- PlayerTracker、机制审计、bootstrap CI。

必须修正：

1. **KPI 从 Cuphead 通关改为覆盖广度**。Cuphead 10/7 只保留为 depth regression，不再是 v3 的完成条件。
2. **不是“一个 policy 打所有游戏”**，而是“通用核心 + 类型适配器 + 每游戏 GamePack”。
3. **不要先上重感知模型**。先做 OCR/UI/状态/探针；检测器/世界模型只在需要时加。
4. **不要一上来要求 5 款游戏**。先 3 款不同类型 T1、2 款 T2，再扩。
5. **不要把 Go-Explore 当通用核心**。它是平台探索适配器，不是所有游戏的默认解法。
6. **不要继续 Cuphead 参数扫描**。它已经证明边际收益接近 0。

新增（参考成熟方案后）：

- **GamePack**：每款游戏一个可验证的数据包，声明能力/键位/状态/配方/证据；
- **自动探针/因果标定**：按键→画面/状态变化，自动找玩家位置和键位，不靠人工示范；
- **分层观测 L0/L1/L2**：像素 / OCR+UI+帧差 / 结构化状态；
- **本地技能原语 + action reflection**：navigate/evade/interact，动作后判断 progressed/blocked/damaged/no_effect；
- **游戏矩阵**：按类型覆盖，而不是按单游戏深度。

## 1. 目标与非目标

### 1.1 本阶段目标

在**零人工示范**的前提下，建立通用接入层，并达到：

- **3 款不同类型游戏 T1**：attach、抓屏、菜单/键位识别、首个有效动作；
- **2 款游戏 T2**：连续 5 分钟有意义游玩（不要求通关）；
- 新游戏接入不修改引擎代码，只新增/生成 GamePack；
- 测试、文档、证据、推送齐全；
- Cuphead 只做 depth regression，不阻塞本目标。

### 1.2 非目标（本阶段不做）

- 不承诺“任意 3D 动作游戏 Boss 战”；
- 不读游戏内存、不注入 DLL、不做 mod；
- 不接带 EAC/BattlEye/Vanguard/Ricochet 等反作弊的在线游戏；
- 不要求所有游戏通关；
- 不把主模型放进 1–2Hz 以上的控制环；
- 不为单款游戏写引擎分支。

## 2. “会玩”的分层

| 层级 | 能力 | 验证 |
|:--|:--|:--|
| T0 | attach、抓屏、窗口/前台/DPI | `game_attach` + snapshot |
| T1 | 菜单导航、键位映射、首个有效动作 | 5 分钟内完成；无需人示范 |
| T2 | 5 分钟有意义游玩 | 有推进/交互/存活，不是菜单空转 |
| T3 | 通关第一关/第一个 Boss | 单游戏深度 |
| T4 | 稳定重复（如 10 局 ≥7） | 可选，只对少数游戏 |

**覆盖指标**：`coverage@T1`、`coverage@T2`，而不是单一 best progress。

## 3. 架构

```text
┌─────────────────────────────────────────────────────┐
│ DSH（慢环，8–60s）                                  │
│  目标 / 规划 / 写 recipe / 生成 GamePack / 复盘      │
└───────────────────────┬─────────────────────────────┘
                        │ intent / pack / review
┌───────────────────────▼─────────────────────────────┐
│ 通用核心（不认游戏名）                              │
│  capture / OCR / input / record / replay / safety    │
│  action scheduler（非阻塞、毫秒级）                  │
│  GamePack loader / capability registry              │
│  experiment / trace / evidence                       │
└───────────────────────┬─────────────────────────────┘
                        │ capabilities
┌───────────────────────▼─────────────────────────────┐
│ 类型适配器（通用算法，不写游戏名）                  │
│  menu_ui / platformer / action_combat / turn_based   │
│  navigation / puzzle                                  │
└───────────────────────┬─────────────────────────────┘
                        │ primitive actions
┌───────────────────────▼─────────────────────────────┐
│ 本地快环（20–30Hz）                                  │
│  observe → primitive → reflect → memory              │
│  不让 LLM/VLM 进这个环                               │
└─────────────────────────────────────────────────────┘
```

### 3.1 分层观测

| 层 | 内容 | 延迟 | 用途 |
|:--|:--|:--|:--|
| L0 像素 | 原始帧、模板、帧差 | 5–30ms | 兜底、跟踪、运动威胁 |
| L1 语义 | OCR、UI、图标、HUD、音频事件 | 20–200ms | **主力层**：菜单/血条/提示/交互 |
| L2 结构化 | 模拟器内存、官方 API、静态数据文件 | <10ms | 有则用，无则降级 |

原则：**能用 L1 就不上 L0 大模型；能用 L2 就不猜像素**。

### 3.2 时间尺度

- **20–30Hz**：本地原语、躲避、移动、UI 焦点；
- **1–5Hz**：战术选择、目标切换、威胁分类；
- **8–60s**：DSH 规划、写 recipe/code、看 trace、生成 pack。

主模型 8–9s 的延迟不是缺陷，只要它不进快环。

## 4. GamePack：通用接入的合同

每款游戏一个 pack；引擎只读能力，不认游戏名。

```json
{
  "schema": 1,
  "id": "pc.example.game",
  "title": "Example Game",
  "platform": "pc",
  "process": "example.exe",
  "trust": {"anti_cheat": "none"},
  "capabilities": {
    "observe.screen": {"level": 0},
    "observe.ui": {"level": 1},
    "observe.state": {"level": 0},
    "control.keyboard": {"level": 1, "keymap": "wasd_zx"},
    "control.mouse": {"level": 0}
  },
  "controls": {
    "move": {"left": "A", "right": "D", "up": "W", "down": "S"},
    "confirm": ["Z", "ENTER"],
    "cancel": ["ESC"],
    "attack": ["X"]
  },
  "hud": {
    "hp": {"box": [0.0, 0.88, 0.22, 0.12], "prefix": "HP"}
  },
  "recipes": [
    {
      "id": "start_game",
      "intent": "从主菜单进入游戏",
      "steps": ["confirm", "wait:800", "confirm"],
      "verify": {"scene": "gameplay"}
    }
  ],
  "evidence": ["experiments/results/example-t1.md"],
  "eval": ["experiments/games/example/replay.jsonl"],
  "level": 1
}
```

规则：

- `anti_cheat` 不为 `none` → 拒绝加载；
- 声明 level ≥1 的能力必须能执行/验证，否则降级；
- pack 只放数据，不放可执行代码；recipe 是声明式步骤；
- 本地路径/录像/账号不外传；
- 游戏版本变化 → pack 标 `stale`，降级到 T0/T1。

### 4.1 能力词汇（v0）

| 能力 | 含义 |
|:--|:--|
| `observe.screen` | 抓屏 + OCR + 帧差 |
| `observe.ui` | 菜单/图标/焦点/提示 |
| `observe.state` | 结构化状态（可选） |
| `control.keyboard` / `control.mouse` / `control.gamepad` | 输入通道 |
| `control.player1` | 控制 1P |
| `pause` / `reset` / `replay` | 通用操作 |

### 4.2 初步实现

- `engine/dsh_game_core/gamepack.py`：schema v0 校验、anti-cheat fail-closed、capability level、recipe 唯一性、`profile_from_pack` 适配（单测 `engine/tests/test_gamepack.py`）。
- `GameSession.attach/policy_start` 接受 `pack`（路径或内联对象），`status` 暴露 pack 摘要；`game_attach` / `game_policy` 工具面也已支持 `pack`。
- `experiments/games/matrix.json`：首批游戏矩阵与 T1/T2 目标。
- 下一步：自动 onboarding 探针、键位/HUD 自动生成 pack、3 款 T1 验收。

## 5. 自动 onboarding（不靠人示范）

目标：新游戏 5 分钟内达到 T1。

1. **识别窗口/引擎**：进程、标题、分辨率、DPI、前台；
2. **OCR/UI 扫菜单**：START/CONTINUE/OPTIONS/PLAY 等关键词；
3. **键位探针**：发短脉冲（方向/确认/取消/攻击），对比画面变化/菜单跳转；
4. **因果标定**：连续方向脉冲 → 帧差运动块 → 找“哪块像素是我”；
5. **HUD 探针**：OCR 血条/分数/计时区域，建立 HUD box；
6. **生成 pack 草稿** → 跑 T1 checklist → 证据入库；
7. 失败则降级/记录，不硬编码。

这层是“通用插件”的核心；GamePack 是它的产物，不是手写配置的终点。

## 6. 游戏矩阵（初始）

| 游戏 | 类型 | 输入 | 目标 | 备注 |
|:--|:--|:--|:--|:--|
| Cuphead | 2D 动作/平台 | 键盘 | T2 regression | 已有深度；只做回归，不调参 |
| SuperTux | 2D 平台 | 键盘 | T1→T2 | 已有 profile/烟测；场景 OCR 需修 |
| Block Blast | 益智/点击 | 鼠标/触屏 | T1→T2 | 本地 Unity/WebGL 资产；低风险 |
| NES Battle City（RetroArch） | 模拟器/俯视 | 键盘 | T1（可选 T2） | 有结构化状态潜力；需确认模拟器可用 |
| 其他单机 | 待定 | 待定 | T1 | 排除反作弊/在线竞技 |

先做 **3 款 T1**（至少覆盖 2 种输入/2 种类型），再选 **2 款 T2**。
Cuphead 可以占一个 T2 名额，但不再做 10/7 的深度调参。

## 7. 阶段与门禁

### P0：基线/合同（1 周）

- 冻结 Cuphead 参数；
- 写 GamePack schema + 示例；
- 建游戏矩阵与 T0/T1 checklist；
- 记录首批 3 款游戏的 attach/菜单/键位现状；
- 验收：文档 + schema + 3 款游戏 T0 证据。

### P1：自动 onboarding（2 周）

- 键位探针、OCR/UI 菜单、因果标定；
- 每款游戏生成 pack 草稿；
- 验收：**3 款不同游戏 T1，零人工示范**。

### P2：本地原语 + T2（3 周）

- navigate/confirm/cancel/attack/evade 原语；
- action reflection（progressed/blocked/damaged/no_effect）；
- 2 款游戏连续 5 分钟有意义游玩；
- 验收：T2 证据 + 无引擎游戏分支。

### P3：扩展（后续）

- 5+ 款 T1；3 款 T2；
- 平台游戏可接 Go-Explore-lite；
- 动作游戏再评估起手识别；
- 3D 动作只做单 Boss 单阶段研究，不承诺全流程。

## 8. 指标

- `coverage@T1` / `coverage@T2`；
- `time_to_control`（attach → 首个有效动作）；
- `first_effective_action` 成功率；
- 人工介入次数（目标 0）；
- action efficacy（progressed/blocked/damaged/no_effect）；
- 引擎游戏分支数（目标 0）；
- 测试：pytest/plugin/integration；
- 证据：pack + replay + 结果报告。

## 9. 风险与停止规则

- 游戏不可用/反作弊 → 换游戏，不硬啃；
- auto-onboarding 5 分钟做不到 → 先降级 T1 定义，不伪造；
- 某游戏 2 周无 T1 → 标记 blocked，换下一款；
- 不新增机制除非有测试 + 证据；
- 不再用 best run 代表能力；
- Cuphead 10/7 不阻塞本阶段。

## 10. 参考

- **PlayerTwo / Universal Play / GamePack**（本项目作者的既有设计）：能力分层、输入↔画面标定、GamePack、action reflection、音频事件。
- [Cradle](https://github.com/BAAI-Agents/Cradle)（[论文](https://arxiv.org/abs/2403.03186)）：截图+键鼠、通用电脑控制、技能/自反思；但延迟高，只做慢环。
- [Voyager](https://github.com/MineDojo/Voyager)：代码即技能、技能库、自我验证；适合 DSH 作为“写技能”的慢环。
- [Go-Explore](https://arxiv.org/abs/1901.10995)：自生成轨迹档案、回到状态再探索；平台适配器可选用。
- [CupheadAI](https://github.com/TremorPulse/CupheadAI)：目标检测 + RL 的动作游戏尝试；参考架构，不视为已验证结果。
- [DreamerV3](https://github.com/danijar/dreamerv3) / [DIAMOND](https://github.com/eloialonso/diamond)：世界模型；后续可选，不是第一版。

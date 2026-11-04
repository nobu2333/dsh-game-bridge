# 策略 v2：从“反射规则汤”到“选项 + 效用 + 承诺 + 量化验证”

> 状态：设计 + 最小实现计划。目标不是再调一个参数，而是把局内策略升级为可解释、可验证、可量化的分层系统。
> 约束：引擎不认游戏名/关卡名；游戏差异只进 profile；主模型 p95≈9s，只做低频姿态/事件驱动。

## 0. 结论

77 轮实机后，A 轨（Cuphead Forest Follies）仍是 20–30 局平均 **4.1–4.2 屏**，最高 11.15 为离群值，未通关。
继续调 `jump/dash/engage/edge` 参数或增加反射 if，已验证没有稳定收益。

根因不是“规则数量不够”，而是当前策略形态不对：

- 没有显式选项（Option）；
- 没有安全否决 + 效用仲裁；
- 没有承诺/冷却/终止；
- 没有空间模型与短时预测；
- 记忆/shadow 只能旁路，无法正确参与仲裁；
- 没有“机制是否真的生效”的运行时证据；
- 没有可重复的 A/B 统计结论。

## 1. 调研：可借鉴的方案

| 方案 | 代表工作 | 能借什么 | 不能借什么 |
|:--|:--|:--|:--|
| Utility AI | Dave Mark, GDC 2010 | 选项打分、曲线、安全否决 | 仍需要选项/感知 |
| GOAP | F.E.A.R. (Jeff Orkin) | 前置/效果、短序列规划 | 实时重规划开销 |
| Behavior Tree | Halo / `py_trees` | 优先级、序列、冷却、中断 | 不做数值优化 |
| Subsumption | Brooks 1986 | 分层抑制、安全层最高 | 无学习 |
| Options / SMDP | Sutton, Precup & Singh 1999 | 技能有起止/终止/组合 | 需要手工/学习选项 |
| MPC | 机器人/自动驾驶 | 0.5–1.5s 动作效果预测 | 需要动作模型 |
| MuZero | DeepMind 2020 | 学世界模型 + 规划 | 训练成本高 |
| TD-MPC2 | 2023 | 潜空间 MPC，样本效率较高 | 工程复杂，先不接 |
| AlphaStar | DeepMind 2019 | 分层 RL + 模仿 + league | 单游戏、超大算力 |
| OpenAI Five | 2019 | 大规模 self-play | 不可迁移到单机插件 |
| SIMA | DeepMind 2024 | 指令条件、多游戏泛化 | 闭源、低频 |
| Cradle | BAAI-Agents | 技能库、记忆、自我验证 | VLM 延迟，不适合快环 |
| Voyager | MineDojo | 自动课程、技能库、代码技能 | 仅 Minecraft |
| Gato | DeepMind 2022 | 通用 token 策略 | 数据/算力不可复现 |
| Mario AI / platformer search | 学术基准 | 平台动作的搜索/评估指标 | 多针对模拟器 |

**选择**：游戏工业的 **Utility AI + GOAP/BT** 做仲裁；学术的 **Options + 短时 MPC** 做技能与预测；Cradle/Voyager 的 **技能库/记忆/验证** 做长期学习。AlphaStar/SIMA 只作为方向证据，不直接复刻。

参考链接：

- Utility AI: https://www.gdcvault.com/play/1012410/Improving-AI-Decision-Modeling-Through
- F.E.A.R. GOAP: https://web.archive.org/web/20170713093117/http://alumni.media.mit.edu/~jorkin/gdc2006_orkin_jeff_fear.pdf
- Behavior trees: https://github.com/splinteredlogic/py_trees
- Options: https://people.cs.umass.edu/~barto/courses/cs687/Sutton-Precup-Singh-AIJ99.pdf
- TD-MPC2: https://github.com/nicklashansen/tdmpc2
- MuZero: https://www.nature.com/articles/s41586-020-03051-4
- AlphaStar: https://www.nature.com/articles/s41586-019-1724-z
- OpenAI Five: https://arxiv.org/abs/1912.06680
- SIMA: https://deepmind.google/discover/blog/sima-generalist-agent/
- Cradle: https://github.com/BAAI-Agents/Cradle
- Voyager: https://github.com/MineDojo/Voyager
- Gato: https://arxiv.org/abs/2205.06175

## 2. 目标架构

```text
WorldModel（30–60Hz 更新，纯观测）
  ├─ space: left/right, ground, edges, platform
  ├─ threats: type, side, lane, ttc, telegraph, targetable
  └─ self: hp, action_state, cooldowns, resources
        ↓
ModeController（2–5Hz，带迟滞）
  traverse / combat / evade / recover / explore
        ↓
OptionLibrary（每个 option 有前置/执行/终止/冷却）
  advance / strafe_left / strafe_right / jump_over
  dash_through / stop_shoot / retreat / wait / recover
        ↓
UtilityArbiter（10–20Hz）
  1) safety veto（坑/弹幕必中/HP 危险/受击硬直）
  2) utility（progress / survival / damage / resource）
  3) commitment（最短持续时间、冷却、迟滞）
        ↓
SkillExecutor（30–60Hz）
```

核心规则：

1. 安全是**硬否决**，不是加分项；
2. 一次只选一个 option；
3. option 有最短承诺时间，避免逐拍抖动；
4. 模式切换有迟滞（进入 2 帧、退出 5 帧之类，参数化）；
5. 记忆/攻略只改效用/先验，不直接发按键；
6. 主模型只改 mode/risk，不进逐帧环。

## 3. 最小 v2（先做，不一次做全）

### Option 合约

```python
class Option:
    id: str
    preconditions: list[str]     # 例：grounded, hp>1, threat_ttc>0.4
    enter(ctx) -> None
    tick(ctx) -> Action
    terminate(ctx) -> bool       # 完成/失败/超时
    cooldown_ms: int
    min_commit_ms: int
```

### 先实现 5 个通用 option

- `advance`：持续前进 + 射击；
- `strafe_left/right`：有空间时横移；
- `jump_over`：威胁/坑在前方且可跳；
- `dash_through`：威胁 ttc 短、可穿过；
- `stop_shoot`：近身/需要清场时停步输出。

### 先实现 3 层仲裁

1. safety veto：HP 危险、坑/边缘、必中弹幕、受击硬直；
2. utility：`w1*progress + w2*survival - w3*damage_risk + w4*resource`；
3. commitment：`min_commit_ms` 内不换 option，除非 safety veto。

### 接入顺序

1. 只 shadow：option 选择只记录，不执行；
2. 替换一个最差机制（例如 edge escape）做 canary；
3. 10 局 A/B，通过才扩大；
4. 每次只允许一个机制进入执行路径。

## 4. 完整检测机制（机制必须自证生效）

每个机制必须有：

```yaml
id: edge_escape
description: 左边缘脱困
enabled_config: combat.edge_escape
expected_trigger: x < 0.10 且持续 0.5s
preconditions: [gameplay, scene_ok]
effect: jump+dash 一次
counters: [evaluated, triggered, applied, vetoed, noop, error]
last_reason: string
owner_test: tests/test_policy.py::test_edge_escape
```

运行时统计（`status.mechanisms`）：

```json
{
  "edge_escape": {
    "evaluated": 1200,
    "triggered": 3,
    "applied": 2,
    "vetoed": 1,
    "noop": 0,
    "error": 0,
    "last_reason": "cooldown"
  }
}
```

判定“生效”的最低证据：

1. **配置生效**：开关关闭时 `applied == 0`，且对应按键计数为 0；
2. **触发正确**：`triggered` 的前置条件在测试中可构造；
3. **执行正确**：`applied > 0` 且动作日志出现对应按键；
4. **无副作用**：关闭该机制时，其他机制计数/行为不变；
5. **有收益**：A/B 达到统计阈值，否则标记 `no_gain` 并回退。

## 5. 量化协议（可持续提升，而不是单局高值）

### 5.1 单局指标

- `peak_screens`：最大推进（主指标之一）；
- `duration_s`：存活时间；
- `damage_taken`：受击次数；
- `deaths` / `death_causes`；
- `clear`：是否 LEVEL COMPLETE；
- `hz`：策略频率；
- `actions_per_screen`：动作密度；
- `time_to_control`（冷启动场景）。

### 5.2 批次指标

- 10–20 局：median / mean / p10 / max；
- clear rate（0/10 也要记录）；
- 按死因/区段分层；
- bootstrap 95% CI（中位数差/均值差）；
- 最差局 guardrail：不得比基线差 > 1 屏；
- 频率 guardrail：hz 不得低于基线 80%。

### 5.3 判定“持续提升”

一个机制只有在**连续 3 个独立批次**满足以下条件才算通过：

- 主指标中位数提升 ≥ +0.5 屏，或 clear rate 提升 ≥ 10 个百分点；
- 95% CI 下界 > 0（小样本用 bootstrap，N≥10/批）；
- 最差局不恶化超过 guardrail；
- 开关关闭时收益消失（A/B 可逆）；
- `mechanisms` 计数证明它确实执行（`applied > 0`）。

否则：`no_gain` / `regression`，回退，记录负结果。

### 5.4 实验记录

本地（不入库）：

```text
experiments/<id>/
  spec.json         # 机制 id、基线/候选配置、N、主指标、阈值
  runs.jsonl        # 每局 metrics + git sha + profile hash + 时间
  summary.json      # 批次统计/CI/判定
  frames/           # 可选关键帧
```

仓库内只提交 `spec` 模板与结论摘要；不提交录像/账本/本机路径。

## 6. 路线图与验收

| 阶段 | 内容 | 验收 |
|:--|:--|:--|
| P0 | 机制注册表 + 运行时计数 + 实验记录器 | 每个现有机制有 counters；关闭开关 applied=0 |
| P1 | WorldModel（空间/威胁/自身） | 10 点同步采样，空间/动作状态一致率 ≥ 80% |
| P2 | Option 合约 + 5 个 option（shadow） | option 选择可解释；shadow 不影响行为 |
| P3 | UtilityArbiter（安全否决 + 承诺） | 单机制 canary；10 局 A/B |
| P4 | 连续 3 批验证 + 记忆/guide 只改效用 | 达标才 promotion；否则回退 |

## 7. 与现有代码的关系

- 保留：`PolicyRunner` 执行层、`WorldState`/`SituationReport`/`Intent` 契约、LevelMemory/GuideStore；
- 新增：`mechanisms.py`（注册/计数）、`experiment.py`（A/B 统计）、后续 `options.py`/`arbiter_v2.py`；
- 不新增：游戏名/关卡坐标分支；不在引擎写 Cuphead 专用技能；
- profile 只放：键位、HUD、阈值、机制开关/权重。

## 8. 非目标

- 不现在上 MuZero/AlphaStar/SIMA；
- 不让主模型进 30Hz 环；
- 不把单局 11.15 当“提升”；
- 不在未通关时写 README「茶杯头已通关」。

## 9. 实现进度（2026-11-04）

- P0 完成：`mechanisms.py` 计数、`experiment.py` A/B 判定、`status.mechanisms`；`edge_escape=false` 可观测 applied=0。
- P1 完成（离线）：`world_model.py`（space/threats/self_state），`status.world_model`。
- P2 完成（shadow）：`options.py`（OptionSpec + 5 个 option + UtilityArbiter 安全否决/承诺/冷却），`status.option_shadow`；只写状态，不执行按键。
- 测试：284 passed。
- 待实机：`world_model`/`option_shadow` 的 live counters、10 局 A/B、连续 3 批 promotion；离线结果不算“游戏内提升”。

## 10. P3 canary（2026-11-04）

- `status.mechanisms.option_canary`：默认 disabled，`applied=0`；
- profile `options.execute=true` + `options.canary=<option id>` 才启用，且一次只允许一个 option；
- 支持 canary：jump_over / dash_through / strafe_left / strafe_right；
- 安全前置：gameplay、grounded、非 hurt、冷却、选中 option 必须等于 canary；
- 执行一次后写入 `_last_jump_at/_last_dash_at`，避免周期动作同帧叠加；
- 仍不默认开启；实机 A/B 未做，不宣称收益。

## 11. P4 离线工具（2026-11-04）

- `experiment_cli.py`：
  - `python -m dsh_game_core.experiment_cli summary runs.jsonl`
  - `python -m dsh_game_core.experiment_cli compare baseline.jsonl candidate.jsonl --mechanism option_canary --min-runs 10 --min-effect 0.5`
- `metrics_from_status()`：从 `policy.status` 提取 peak/duration/damage/deaths/cause/hz/clear；
- `test_mechanism_defaults.py`：所有默认机制必须有 expected_trigger/effect/owner_test；option_canary 默认 disabled；
- 默认机制 live counters 测试：periodic_jump applied>0、world_model applied>0、option_canary applied=0；
- 测试：290 passed。

## 12. 机制审计（2026-11-04）

- `mechanism_audit.py`：对 `status.mechanisms` 做 pass/fail：
  - 该启用的机制 `applied > 0`；
  - 该关闭的机制 `applied == 0`；
  - 缺失机制直接失败。
- CLI：`python -m dsh_game_core.experiment_cli audit status.json --profile profile.json`。
- 这是“机制正确生效”的最后一道检查：不是看代码存在，而是看开关+计数一致。

## 13. P4 跑批器（2026-11-04）

- `batch.py`：注入式 `collect_batch`：
  - start/stop/status/reset/sleep 全部由调用方提供；
  - 每局等 death 或超时，转 RunMetrics 写 JSONL；
  - 每局 mechanism audit，失败写入 audit_failures；
  - 返回 summary。
- 引擎不绑定具体 driver；实机时把 driver HTTP 调用注入即可。
- 测试覆盖 start/stop/reset 计数、death envelope、audit failure。

## 14. 实机跑批入口（2026-11-04）

- `scripts/ab_batch.py`：通过本地 driver 跑 N 局：
  - `python scripts/ab_batch.py --label baseline --runs 10`
  - `python scripts/ab_batch.py --label canary-jump --runs 10 --canary jump_over`
- 自动应用 profile 的 `options.execute/canary`，写 `tmp/experiments/<label>.jsonl`，每局 audit，输出 summary。
- `batch.apply_canary` 是纯函数，单元测试覆盖基线与候选 profile。
- 未实机；等 driver 可用时直接执行。

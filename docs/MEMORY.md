# 记忆架构（v0，已接线）

> **范围说明（2026-11-12）**：项目方向已收窄为慢节奏游戏（见 [STATUS](STATUS.md)）。本文的**架构仍然有效**，
> 但各层适用性不同，且**实现远没有设计完整**：
>
> | 层 | 适用于慢节奏游戏 | 实现现状（已对照代码） |
> |:--|:--|:--|
> | M0 工作记忆 | ✅ | 没有通用实现；只有动作策略里的 `_learning_recent` 等内部缓冲（`policy.py`） |
> | M1 关卡/Boss | ❌ 动作游戏专用，已冻结 | `level_memory.py`、`memory.py` 的 DangerCard / `LevelLocator`；按横版卷轴坐标 `scroll_s` 分段 |
> | M2 游戏级 | ✅ **核心** | `memory_loader.load_game` 只会**读取** `game.json` / `ui.json` / `entities.json`；**没有任何代码写这些文件** |
> | M3 通识 | ✅ | 只会读 `general.json`，没有内容、没有写入 |
> | M4 元记忆 | ✅ | 只有 `manifest()` 读取，没有写入 |
> | M5 用户/环境 | ✅ | 只会读 `user/preferences.json`，没有写入 |
> | 攻略（§5） | ✅ | `GuideStore` 已实现，数据形状通用 |
>
> 下文 §4（Level Memory）和 §7 的待办 1–3、5 属于已冻结的动作游戏路线。其余章节在新路线里要重新对齐，
> 对齐方案见 [DESIGN § 9](DESIGN.md#9-待定游戏数据与记忆的收敛)。

> 状态：`level_memory.py` / `memory_loader.py` / `memory_context.py` / `memory_report.py` 已实现，并接入 Session/PolicyRunner（记录、上下文、shadow 只读）；目前不改变动作。
> 原则：引擎不认游戏名/关卡名；`game_id` / `level_id` 由 session 传入，数据按作用域懒加载。

## 1. 作用域

| 层 | 作用域 | 生命周期 | 内容 |
|:--|:--|:--|:--|
| M0 工作记忆 | 当前一局 | 秒级 | 最近状态/动作/结果、intent/TTL |
| M1 关卡/Boss | 单关卡 | 进入加载、离开卸载 | 分段、死亡/受击热点、成功动作、Boss 阶段 |
| M2 游戏 | 单游戏 | attach 时常驻 | 按键/HUD/UI、实体目录、参数校准、规则 |
| M3 通识 | 跨游戏 | 常驻（小体积） | 类型先验、设计约定、引擎/文件布局 |
| M4 元记忆 | 跨层 | 常驻 | 来源、置信、版本、冲突、assisted、验证状态 |
| M5 用户/环境 | 用户 | 常驻 | 风险偏好、设备、安全/反作弊约束 |

## 2. 目录结构

```text
<memory-root>/
  general.json
  user/preferences.json
  meta/manifest.json
  games/<game_id>/
    game.json
    entities.json
    ui.json
    levels/<level_id>.json
```

`<game_id>` / `<level_id>` 必须经过 `safe_id`，防路径穿越。

## 3. 加载规则

- attach 游戏：`load_game(game_id)`，只加载 M2 + M3 + M5；
- 进入关卡/Boss：`load_level(game_id, level_id)`，加载 M1；
- 离开关卡：`save_level()` + `unload_level()`，不把关卡记忆带进其他关卡；
- 上下文只注入当前作用域 + 高相关/高置信条目。

## 4. Level Memory

`LevelMemory` 按 scroll 桶分段：

```json
{
  "game": "cuphead",
  "level": "forest-follies",
  "bucket": 0.5,
  "segments": {
    "s:-13": {
      "visits": 3,
      "deaths": 2,
      "damage": 4,
      "actions": {
        "jump": {"n": 4, "good": 3},
        "advance": {"n": 6, "good": 1}
      },
      "last_success": ["jump", "dash"]
    }
  }
}
```

用途：

- `hotspot(scroll)`：重复死亡点；
- `preferred_action(scroll)`：该段成功率最高的动作；
- 调用方决定“提高风险/提前跳/换姿态”，LevelMemory 本身不控制按键。

## 5. 攻略（Guide）边界

- 进入游戏：查游戏卡（键位/机制/UI）；
- 进入关卡/Boss：查关卡/Boss 卡（阶段、招式应对、常见坑）；
- 存 claim，不存全文；带 `source_url/fetched_at/confidence/assisted/verified`；
- 攻略是**先验**，实测优先；不可存逐帧输入序列/精确坐标脚本；
- 离线时退化到通识 + 自探索；
- Assisted / Autonomous 分开统计。

## 6. 元记忆

每条跨局记忆应带：

- `source`: probe/file/web/model/outcome
- `confidence`
- `samples`
- `last_verified_at`
- `assisted`
- `schema_version`
- `conflicts`

## 7. 待办

1. Session 在 attach/进关/离关时调用 MemoryLoader；
2. PolicyRunner 在 death/damage/success 时更新 LevelMemory；
3. 把 hotspot/preferred action 接入候选评分（先 shadow，再 promotion）；
4. GuideStore 扩展 scope/source/assisted/verified；
5. 上下文组装器：按作用域/相关性/置信度取 top-K。

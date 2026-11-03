# 记忆架构（v0，已接线）

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

# 通用游戏矩阵（v3）

本目录是 [GENERAL-PLUGIN-V3.md](../../docs/GENERAL-PLUGIN-V3.md) 的执行清单，不是游戏数据仓库。

## 规则

- 只列单机、无反作弊的游戏；在线竞技一律排除。
- 不提交 ROM、录像、账号、本机路径或游戏资源。
- 每款游戏先做 **T1**，再考虑 **T2**；不要求通关。
- 反作弊字段不是 `none` 的游戏，GamePack 直接拒绝加载。
- Cuphead 只做 depth regression，不再作为总 KPI。

## 层级

| 层级 | 验收 |
|:--|:--|
| T0 | attach + 抓屏 + 窗口/前台 |
| T1 | 菜单/键位 + 首个有效动作，5 分钟内，无需人示范 |
| T2 | 连续 5 分钟有意义游玩 |
| T3 | 通关第一关/Boss（可选） |
| T4 | 稳定重复（可选） |

## 当前选择

- **T1 主目标（2/3）**：Cuphead ✅、2048 ✅、SuperTux（二进制缺失）
- **T2 候选**：Cuphead、2048
- **可选**：NES Battle City via RetroArch（需要先确认模拟器与合法 ROM）；Block Blast（构建不可玩）
- **排除**：Overwatch、Honkai: Star Rail、Wuthering Waves（在线/反作弊）；Brotato 暂不可用

具体状态见 [matrix.json](matrix.json)。新游戏先在此登记，再生成 pack 草稿。

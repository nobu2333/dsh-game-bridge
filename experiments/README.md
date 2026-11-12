# 实验存档（已冻结）

> 2026-11-12 起，本目录只作历史存档，不再新增实验。项目方向见 [docs/STATUS.md](../docs/STATUS.md)。
> 本机的完整 runs / traces / frames 从未入库（`.gitignore`）。

## 内容

| 路径 | 内容 | 结论 |
|:--|:--|:--|
| `results/v21-*.md`、`results/ptracker-*.md`、`results/option-canary-*.md` | Cuphead 实时玩法的 A/B 批次报告（2026-11-05 至 11-09） | 策略改动都没有超过 baseline；感知指标改善没有转化成推进 |
| `results/b-supertux-*.md` | SuperTux 第二游戏冒烟（2026-11-06） | 部分跑通，未继续 |
| `results/auto-onboard-*.md` | 自动接入：Dino 成功、SuperTux 失败（2026-11-10、11-11） | 单阶段菜单的游戏可以自动接入，多阶段导航不行 |
| `games/packs/*.json`、`games/packs/*.md` | v3 的 GamePack 与 T1/T2 证据 | T1 大多依赖手写 pack；T2 是固定节拍按键循环，**不代表有玩法能力** |
| `games/matrix.json` | v3 游戏矩阵 | 路线已停止 |
| `specs/` | 实验设计 | — |

## 如果以后要重新做实验

慢节奏游戏的玩法证据必须满足：

1. 由 DSH 模型通过插件工具驱动，不能用直接调用引擎的脚本代替；
2. 和随机 / 固定按键对照组比较，每组至少 5 局，报告得分分布；
3. 负结果也入库。

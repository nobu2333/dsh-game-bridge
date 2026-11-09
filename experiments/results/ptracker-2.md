# 批次复盘报告：ptracker-2

- **局数 (n)**：20
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 2.4075 | — |
| Mean Peak (screens) | 2.0687 | — |
| P10 Peak (screens) | 0.408 | — |
| Max Peak (screens) | 3.232 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.0349 | — |
| Mean Threat Active Ratio | 0.9875 | — |
| Mean Damage Events | 5.6 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"cornered": 12, "hit": 5, "low_hp": 3}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| ptracker-2-01 | 2.588 | 22.302 | 0.023 | 1.0 | 7 | cornered:1 |
| ptracker-2-02 | 1.941 | 17.385 | 0.0461 | 0.9965 | 5 | hit:1 |
| ptracker-2-03 | 1.894 | 16.95 | 0.0438 | 0.9933 | 3 | hit:1 |
| ptracker-2-04 | 2.678 | 21.236 | 0.0397 | 0.9435 | 7 | cornered:1 |
| ptracker-2-05 | 0.108 | 15.628 | 0.0526 | 0.9158 | 1 | hit:1 |
| ptracker-2-06 | 2.768 | 22.319 | 0.0343 | 1.0 | 10 | cornered:1 |
| ptracker-2-07 | 3.057 | 19.013 | 0.0353 | 0.9793 | 7 | hit:1 |
| ptracker-2-08 | 2.78 | 22.962 | 0.0515 | 0.9974 | 4 | cornered:1 |
| ptracker-2-09 | 3.079 | 23.429 | 0.0252 | 1.0 | 5 | hit:1 |
| ptracker-2-10 | 0.76 | 36.443 | 0.0 | 1.0 | 6 | cornered:1 |
| ptracker-2-11 | 2.383 | 17.497 | 0.0267 | 1.0 | 6 | cornered:1 |
| ptracker-2-12 | 1.739 | 12.793 | 0.0302 | 0.997 | 10 | low_hp:1 |
| ptracker-2-13 | 2.432 | 16.87 | 0.0416 | 0.9723 | 6 | cornered:1 |
| ptracker-2-14 | 2.488 | 16.885 | 0.0261 | 1.0 | 5 | cornered:1 |
| ptracker-2-15 | 0.408 | 21.091 | 0.0263 | 1.0 | 4 | cornered:1 |
| ptracker-2-16 | 0.227 | 21.174 | 0.0694 | 0.9583 | 3 | low_hp:1 |
| ptracker-2-17 | 3.208 | 19.899 | 0.0356 | 0.9979 | 8 | low_hp:1 |
| ptracker-2-18 | 2.091 | 16.846 | 0.0173 | 1.0 | 3 | cornered:1 |
| ptracker-2-19 | 3.232 | 19.005 | 0.0336 | 0.9982 | 9 | cornered:1 |
| ptracker-2-20 | 1.513 | 19.932 | 0.0393 | 1.0 | 3 | cornered:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `ptracker-2-01` (共 123 条轨迹采样)
- `tick=381` `scroll=-2.534` `hp=1` `anchor=[0.1266, 0.4074]` `age_ms=14` `opt=dash_through(commit)` `act=dash` `threats=2`
- `tick=383` `scroll=-2.544` `hp=1` `anchor=[0.1266, 0.4074]` `age_ms=48` `opt=dash_through(commit)` `act=dash` `threats=2`
- `tick=384` `scroll=-2.55` `hp=1` `anchor=[0.1323, 0.4009]` `age_ms=2` `opt=dash_through(commit)` `act=jump` `threats=2`
- `tick=390` `scroll=-2.583` `hp=1` `anchor=[0.125, 0.3954]` `age_ms=47` `opt=jump_over(switch)` `act=jump` `threats=2`
- `tick=518` `scroll=-2.588` `hp=None` `anchor=[0.125, 0.3954]` `age_ms=5600` `opt=jump_over(commit)` `act=None` `threats=2`

### `ptracker-2-02` (共 90 条轨迹采样)
- `tick=271` `scroll=-1.833` `hp=2` `anchor=[0.262, 0.4093]` `age_ms=50` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=273` `scroll=-1.855` `hp=2` `anchor=[0.2349, 0.413]` `age_ms=14` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=276` `scroll=-1.864` `hp=2` `anchor=[0.2078, 0.4185]` `age_ms=2` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=280` `scroll=-1.905` `hp=2` `anchor=[0.1672, 0.4259]` `age_ms=2` `opt=stop_shoot(switch)` `act=None` `threats=2`
- `tick=335` `scroll=-1.941` `hp=None` `anchor=[0.1672, 0.4259]` `age_ms=2917` `opt=stop_shoot(commit)` `act=None` `threats=2`

### `ptracker-2-03` (共 87 条轨迹采样)
- `tick=289` `scroll=-1.842` `hp=2` `anchor=[0.5563, 0.7722]` `age_ms=14` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=293` `scroll=-1.881` `hp=2` `anchor=[0.5052, 0.7852]` `age_ms=15` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=294` `scroll=-1.887` `hp=2` `anchor=[0.5052, 0.7852]` `age_ms=41` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=296` `scroll=-1.894` `hp=2` `anchor=[0.6411, 0.5954]` `age_ms=3` `opt=jump_over(continue)` `act=None` `threats=2`
- `tick=345` `scroll=-1.894` `hp=None` `anchor=[0.6411, 0.5954]` `age_ms=2790` `opt=jump_over(continue)` `act=None` `threats=2`

# 批次复盘报告：v21-reactive-3

- **局数 (n)**：10
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 1.936 | — |
| Mean Peak (screens) | 1.9697 | — |
| P10 Peak (screens) | 1.481 | — |
| Max Peak (screens) | 3.326 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.1918 | — |
| Mean Threat Active Ratio | 0.9878 | — |
| Mean Damage Events | 6.8 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"hit": 3, "low_hp": 2, "cornered": 5}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| v21-reactive-3-01 | 3.326 | 23.411 | 0.1597 | 0.9987 | 7 | hit:1 |
| v21-reactive-3-02 | 2.621 | 25.017 | 0.1631 | 1.0 | 5 | hit:1 |
| v21-reactive-3-03 | 2.026 | 14.777 | 0.2144 | 1.0 | 7 | low_hp:1 |
| v21-reactive-3-04 | 2.151 | 16.803 | 0.1468 | 0.9984 | 11 | cornered:1 |
| v21-reactive-3-05 | 1.846 | 15.728 | 0.1497 | 0.9981 | 6 | low_hp:1 |
| v21-reactive-3-06 | 1.481 | 22.231 | 0.1553 | 0.9983 | 11 | cornered:1 |
| v21-reactive-3-07 | 0.565 | 21.086 | 0.4659 | 0.9318 | 6 | cornered:1 |
| v21-reactive-3-08 | 1.73 | 14.698 | 0.1911 | 0.9961 | 5 | cornered:1 |
| v21-reactive-3-09 | 2.402 | 23.55 | 0.1451 | 0.9565 | 7 | cornered:1 |
| v21-reactive-3-10 | 1.549 | 20.408 | 0.1273 | 1.0 | 3 | hit:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `v21-reactive-3-01` (共 171 条轨迹采样)
- `tick=732` `scroll=-3.258` `hp=2` `anchor=[0.4668, 0.2574]` `age_ms=2` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=738` `scroll=-3.296` `hp=2` `anchor=[0.4823, 0.29]` `age_ms=40` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=739` `scroll=-3.3` `hp=2` `anchor=[0.4823, 0.29]` `age_ms=51` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=744` `scroll=-3.326` `hp=2` `anchor=[0.5162, 0.3492]` `age_ms=2` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=814` `scroll=-3.326` `hp=None` `anchor=[0.5162, 0.3492]` `age_ms=2385` `opt=jump_over(commit)` `act=None` `threats=2`

### `v21-reactive-3-02` (共 151 条轨迹采样)
- `tick=606` `scroll=-2.603` `hp=2` `anchor=[0.4926, 0.5729]` `age_ms=42` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=608` `scroll=-2.607` `hp=2` `anchor=[0.3992, 0.5594]` `age_ms=2` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=611` `scroll=-2.616` `hp=2` `anchor=[0.3992, 0.5594]` `age_ms=47` `opt=stop_shoot(switch)` `act=dash` `threats=2`
- `tick=612` `scroll=-2.621` `hp=2` `anchor=[0.3668, 0.5679]` `age_ms=2` `opt=stop_shoot(commit)` `act=dash` `threats=2`
- `tick=783` `scroll=-2.621` `hp=None` `anchor=[0.3668, 0.5679]` `age_ms=8944` `opt=stop_shoot(commit)` `act=None` `threats=2`

### `v21-reactive-3-03` (共 129 条轨迹采样)
- `tick=522` `scroll=-2.025` `hp=1` `anchor=[0.5111, 0.7815]` `age_ms=989` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=528` `scroll=-2.026` `hp=1` `anchor=[0.5111, 0.7815]` `age_ms=1100` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=534` `scroll=-2.025` `hp=1` `anchor=[0.5111, 0.7815]` `age_ms=1203` `opt=dash_through(switch)` `act=None` `threats=2`
- `tick=540` `scroll=-2.026` `hp=1` `anchor=[0.5111, 0.7815]` `age_ms=1313` `opt=dash_through(commit)` `act=None` `threats=2`
- `tick=541` `scroll=-2.026` `hp=None` `anchor=[0.5111, 0.7815]` `age_ms=1970` `opt=dash_through(commit)` `act=None` `threats=2`

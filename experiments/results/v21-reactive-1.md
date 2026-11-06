# 批次复盘报告：v21-reactive-1

- **局数 (n)**：10
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 1.996 | — |
| Mean Peak (screens) | 1.7702 | — |
| P10 Peak (screens) | 0.006 | — |
| Max Peak (screens) | 3.427 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.1589 | — |
| Mean Threat Active Ratio | 0.9901 | — |
| Mean Damage Events | 166.3 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"cornered": 3, "hit": 3, "low_hp": 3, "unknown": 1}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| v21-reactive-1-01 | 1.99 | 16.811 | 0.1929 | 0.9814 | 3 | cornered:1 |
| v21-reactive-1-02 | 2.037 | 19.24 | 0.1659 | 1.0 | 8 | hit:1 |
| v21-reactive-1-03 | 2.079 | 17.485 | 0.0681 | 0.9961 | 5 | cornered:1 |
| v21-reactive-1-04 | 2.002 | 20.347 | 0.0593 | 1.0 | 5 | hit:1 |
| v21-reactive-1-05 | 3.427 | 25.746 | 0.1574 | 0.9986 | 10 | low_hp:1 |
| v21-reactive-1-06 | 1.917 | 19.534 | 0.1625 | 0.9265 | 4 | cornered:1 |
| v21-reactive-1-07 | 1.895 | 17.982 | 0.0833 | 0.9981 | 6 | low_hp:1 |
| v21-reactive-1-08 | 2.348 | 16.812 | 0.1552 | 1.0 | 9 | hit:1 |
| v21-reactive-1-09 | 0.001 | 8.755 | 0.0049 | 1.0 | 1611 | unknown:1 |
| v21-reactive-1-10 | 0.006 | 21.607 | 0.5395 | 1.0 | 2 | low_hp:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `v21-reactive-1-01` (共 127 条轨迹采样)
- `tick=522` `scroll=-1.905` `hp=2` `anchor=[0.0696, 0.7425]` `age_ms=39` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=528` `scroll=-1.942` `hp=2` `anchor=[0.0714, 0.745]` `age_ms=80` `opt=jump_over(continue)` `act=None` `threats=2`
- `tick=534` `scroll=-1.972` `hp=2` `anchor=[0.109, 0.7682]` `age_ms=40` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=538` `scroll=-1.99` `hp=2` `anchor=[0.1037, 0.7772]` `age_ms=33` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=599` `scroll=-1.99` `hp=None` `anchor=[0.1037, 0.7772]` `age_ms=2795` `opt=jump_over(commit)` `act=None` `threats=2`

### `v21-reactive-1-02` (共 166 条轨迹采样)
- `tick=672` `scroll=-2.037` `hp=2` `anchor=[0.3795, 0.6745]` `age_ms=1411` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=673` `scroll=-2.037` `hp=2` `anchor=[0.3795, 0.6745]` `age_ms=1427` `opt=stop_shoot(switch)` `act=None` `threats=2`
- `tick=674` `scroll=-2.037` `hp=2` `anchor=[0.3795, 0.6745]` `age_ms=1442` `opt=stop_shoot(commit)` `act=stop_shoot` `threats=2`
- `tick=678` `scroll=-2.037` `hp=2` `anchor=[0.3795, 0.6745]` `age_ms=1524` `opt=stop_shoot(commit)` `act=stop_shoot` `threats=2`
- `tick=681` `scroll=-2.037` `hp=None` `anchor=[0.3795, 0.6745]` `age_ms=1571` `opt=stop_shoot(commit)` `act=stop_shoot` `threats=2`

### `v21-reactive-1-03` (共 125 条轨迹采样)
- `tick=504` `scroll=-1.997` `hp=1` `anchor=[0.1884, 0.8599]` `age_ms=2` `opt=dash_through(commit)` `act=dash` `threats=2`
- `tick=506` `scroll=-2.026` `hp=1` `anchor=[0.1884, 0.8599]` `age_ms=34` `opt=jump_over(switch)` `act=dash` `threats=2`
- `tick=508` `scroll=-2.044` `hp=1` `anchor=[0.1012, 0.8849]` `age_ms=3` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=510` `scroll=-2.052` `hp=1` `anchor=[0.1012, 0.8849]` `age_ms=47` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=576` `scroll=-2.079` `hp=None` `anchor=[0.1012, 0.8849]` `age_ms=2989` `opt=jump_over(commit)` `act=None` `threats=2`

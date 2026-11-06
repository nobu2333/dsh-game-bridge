# 批次复盘报告：v21-baseline-1

- **局数 (n)**：10
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 2.5505 | — |
| Mean Peak (screens) | 2.2923 | — |
| P10 Peak (screens) | 1.493 | — |
| Max Peak (screens) | 3.229 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.2563 | — |
| Mean Threat Active Ratio | 0.9934 | — |
| Mean Damage Events | 6.5 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"low_hp": 4, "hit": 4, "cornered": 2}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| v21-baseline-1-01 | 2.488 | 16.829 | 0.1547 | 0.9981 | 6 | low_hp:1 |
| v21-baseline-1-02 | 3.229 | 17.484 | 0.1699 | 1.0 | 16 | low_hp:1 |
| v21-baseline-1-03 | 2.503 | 21.07 | 0.1984 | 1.0 | 7 | low_hp:1 |
| v21-baseline-1-04 | 0.005 | 15.692 | 0.9263 | 1.0 | 1 | low_hp:1 |
| v21-baseline-1-05 | 1.493 | 12.701 | 0.2216 | 1.0 | 4 | hit:1 |
| v21-baseline-1-06 | 2.717 | 16.826 | 0.1497 | 0.9982 | 9 | hit:1 |
| v21-baseline-1-07 | 2.283 | 19.496 | 0.1351 | 0.9443 | 8 | cornered:1 |
| v21-baseline-1-08 | 2.795 | 20.181 | 0.2466 | 0.9966 | 7 | cornered:1 |
| v21-baseline-1-09 | 2.812 | 20.282 | 0.2521 | 1.0 | 3 | hit:1 |
| v21-baseline-1-10 | 2.598 | 16.796 | 0.1085 | 0.9963 | 4 | hit:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `v21-baseline-1-01` (共 148 条轨迹采样)
- `tick=516` `scroll=-2.371` `hp=1` `anchor=[0.7208, 0.6089]` `age_ms=2` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=522` `scroll=-2.419` `hp=1` `anchor=[0.636, 0.6225]` `age_ms=44` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=526` `scroll=-2.456` `hp=1` `anchor=[0.5819, 0.6348]` `age_ms=31` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=528` `scroll=-2.471` `hp=1` `anchor=[0.5381, 0.6436]` `age_ms=2` `opt=stop_shoot(commit)` `act=jump` `threats=2`
- `tick=585` `scroll=-2.488` `hp=None` `anchor=[0.5381, 0.6436]` `age_ms=2740` `opt=stop_shoot(commit)` `act=None` `threats=2`

### `v21-baseline-1-02` (共 178 条轨迹采样)
- `tick=606` `scroll=-3.229` `hp=1` `anchor=[0.1878, 0.3963]` `age_ms=559` `opt=dash_through(commit)` `act=None` `threats=2`
- `tick=611` `scroll=-3.229` `hp=1` `anchor=[0.1878, 0.3963]` `age_ms=640` `opt=jump_over(switch)` `act=None` `threats=2`
- `tick=612` `scroll=-3.229` `hp=1` `anchor=[0.1878, 0.3963]` `age_ms=675` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=615` `scroll=-3.229` `hp=1` `anchor=[0.1878, 0.3963]` `age_ms=726` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=618` `scroll=-3.229` `hp=None` `anchor=[0.1878, 0.3963]` `age_ms=1407` `opt=jump_over(commit)` `act=jump` `threats=2`

### `v21-baseline-1-03` (共 166 条轨迹采样)
- `tick=612` `scroll=-2.44` `hp=1` `anchor=[0.4509, 0.6622]` `age_ms=2` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=617` `scroll=-2.486` `hp=1` `anchor=[0.4167, 0.6695]` `age_ms=14` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=618` `scroll=-2.495` `hp=1` `anchor=[0.4167, 0.6695]` `age_ms=45` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=619` `scroll=-2.503` `hp=1` `anchor=[0.4167, 0.6695]` `age_ms=58` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=674` `scroll=-2.503` `hp=None` `anchor=[0.4167, 0.6695]` `age_ms=2737` `opt=jump_over(commit)` `act=None` `threats=2`

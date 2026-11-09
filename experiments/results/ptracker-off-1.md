# 批次复盘报告：ptracker-off-1

- **局数 (n)**：20
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 1.5255 | — |
| Mean Peak (screens) | 1.4863 | — |
| P10 Peak (screens) | 0.049 | — |
| Max Peak (screens) | 3.194 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.3663 | — |
| Mean Threat Active Ratio | 0.9918 | — |
| Mean Damage Events | 4.8 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"cornered": 109, "low_hp": 50, "hit": 51, "unknown": 5}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| ptracker-off-1-01 | 2.786 | 21.293 | 0.1684 | 0.9562 | 8 | cornered:1 |
| ptracker-off-1-02 | 0.111 | 19.378 | 1.0 | 1.0 | 1 | low_hp:1 |
| ptracker-off-1-03 | 2.703 | 22.103 | 0.1873 | 0.9982 | 5 | cornered:1 |
| ptracker-off-1-04 | 2.244 | 16.785 | 0.1737 | 0.9889 | 3 | hit:1 |
| ptracker-off-1-05 | 0.003 | 22.057 | 1.0 | 0.9651 | 2 | low_hp:1 |
| ptracker-off-1-06 | 0.565 | 21.853 | 0.4054 | 1.0 | 5 | hit:1 |
| ptracker-off-1-07 | 1.858 | 22.084 | 0.1205 | 0.9928 | 2 | cornered:1 |
| ptracker-off-1-08 | 2.391 | 17.644 | 0.2773 | 0.9982 | 6 | cornered:1 |
| ptracker-off-1-09 | 1.324 | 12.851 | 0.2902 | 0.9902 | 7 | cornered:1 |
| ptracker-off-1-10 | 0.049 | 22.909 | 0.5 | 1.0 | 1 | low_hp:1 |
| ptracker-off-1-11 | 0.001 | 7.887 | 0.3521 | 1.0 | 0 | unknown:1 |
| ptracker-off-1-12 | 1.644 | 12.813 | 0.2494 | 0.9953 | 10 | low_hp:1 |
| ptracker-off-1-13 | 3.194 | 21.193 | 0.2481 | 0.9954 | 5 | cornered:1 |
| ptracker-off-1-14 | 0.257 | 25.862 | 0.8209 | 0.9627 | 2 | low_hp:42,hit:48,unknown:4,cornered:102 |
| ptracker-off-1-15 | 3.088 | 22.357 | 0.177 | 1.0 | 9 | low_hp:1 |
| ptracker-off-1-16 | 3.191 | 18.982 | 0.1582 | 0.9939 | 9 | cornered:1 |
| ptracker-off-1-17 | 2.079 | 17.4 | 0.2068 | 1.0 | 5 | hit:1 |
| ptracker-off-1-18 | 0.609 | 50.383 | 0.4367 | 1.0 | 8 | low_hp:1 |
| ptracker-off-1-19 | 1.407 | 17.043 | 0.161 | 1.0 | 5 | low_hp:1 |
| ptracker-off-1-20 | 0.221 | 21.396 | 0.3929 | 1.0 | 3 | low_hp:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `ptracker-off-1-01` (共 173 条轨迹采样)
- `tick=582` `scroll=-2.708` `hp=2` `anchor=[0.0496, 0.8401]` `age_ms=119` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=588` `scroll=-2.754` `hp=2` `anchor=[0.0537, 0.9102]` `age_ms=84` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=592` `scroll=-2.777` `hp=2` `anchor=[0.0551, 0.9348]` `age_ms=3` `opt=strafe_right(switch)` `act=None` `threats=2`
- `tick=593` `scroll=-2.786` `hp=2` `anchor=[0.0551, 0.9348]` `age_ms=16` `opt=strafe_right(commit)` `act=dash` `threats=2`
- `tick=652` `scroll=-2.786` `hp=None` `anchor=[0.0551, 0.9348]` `age_ms=2232` `opt=strafe_right(commit)` `act=None` `threats=2`

### `ptracker-off-1-02` (共 142 条轨迹采样)
- `tick=570` `scroll=-0.111` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(continue)` `act=jump` `threats=2`
- `tick=576` `scroll=-0.111` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=582` `scroll=-0.111` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=588` `scroll=-0.111` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=590` `scroll=-0.111` `hp=None` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`

### `ptracker-off-1-03` (共 153 条轨迹采样)
- `tick=558` `scroll=-2.705` `hp=2` `anchor=[0.0142, 0.6415]` `age_ms=418` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=559` `scroll=-2.71` `hp=2` `anchor=[0.0142, 0.6415]` `age_ms=430` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=561` `scroll=-2.704` `hp=2` `anchor=[0.0142, 0.6415]` `age_ms=466` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=564` `scroll=-2.705` `hp=2` `anchor=[0.0142, 0.6415]` `age_ms=539` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=690` `scroll=-2.703` `hp=None` `anchor=[0.0142, 0.6415]` `age_ms=5986` `opt=jump_over(commit)` `act=None` `threats=2`

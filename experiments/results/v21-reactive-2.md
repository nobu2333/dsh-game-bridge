# 批次复盘报告：v21-reactive-2

- **局数 (n)**：10
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 2.261 | — |
| Mean Peak (screens) | 2.0029 | — |
| P10 Peak (screens) | 0.356 | — |
| Max Peak (screens) | 3.833 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.2098 | — |
| Mean Threat Active Ratio | 0.9927 | — |
| Mean Damage Events | 6.5 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"cornered": 4, "low_hp": 4, "hit": 2}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| v21-reactive-2-01 | 2.334 | 17.418 | 0.0673 | 1.0 | 14 | cornered:1 |
| v21-reactive-2-02 | 0.046 | 19.497 | 1.0 | 0.962 | 1 | low_hp:1 |
| v21-reactive-2-03 | 1.787 | 15.116 | 0.1327 | 1.0 | 7 | cornered:1 |
| v21-reactive-2-04 | 3.833 | 25.604 | 0.1032 | 0.9964 | 8 | hit:1 |
| v21-reactive-2-05 | 2.872 | 21.74 | 0.1787 | 0.996 | 7 | low_hp:1 |
| v21-reactive-2-06 | 2.334 | 19.029 | 0.1033 | 0.9885 | 11 | low_hp:1 |
| v21-reactive-2-07 | 2.77 | 19.129 | 0.1828 | 0.9845 | 7 | cornered:1 |
| v21-reactive-2-08 | 2.188 | 20.738 | 0.1208 | 1.0 | 4 | cornered:1 |
| v21-reactive-2-09 | 1.509 | 12.755 | 0.0875 | 1.0 | 1 | hit:1 |
| v21-reactive-2-10 | 0.356 | 23.591 | 0.1216 | 1.0 | 5 | low_hp:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `v21-reactive-2-01` (共 143 条轨迹采样)
- `tick=594` `scroll=-2.333` `hp=1` `anchor=[0.0272, 0.9473]` `age_ms=109` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=597` `scroll=-2.333` `hp=1` `anchor=[0.0272, 0.9473]` `age_ms=154` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=600` `scroll=-2.334` `hp=1` `anchor=[0.0272, 0.9473]` `age_ms=221` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=606` `scroll=-2.334` `hp=1` `anchor=[0.0272, 0.9473]` `age_ms=329` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=609` `scroll=-2.334` `hp=None` `anchor=[0.0272, 0.9473]` `age_ms=1036` `opt=jump_over(commit)` `act=None` `threats=2`

### `v21-reactive-2-02` (共 149 条轨迹采样)
- `tick=670` `scroll=-0.046` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(switch)` `act=None` `threats=1`
- `tick=672` `scroll=-0.046` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`
- `tick=678` `scroll=-0.046` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=1`
- `tick=684` `scroll=-0.046` `hp=1` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=1`
- `tick=687` `scroll=-0.046` `hp=None` `anchor=[0.28, 0.75]` `age_ms=None` `opt=stop_shoot(commit)` `act=None` `threats=2`

### `v21-reactive-2-03` (共 134 条轨迹采样)
- `tick=527` `scroll=-1.788` `hp=1` `anchor=[0.0095, 0.5338]` `age_ms=763` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=528` `scroll=-1.788` `hp=1` `anchor=[0.0095, 0.5338]` `age_ms=801` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=532` `scroll=-1.788` `hp=1` `anchor=[0.0095, 0.5338]` `age_ms=900` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=534` `scroll=-1.787` `hp=1` `anchor=[0.0095, 0.5338]` `age_ms=958` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=535` `scroll=-1.787` `hp=None` `anchor=[0.0095, 0.5338]` `age_ms=2035` `opt=jump_over(commit)` `act=None` `threats=2`

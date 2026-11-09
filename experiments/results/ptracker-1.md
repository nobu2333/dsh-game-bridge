# 批次复盘报告：ptracker-1

- **局数 (n)**：20
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 2.4715 | — |
| Mean Peak (screens) | 2.1411 | — |
| P10 Peak (screens) | 0.133 | — |
| Max Peak (screens) | 3.413 | — |
| Clear Rate | 0.0 | — |
| Mean Player Stale Ratio | 0.0361 | — |
| Mean Threat Active Ratio | 0.9833 | — |
| Mean Damage Events | 6.4 | — |

## 2. 死因分布与单局明细

- **死因汇总**：`{"cornered": 6, "low_hp": 6, "hit": 8}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| ptracker-1-01 | 2.468 | 16.965 | 0.038 | 1.0 | 11 | cornered:1 |
| ptracker-1-02 | 3.413 | 23.467 | 0.034 | 0.9117 | 8 | low_hp:1 |
| ptracker-1-03 | 2.804 | 18.975 | 0.0362 | 0.9976 | 4 | hit:1 |
| ptracker-1-04 | 0.034 | 16.912 | 0.0588 | 1.0 | 2 | cornered:1 |
| ptracker-1-05 | 0.133 | 16.743 | 0.0435 | 1.0 | 3 | hit:1 |
| ptracker-1-06 | 2.299 | 14.806 | 0.03 | 1.0 | 10 | low_hp:1 |
| ptracker-1-07 | 2.727 | 22.125 | 0.0422 | 1.0 | 9 | low_hp:1 |
| ptracker-1-08 | 2.826 | 19.448 | 0.0339 | 1.0 | 6 | cornered:1 |
| ptracker-1-09 | 0.247 | 20.906 | 0.029 | 0.9348 | 1 | low_hp:1 |
| ptracker-1-10 | 2.475 | 17.769 | 0.0274 | 1.0 | 11 | cornered:1 |
| ptracker-1-11 | 1.92 | 21.491 | 0.0418 | 1.0 | 3 | hit:1 |
| ptracker-1-12 | 2.224 | 17.309 | 0.0334 | 1.0 | 10 | cornered:1 |
| ptracker-1-13 | 2.275 | 22.315 | 0.0317 | 0.9819 | 5 | cornered:1 |
| ptracker-1-14 | 0.022 | 21.865 | 0.0217 | 0.9348 | 2 | low_hp:1 |
| ptracker-1-15 | 1.807 | 12.841 | 0.0347 | 0.9937 | 8 | low_hp:1 |
| ptracker-1-16 | 3.071 | 21.13 | 0.0382 | 0.9598 | 6 | hit:1 |
| ptracker-1-17 | 3.179 | 23.754 | 0.0326 | 0.9751 | 9 | hit:1 |
| ptracker-1-18 | 2.983 | 21.156 | 0.0378 | 0.9953 | 7 | hit:1 |
| ptracker-1-19 | 3.201 | 19.322 | 0.0546 | 0.9905 | 7 | hit:1 |
| ptracker-1-20 | 2.714 | 19.72 | 0.0223 | 0.9901 | 6 | hit:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `ptracker-1-01` (共 114 条轨迹采样)
- `tick=325` `scroll=-2.329` `hp=1` `anchor=[0.0828, 0.9148]` `age_ms=17` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=330` `scroll=-2.358` `hp=1` `anchor=[0.0922, 0.912]` `age_ms=38` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=336` `scroll=-2.403` `hp=1` `anchor=[0.0922, 0.912]` `age_ms=2` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=338` `scroll=-2.438` `hp=1` `anchor=[0.0922, 0.912]` `age_ms=31` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=386` `scroll=-2.468` `hp=None` `anchor=[0.0922, 0.912]` `age_ms=2818` `opt=jump_over(commit)` `act=None` `threats=2`

### `ptracker-1-02` (共 170 条轨迹采样)
- `tick=624` `scroll=-3.414` `hp=1` `anchor=[0.937, 0.7102]` `age_ms=2` `opt=jump_over(commit)` `act=dash` `threats=1`
- `tick=630` `scroll=-3.414` `hp=1` `anchor=[0.938, 0.7102]` `age_ms=34` `opt=jump_over(commit)` `act=dash` `threats=1`
- `tick=636` `scroll=-3.414` `hp=1` `anchor=[0.937, 0.7102]` `age_ms=2` `opt=jump_over(commit)` `act=dash` `threats=0`
- `tick=642` `scroll=-3.414` `hp=1` `anchor=[0.937, 0.7102]` `age_ms=33` `opt=jump_over(commit)` `act=jump` `threats=1`
- `tick=647` `scroll=-3.413` `hp=None` `anchor=[0.9359, 0.7102]` `age_ms=48` `opt=jump_over(commit)` `act=jump` `threats=1`

### `ptracker-1-03` (共 127 条轨迹采样)
- `tick=396` `scroll=-2.771` `hp=2` `anchor=[0.213, 0.2731]` `age_ms=2` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=402` `scroll=-2.767` `hp=2` `anchor=[0.2172, 0.2676]` `age_ms=42` `opt=jump_over(commit)` `act=jump` `threats=2`
- `tick=405` `scroll=-2.77` `hp=2` `anchor=[0.2109, 0.2602]` `age_ms=13` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=408` `scroll=-2.78` `hp=2` `anchor=[0.1995, 0.2602]` `age_ms=2` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=466` `scroll=-2.804` `hp=None` `anchor=[0.1745, 0.262]` `age_ms=2846` `opt=jump_over(commit)` `act=None` `threats=2`

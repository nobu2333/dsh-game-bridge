# 批次复盘报告：v21-hybrid1-vs-baseline

- **局数 (n)**：10
- **假设/说明**：常规批次评估与过程留痕复盘
- **机制审计**：通过 (0 failures)

## 1. 核心表现与感知健康度汇总

| 指标 | 当前批次 | 基线 (如有) |
|:--|--:|--:|
| Median Peak (screens) | 2.106 | 2.5505 |
| Mean Peak (screens) | 2.3352 | 2.2923 |
| P10 Peak (screens) | 1.723 | 1.493 |
| Max Peak (screens) | 3.808 | 3.229 |
| Clear Rate | 0.0 | 0.0 |
| Mean Player Stale Ratio | 0.19 | 0.2563 |
| Mean Threat Active Ratio | 0.9929 | 0.9934 |
| Mean Damage Events | 8.5 | 6.5 |

### A/B 判定
- **Decision**: `no_gain` (95% CI low -0.9005 <= 0.0)
- **Median Diff**: `-0.4445` (95% CI: `[-0.9005, 0.3385]`)

## 2. 死因分布与单局明细

- **死因汇总**：`{"hit": 4, "low_hp": 3, "cornered": 3}`

| Run ID | Peak (s) | Duration (s) | Stale Ratio | Threat Ratio | Damage | Death Cause |
|:--|--:|--:|--:|--:|--:|:--|
| v21-hybrid-1-01 | 1.734 | 14.727 | 0.1625 | 0.9962 | 7 | hit:1 |
| v21-hybrid-1-02 | 1.668 | 16.771 | 0.1724 | 0.9984 | 6 | low_hp:1 |
| v21-hybrid-1-03 | 2.219 | 16.842 | 0.2115 | 0.9455 | 8 | cornered:1 |
| v21-hybrid-1-04 | 3.808 | 25.888 | 0.1358 | 1.0 | 7 | hit:1 |
| v21-hybrid-1-05 | 2.719 | 19.045 | 0.25 | 1.0 | 9 | hit:1 |
| v21-hybrid-1-06 | 2.92 | 27.768 | 0.1792 | 1.0 | 22 | low_hp:1 |
| v21-hybrid-1-07 | 2.669 | 19.047 | 0.162 | 1.0 | 7 | hit:1 |
| v21-hybrid-1-08 | 1.723 | 15.731 | 0.1736 | 1.0 | 6 | cornered:1 |
| v21-hybrid-1-09 | 1.899 | 17.492 | 0.2788 | 0.9887 | 11 | cornered:1 |
| v21-hybrid-1-10 | 1.993 | 15.186 | 0.1739 | 1.0 | 8 | low_hp:1 |

## 4. 典型局死前关键时间线回放 (Last 5 Trace Events)

### `v21-hybrid-1-01` (共 127 条轨迹采样)
- `tick=504` `scroll=-1.733` `hp=1` `anchor=[0.6048, 0.5789]` `age_ms=722` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=510` `scroll=-1.733` `hp=1` `anchor=[0.6048, 0.5789]` `age_ms=829` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=516` `scroll=-1.733` `hp=1` `anchor=[0.6048, 0.5789]` `age_ms=940` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=522` `scroll=-1.734` `hp=None` `anchor=[0.6048, 0.5789]` `age_ms=1044` `opt=jump_over(hysteresis)` `act=None` `threats=2`
- `tick=523` `scroll=-1.734` `hp=None` `anchor=[0.6048, 0.5789]` `age_ms=1051` `opt=jump_over(hysteresis)` `act=None` `threats=2`

### `v21-hybrid-1-02` (共 137 条轨迹采样)
- `tick=600` `scroll=-1.668` `hp=1` `anchor=[0.614, 0.4449]` `age_ms=299` `opt=jump_over(commit)` `act=None` `threats=2`
- `tick=605` `scroll=-1.668` `hp=1` `anchor=[0.614, 0.4449]` `age_ms=384` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=606` `scroll=-1.668` `hp=1` `anchor=[0.614, 0.4449]` `age_ms=410` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=612` `scroll=-1.668` `hp=1` `anchor=[0.614, 0.4449]` `age_ms=523` `opt=jump_over(commit)` `act=dash` `threats=2`
- `tick=615` `scroll=-1.668` `hp=None` `anchor=[0.614, 0.4449]` `age_ms=1210` `opt=jump_over(hysteresis)` `act=dash` `threats=1`

### `v21-hybrid-1-03` (共 150 条轨迹采样)
- `tick=611` `scroll=-2.218` `hp=1` `anchor=[0.1268, 0.8726]` `age_ms=698` `opt=dash_through(switch)` `act=None` `threats=2`
- `tick=612` `scroll=-2.218` `hp=1` `anchor=[0.1268, 0.8726]` `age_ms=729` `opt=dash_through(commit)` `act=None` `threats=2`
- `tick=618` `scroll=-2.219` `hp=1` `anchor=[0.1268, 0.8726]` `age_ms=1454` `opt=dash_through(continue)` `act=None` `threats=1`
- `tick=621` `scroll=-2.219` `hp=1` `anchor=[0.1268, 0.8726]` `age_ms=1497` `opt=dash_through(commit)` `act=jump` `threats=1`
- `tick=624` `scroll=-2.219` `hp=None` `anchor=[0.1268, 0.8726]` `age_ms=1547` `opt=dash_through(commit)` `act=jump` `threats=0`

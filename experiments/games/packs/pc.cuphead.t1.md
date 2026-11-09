# Cuphead T1 证据（2026-11-09）

## 结论

Cuphead 达到 **T1**（本 goal 定义）：

- attach 成功；
- 窗口级抓屏成功（`PrintWindow` fallback）；
- 初始 OCR：`Press Any Button`；
- 按键脉冲：`ENTER` 变化比例 **0.8144**，中心 (0.5, 0.5)；
- 按 `ENTER` 后 OCR：`START / OPTIONS / DLC / EXIT`，主菜单可见；
- 方向键/确认/取消候选由探针自动给出；
- 全程无人工示范；探针命令：

```powershell
python scripts/probe_game.py --window "Cuphead" --window-capture --keys "ENTER,Z,SPACE,DOWN,UP"
```

## 局限

- 这是 T1，不是 T2；没有连续 5 分钟游玩，也没有通关；
- `PrintWindow` 是 fallback：部分硬件加速窗口可能返回黑帧；本次 Cuphead 正常；
- 探针只给键位“建议”，没有证明每个键的完整语义；
- Cuphead 仍是 depth regression，不恢复 10/7 KPI。

## 原始草稿

- `tmp/cuphead-probe.pack.json`（本地，不入库）
- `tmp/cuphead-probe2.pack.json`（本地，不入库）
- 本文件是 curation 后的证据；pack 见 `pc.cuphead.t1.json`。

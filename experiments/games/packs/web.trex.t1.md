# Local T-Rex T1 证据（2026-11-09）

## 结论

本地开源 T-Rex runner（`wayou/t-rex-runner`，仅本地 tmp，不入库）达到 **T1**：

- Chrome app 窗口 `t.rex extracted`；
- 窗口级抓屏成功；
- OCR 初始 `00000`；
- `SPACE` / `UP` / `DOWN` 均有帧差；
- 命令：

```powershell
python scripts/probe_game.py --window "t.rex" --window-capture --keys "SPACE,UP,DOWN"
```

## 边界

- 这是 T1；T2 由 `play_pack.py` 的 5 分钟 autoplay 另测；
- 开源页面只放本地 `tmp`，不提交资源；
- 方向/跳跃语义仍由探针建议 + 人工 curation，不是自动证明。

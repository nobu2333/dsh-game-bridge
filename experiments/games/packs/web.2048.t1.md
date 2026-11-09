# 2048 T1 证据（2026-11-09）

## 结论

2048 达到 **T1**：

- 本地 `serve_webgl.py` 服务开源 2048（MIT，未入库游戏资源）；
- Chrome app 窗口 `2048`，窗口级抓屏成功；
- OCR：`2048 / SCORE / BEST / Join the numbers and get to the 2048 tile! / New Game`；
- 四个方向键都有帧差，`RIGHT` 最高 **0.0666**，首次有效动作成立；
- 全程无人工示范；
- 命令：

```powershell
python scripts/probe_game.py --window "2048" --window-capture --keys "LEFT,RIGHT,UP,DOWN"
```

## 边界

- 这是 T1，不是 T2；没有连续 5 分钟策略验证；
- 2048 是开源浏览器游戏，不是商业 3A；作为“鼠标/键盘浏览器 + 前台修复”的第二种类型验证；
- 游戏资源只放在本地 `tmp`，不提交仓库；
- 探针只给方向键建议；没有证明所有键语义。

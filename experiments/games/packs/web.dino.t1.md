# Chrome Dino T1 证据（2026-11-09）

## 结论

Dinosaur Game（Chrome Dino 在线版）达到 **T1**：

- Chrome app 窗口 `Dinosaur Game — Chrome Dino T-Rex Run Online`；
- 窗口级抓屏 + `force_foreground` 成功；
- OCR 初始：`Press Space or tap to jump; ... 00000`；
- 发送 `SPACE` 后分数从 **00000 → 00029**，首个有效动作成立；
- 探针/VLM 不需要人示范。

## 命令

```powershell
python scripts/probe_game.py --window "Dinosaur Game" --window-capture --keys "SPACE,UP,DOWN"
```

## 边界

- 这是 T1，不是 T2；
- 在线页面，不提交任何页面资源；
- 只验证了 SPACE/UP/DOWN 的候选映射，未验证长时间生存；
- 5 分钟 autoplay 实测被页面广告遮罩/GAMEOVER 干扰，**T2 无效，不声称**；
- 下一步换无广告的 T2 目标。

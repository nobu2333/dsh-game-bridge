# Local T-Rex T2 证据（2026-11-09）

## 结论

本地开源 T-Rex runner 达到 **T2**（按本 goal 定义）：

- 连续 **301.55 秒**；
- **237** 次动作，0 错误；
- 窗口抓屏 + `force_foreground` 正常；
- OCR 分数从 `HI 00053` 提升到 `HI 00089`；
- 过程中出现 `GAMEOVER` 后继续输入，属于 runner 的死亡/重开循环，不是菜单空转。

## 命令

```powershell
python scripts/play_pack.py --pack experiments/games/packs/web.trex.t1.json --duration 300
```

## 边界

- T2 只要求 5 分钟有意义游玩，不要求单命通关；
- 这是“每 800ms SPACE”的 pack autoplay，不是智能策略；
- 没有证明跨游戏泛化，只证明该 pack + window capture + input 能维持 5 分钟；
- 开源页面只放本地 `tmp`，不提交资源。

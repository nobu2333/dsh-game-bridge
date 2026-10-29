# dsh-game-core

`dsh-game-bridge` 的本地引擎：**抓屏 + OCR + 将来的 20 Hz 闭环**。
独立进程、stdio JSON 协议、不认识模型也不认识 DSH。

## 为什么单独一个包

- 插件壳（npm）要被 DSH 的市场沙箱干净安装，不能带原生依赖；
- Python 的 CV/OCR/手柄生态现成，引擎可以独立升级；
- 引擎崩溃不该带走 harness；harness 卸载插件时要能整棵杀掉引擎。

## 协议（v0，一行一条）

```jsonc
// 请求（region 可选：attach 到窗口后由会话自动填入）
{"id": 1, "method": "snapshot", "params": {"ocr": true, "max_width": 1280, "region": {"left": 239, "top": 203, "width": 1280, "height": 800}}}
// 成功
{"id": 1, "ok": true, "result": {"png_b64": "...", "width": 1280, "height": 800, "scale": 1.0, "region": {...}, "ocr": [...], "captured_at_ms": 0}}
// 失败
{"id": 1, "ok": false, "error": {"code": "ENCODE_FAILED", "message": "..."}}
```

方法：`ping` · `selftest` · `snapshot` · `attach` · `act` · `plan` · `status` · `stop`。

`attach` 接受窗口标题子串（大小写不敏感）：优先后台只截该窗口；找不到时返回
`WINDOW_NOT_FOUND` 并列出当前可见窗口，便于换关键词。传 `unspecified` 退回整屏。

## 自检

```bash
python -m dsh_game_core selftest            # 依赖 / 显示器 / OCR 预热
python -m dsh_game_core selftest --capture  # 再加一次真实抓屏（只读，不注入输入）
python -m dsh_game_core serve               # 插件用的 stdio 服务
```

## 已固定下来的实测教训

- RapidOCR 必须 `det_limit_type="max"`、`det_limit_side_len=960`：
  默认 `min` 会把 640×80 的 HUD 区域放大到短边 736px，det 从 ~9ms 变成 ~1.3s。
- 一次性 `grab()`，不开连续捕获线程：采样只有 2–5 Hz，起线程只会抢游戏帧数。
- 抓屏是只读操作；任何**输入注入**能力（M2）必须另有夺回热键与反作弊拒绝。

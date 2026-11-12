# M5 运行手册：让模型自己玩一局 2048

> 状态：**准备就绪，等待一次真实的 DSH 会话**。
> 协议规则见 [PLAY](PLAY.md)；本文件只写操作步骤，照着做即可。
> 目标游戏是 MIT 开源的 2048（`gabrielecirulli/2048`），只用来验证「模型通过插件工具玩得比随机好」。

## 0. 已验证 / 未验证

| 环节 | 状态 |
|:--|:--|
| 本地启动 2048、窗口抓屏、OCR 读分数 | ✅ 已实测（2026-11-12） |
| 随机 / 固定循环基线脚本与对照数据格式 | ✅ 已实测（真实键盘注入，分数正确） |
| 模型通过 DSH 会话玩完一局 | ❌ **未做，需要你跑一次** |

## 1. 准备游戏（两个终端常驻）

```powershell
cd <repo>

# 终端 A：静态文件服务器。--port 0 会自动选空闲端口，记下输出的端口号。
python scripts\serve_webgl.py --root tmp\2048-src --port 0
#   serving ... at http://127.0.0.1:<PORT>/

# 终端 B：用独立 profile 打开 Chrome 应用窗口（标题是 2048）。
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://127.0.0.1:<PORT>/ `
  --window-size=760,900 --window-position=80,80 `
  --user-data-dir="<repo>\tmp\m5-model-profile" --no-first-run --no-default-browser-check
```

窗口打开后先做一次只读检查：

```powershell
python scripts\record_model_run.py --window 2048 --reads 1 --no-write
```

应输出 `score=0 best=0`（新 profile 的初始值）。如果读不到，先解决抓屏/OCR 再继续。

## 2. 准备 DSH（真实后端 + 审批）

1. 插件要装在**你实际使用的宿主 profile**里：
   - 桌面版：应用内 **设置 → 插件** 安装 `dsh-game-bridge`；
   - `dsh web`：`dsh plugin --profile web add dsh-game-bridge`。
2. 启动宿主前设置环境变量（**宿主启动时读取，中途改无效**）：

```powershell
$env:DSH_GAME_BRIDGE_CONTROL='keyboard'   # 真实键盘输入
$env:DSH_GAME_BRIDGE_CAPTURE='window'     # PrintWindow 窗口级抓屏
dsh web                                    # 或直接打开桌面版（setx 写用户级变量后重启应用）
```

3. 确认权限预设是 `ask` 而不是 `never`，否则 `game_attach` 会被自动拒绝。
4. 重启宿主后，在新会话里先让模型调一次 `game_selftest`，确认插件、引擎、后端都就绪。

## 3. 给模型的任务提示（直接复制）

```text
你要通过 game_* 工具玩一局 2048，目标是拿到尽可能高的分数。

规则：
1. 先调用 game_selftest，再用 game_windows 找到标题含 2048 的窗口，
   然后 game_attach window="2048"。
2. 之后每一步：game_snapshot 看棋盘 → 选一个方向 → game_act button="UP"（或 DOWN/LEFT/RIGHT）。
   每次只按一个方向键，不要连续盲按；按完再看下一张截图。
3. 不要使用 game_plan、game_policy、game_intent。
4. 结束条件（任一满足就停）：画面出现 Game over；连续 5 步画面没有变化；已经走了 300 步。
5. 结束时调用 game_status，记下 actions_total；再调用 game_stop。
6. 最后报告：结束原因、你走了多少步、屏幕上显示的最终分数（SCORE）。

开始吧。
```

> 说明：模型每步的 `game_snapshot` 自带 OCR（约 2–4 秒），所以不需要额外 sleep；
> 如果它连续按键，可能读到动画中间帧，允许它重看一次再决定。

## 4. 记录模型这一局

模型停止、但**游戏窗口仍然开着**时，运行：

```powershell
python scripts\record_model_run.py --window 2048 `
  --player model:deepseek `
  --game 2048 --build "gabrielecirulli/2048@master" `
  --steps <game_status 里的 actions_total> `
  --wall-s <这一局的大致耗时秒数> `
  --end-reason "phrase:game over"     # 或 step_limit / static
```

脚本用与基线**完全相同**的 OCR 解析读最终分数，写进 `experiments/results/m5-model.jsonl`。
如果读到的分数和模型自己的报告差异很大，以脚本读数为准，并在记录里加 `--notes` 说明。

## 5. 跑对照组（各 5 局）

同一台服务器不用关；基线脚本会自己开新窗口、用新的浏览器 profile，每局从零开始：

```powershell
# 随机方向（5 局）
python scripts\run_baseline.py --window 2048 --mode random --runs 5 --max-steps 300 `
  --step-interval-ms 300 --ocr-every 10 `
  --url http://127.0.0.1:<PORT>/ --build "gabrielecirulli/2048@master" `
  --out experiments\results\m5-baseline.jsonl

# 固定循环（5 局）
python scripts\run_baseline.py --window 2048 --mode cycle --runs 5 --max-steps 300 `
  --step-interval-ms 300 --ocr-every 10 `
  --url http://127.0.0.1:<PORT>/ --build "gabrielecirulli/2048@master" `
  --out experiments\results\m5-baseline.jsonl
```

> 基线脚本每局都会杀掉自己启动的浏览器实例，不影响你开着的模型那局窗口。
> 已实测：每局约 0.2–0.3 秒/步，重复运行结果稳定，脚本会在最后打印分数中位数。

## 6. 判定（照 PLAY §9）

读取两个 JSONL：

```powershell
Get-Content experiments\results\m5-model.jsonl
Get-Content experiments\results\m5-baseline.jsonl
```

- 模型组只有 1 局的话，先跑 3 局模型、5 局随机、5 局固定循环再下结论；
- **M5 完成**：模型组分数中位数 > 两个对照组的中位数，且最差一局不低于对照组中位数的一半；
- 结果写进 `experiments/results/m5-2026-xx-xx.md`（正负都写），并在 [STATUS](STATUS.md) 更新。

## 7. 常见问题

| 现象 | 处理 |
|:--|:--|
| `game_snapshot` 返回 `source: synthetic fallback` | 引擎没就绪。先 `game_selftest`，看 `install` / `report`；这一局作废 |
| `game_attach` 报需要审批但被拒绝 | 宿主权限预设是 `approval: never`；改成 `ask` 后重启宿主 |
| `FOREGROUND_MISMATCH` | 游戏窗口不在前台。让用户点一下游戏窗口；插件不会自己抢焦点 |
| 截到的画面是别的窗口 | `DSH_GAME_BRIDGE_CAPTURE=window` 是否生效；看 `game_snapshot` 的 `occluded` 字段 |
| 基线与模型窗口互相干扰 | 不要同时跑；基线用独立浏览器 profile，模型那局窗口保持在前台 |

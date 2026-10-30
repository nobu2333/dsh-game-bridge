# field-2026-10-29 —— 首次真实游戏实机测试的证据包

这是 2026-10-29 晚上对 `dsh-game-bridge@0.0.1` 做 Cuphead 实机测试时留下的东西，
配套主报告在 **`docs/FIELD-2026-10-29.md`**。主报告是结论，这里是可以自己复跑/复核的证据与工具。

> **公开版编辑说明**：本目录是 2026-10-29 的历史证据，为公开发布只做了路径泛化
> （本机绝对输出路径改为 `<local-output>`），证据文件、截图与审计条目均未改动。

## 先读什么

1. `docs/FIELD-2026-10-29.md` —— 问题清单、根因假设、修法建议、下次实机测试清单（§8）；
2. `docs/STATUS.md` —— 插件当前工程状态；
3. 本目录的 `harness/` —— 当晚绕过「宿主 env 锁死」用的临时驱动（见下）。

## 目录

```text
docs/field-2026-10-29/
├── README.md                  # 本文件
├── evidence/
│   ├── menu.png               # Cuphead 主菜单（attach 成功后抓到的画面）
│   ├── menu-after-two-A-presses.png   # 两次手柄 A 之后：与上一张逐字一致（输入没到游戏）
│   └── audit.jsonl            # 引擎审计：attach / act×2 / stop（backend=vgamepad, dry_run=false）
└── harness/
    ├── drive_server.py        # 把 dsh_game_core.GameSession 挂到 127.0.0.1:47654 的临时驱动
    ├── ctl.py                 # 给 drive_server 发一条指令（命令行客户端）
    ├── xinput_probe.py         # 读 XInput 0..3 槽位 + 按键位（验证虚拟手柄）
    ├── slot_test.py           # 一次性实验：新开 pad 看落哪个槽位、退出是否释放
    └── measure.py             # 只读延时测量：attach / snapshot / events / windows / status
```

## 关于 harness 的警告（重要）

`harness/` 不是推荐用法，是**当晚为了绕过「真实后端在宿主启动时定死」的临时手段**：
它不经过插件工具层的审批闸，直接在同一台机器上起第二个引擎实例、创建第二个虚拟手柄。

- 它**只应在真人在场时使用**（引擎的 F12 夺回与反作弊拒绝仍在，但绕过审批这件事本身就要求人明确同意；
  「无人闸」已于 2026-10-30 从当前代码移除，本目录只是历史证据）；
- 同机重现时注意：多个虚拟手柄会争 XInput 槽位（见主报告 P1-3），用完必须杀进程；
- 正式路径仍然是：`DSH_GAME_BRIDGE_CONTROL=vgamepad` + DSH 审批，再走 `game_attach`。

用法（引擎缓存里的 Python 自带依赖）：

```powershell
# 起驱动（后台）
& "$env:LOCALAPPDATA\dsh-game-bridge\engine\0.0.1\Scripts\python.exe" .\harness\drive_server.py
# 另开一个终端发指令
& "$env:LOCALAPPDATA\dsh-game-bridge\engine\0.0.1\Scripts\python.exe" .\harness\ctl.py snapshot
& "$env:LOCALAPPDATA\dsh-game-bridge\engine\0.0.1\Scripts\python.exe" .\harness\ctl.py status
```

注意：`drive_server.py` 会在 `%LOCALAPPDATA%\dsh-game-bridge\engine\0.0.1` 里用到 `vgamepad` ——
**发布版的引擎 venv 默认没有装 vgamepad**（主报告 P0-5），当晚是手工从另一个 venv 复制进去的。

## 没随仓库分发的证据

「抓屏拍到遮挡窗口」那张截图（attach 在 Cuphead 上、snapshot 却返回 DSH 聊天界面）**没有放进仓库**：
画面里有 DSH 会话内容，不适合放进公开仓库。原件在本机：

```text
<local-output>\game-bridge\frames\snap-1793279702185.png
```

需要入库的话请先脱敏（打码会话内容）再放进来。

## 状态

本目录与 `docs/FIELD-2026-10-29.md` 是实机测试的历史记录；公开版随仓库首次入库，
内容只做了路径泛化，结论与证据文件未改动。

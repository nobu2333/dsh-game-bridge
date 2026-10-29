# 设计决策（dsh-game-bridge）

> 这份文件只记「为什么这样做」以及被证据钉死的约束。改代码前先读它；
> 与它冲突的实现要么改代码，要么先改这里。

## 1. 形态：两层，中间隔一条稳定缝

```
┌──────────────────────────── DSH 宿主进程 ────────────────────────────┐
│  dsh-game-bridge（npm 包，本仓库）                                    │
│    · cordis 插件：defineTool 注册 game_* 工具                         │
│    · 引擎监督：检查 / 自举 / 拉起 / 清理子进程                        │
│    · 安全闸：夺回热键、反作弊拒绝、无人不自娱                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ stdio JSON（MCP 兼容子集）
┌───────────────────────────────▼──────────────────────────────────────┐
│  dsh-game-core（Python 包）                                          │
│    · 抓屏 / 帧差分 / OCR / 20 Hz 追踪                                │
│    · 虚拟手柄 / 键鼠 / 窗口焦点 / 输入法看护                          │
│    · 本地 20 Hz 闭环（导航 / 避障 / 走位 / 弹反）                     │
│    · 引擎探针与游戏档案（纯数据）                                     │
└──────────────────────────────────────────────────────────────────────┘
```

**为什么引擎必须是独立进程**：Python 的 CV/OCR/手柄生态是现成的；Node 侧重写这些
不划算。同时独立进程能在插件被 HMR 卸载时被整棵杀掉，不留孤儿。

**为什么插件壳要自己注册原生工具、而不是给用户配一条 MCP**：
`@deepseek-ai/dsh-mcp-client` 不在 `dsh-base` 里，用户得先装它再手写 YAML——
对「填个包名就装上」的目标是致命摩擦。原生注册还能拿到工具展示、审批与超时的统一处理。

## 2. 工具面：目标级，不是步进级

模型一次工具调用 3–5 秒。让模型逐步决定「往右走一步」，游戏里就是植物人。
因此工具只暴露：

| 工具 | 语义 | 频率 | 状态 |
|:--|:--|:--|:--|
| `game_selftest` | 装没装上、引擎在哪一步 | 一次 | M1 ✅ |
| `game_snapshot` | 看一眼（图 + OCR） | 模型需要时 | M1 ✅ |
| `game_windows` | 列出可见窗口（标题/进程/尺寸） | 一次/局 | M2 ✅ |
| `game_controls` | 当前后端支持的按钮/按键 | 一次/局 | M2 ✅ |
| `game_events` | 帧差分事件（baseline/static/changed/scene_cut） | 稀疏轮询 | M2 ✅ |
| `game_attach` | 绑定窗口（用户授权步骤） | 一次 | M2 ✅ |
| `game_act` | 单步按键（默认 dry-run） | 一次/动作 | M2 ✅ |
| `game_stop` | 松手 + 解绑 | 随时，越易越好 | M2 ✅ |
| `game_plan` | 给目标，启动本地 20 Hz 循环（hold / tap / advance 撞墙侧移脱困） | 一次/目标 | M3 ✅（dry-run 验证） |
| `game_status` | 轮询进度与事件 | 稀疏 | M3 ✅ |

**判定标准**：任何工具如果要求模型以高于 1 Hz 的频率调用，就说明它设计错了。

闭环实现（`session.plan`）：本地线程按 20 Hz 跑（实测 21.3 Hz），**每一拍重新过
安全闸**——命中反作弊、超过无人时限、或 F12 闩锁，都在一拍内释放按键并记录
`stop_reason`；`game_stop` 立刻停止并松手。模型只发一次 `game_plan`，不逐拍调用。

## 2.5 M2 的安全闸实现（safety.py / control.py）

输出通道有三道硬闸，全部在引擎侧、可注入、可单测：

1. **反作弊**：`tasklist` 进程名前缀匹配 EAC/BattlEye/Vanguard/ACE…，命中即拒绝；
2. **无人不自娱**：`GetLastInputInfo` 距离上次输入超过 `DSH_GAME_BRIDGE_UNATTENDED_S`
   （默认 180s）即拒绝；**拿不到输入遥测也拒绝**（fail-closed）；
3. **随时可夺回**：F12 一旦按下即闩锁拒绝，重新 `game_attach` 才解除。

输出后端默认 `dry-run`（只记录动作、不碰设备）；真实手柄必须显式
`DSH_GAME_BRIDGE_CONTROL=vgamepad`，且 vgamepad 后端尚未实机验证。

## 3. 图片：走宿主 attachment，不搬 base64

`ToolOutputDefinition.render(args, value)` 返回 `ContentBlock[]`；图片块是
`{ type: 'image', attachment: ImageAttachmentRef }`，引用由 `ctx.attachments.saveImage()`
落盘。会话文本里只留尺寸与来源，字节不进历史。M0 已用合成帧验证这条链路。

## 3.5 窗口级抓屏（不是整屏）

`game_attach` 接受窗口标题子串，用只读 Win32 API（EnumWindows / GetWindowText /
DwmGetWindowAttribute）解析出窗口矩形；之后每次 `snapshot` 重新读一次矩形再裁剪，
窗口移动/缩放不会拍偏。找不到窗口时返回 `WINDOW_NOT_FOUND` 并列出当前可见标题——
比「随便截个整屏让模型猜」有用得多。

实测（本机）：attach 到 1280×800 的窗口后，帧尺寸与裁剪区完全一致
（`region {left:239, top:203, width:1280, height:800}`，OCR 读出 32–54 行界面文字）。

**多显示器**：`EnumDisplayMonitors` + `GetMonitorInfoW` 拿到每块显示器的虚拟桌面
坐标，`MonitorFromWindow` 找窗口所在屏；`capture.match_output_index` 用分辨率与主屏
标记把它映射到 DXcam 的 output 序号，裁剪区换算成「相对该显示器原点」。引擎按
output 缓存抓屏器。已知边界：两块同分辨率且都不是主屏时，dxcam 不暴露输出坐标，
只能按序号确定性选择（可能选错）。

## 4. 安装与自举

- 官方安装 = `dsh plugin --profile <p> add dsh-game-bridge`；实行验证过它会把包
  自动选进 `dsh.profile.bundles`（无需手改 profile）。
- **零 install 脚本**：市场不收需要手动放行构建脚本的插件；pnpm 也可能拦脚本。
  因此引擎在**首次激活**时自举（M1 已实现并验证）：`uv venv <cache>/<version>` →
  `uv pip install dsh-game-core==<version>` → 用缓存里的 Python 起引擎。
  用户机器不需要预装 Python；**但需要 uv**（缺失时工具结果给出安装命令，
  自动下载 uv 留到发布前再做）。
- 自举是**非阻塞**的：插件装载即开始，状态机 `idle → installing → ready | failed`；
  工具调用最多等 20 秒（可配），没等到就降级合成帧并写明原因。
- 引擎未就绪时绝不假装能玩；`game_selftest` 永远报告真实状态。
- 缓存与覆盖：`%LOCALAPPDATA%\dsh-game-bridge\engine\<version>`；调试可用
  `DSH_GAME_BRIDGE_PYTHON`（现成 Python）、`DSH_GAME_BRIDGE_ENGINE_SPEC`（自定义安装源）、
  `DSH_GAME_BRIDGE_CACHE_DIR`、`DSH_GAME_BRIDGE_PYTHON=off`（强制合成帧）。

## 5. 版本兼容（踩过的坑）

DSH 的兼容性检查是**严格 semver**，而运行时版本常带预发布标签（本机 `0.2.1-rc.2`）。
`^0.2.0-rc.2` 这类范围**不匹配** `0.2.1-rc.2`（预发布规则），会让插件被静默跳过
——本机就有一个 `dshmarketplace-plugin@0.2.0` 正因此被跳过。所以：

- `engines.dsh` 与 `peerDependencies` 都写 `>=0.2.1-rc.2 <0.3.0`；
- 每次 DSH 发布新版本，必须同步这两个范围并实测 `dsh --dump-config` 无警告。

## 6. 安全边界（发布版必须成立，代码里实现）

1. **随时可夺回**：本地热键/鼠标一动即松手，不经模型、不经会话；
2. **无人不自娱**：无人类输入且无显式 `game_plan` 授权时不输出；
3. **反作弊不接**：命中 EAC/BattlEye/Vanguard 等进程即拒绝一切输出通道；
4. **默认只读**：发布版只做抓屏 + 手柄，不读内存、不注入；
5. **真实后端需批准**：`DSH_GAME_BRIDGE_CONTROL` 不是 dry-run 时，插件注册
   `tools/pre-execute` 钩子，对 `game_attach` 返回 `{kind:'ask'}`，走 DSH
   user-approval 的一次性批准；headless/CI 没有应答者时 fail-closed 拒绝。
   dry-run 下不注册钩子——只记录动作的操作不值得打断用户；
6. **可审计**：`DSH_GAME_BRIDGE_AUDIT_LOG` 打开后，`attach / act / plan_start /
   plan_end / stop` 与 `act_blocked / plan_blocked` 全部写本地 JSONL；写失败只记
   在条目里，不影响主流程。默认关闭，路径完全由用户指定。

## 6.5 引擎生命周期（M1 实测踩到的坑）

- **子进程与它的管道必须 `unref`**：插件跑在 DSH 宿主进程内，普通 `spawn` 会让
  宿主的事件循环被引擎握住。实测 `dsh headless` 任务已经完成、JSON 事件也输出了
  `turn_end completed`，但进程**永不退出**，最后被外部超时杀掉，表现为 exit code 1。
  修复：`child.unref()` + `stdin/stdout/stderr.unref()`。
- **不能只靠 `ctx.on('dispose')` 清理**：headless 成功路径是设置 `process.exitCode`
  等事件循环自然排空，并不会逐插件 dispose（实测 dispose 从未被调用）。因此必须有
  `process.once('exit')` 兜底 `kill`，同时保留 dispose 供 HMR/Web 卸载时使用。
- **每个请求必须有超时**：抓屏可能卡在 DXGI；超时后工具降级并报告原因，不能挂住
  模型轮次。
- **Windows 控制台默认 GBK**：引擎被插件 spawn 时没有 `PYTHONIOENCODING`，把中文
  窗口标题写进 stdout 会抛 `UnicodeEncodeError`，整个引擎进程 exit 1（实测在
  `game_windows` 上炸）。修复：引擎启动时强制 UTF-8 stdio，插件 spawn 时兜底设
  `PYTHONIOENCODING=utf-8`。
- **崩溃自愈**：引擎意外退出后，下一次工具调用会**重建客户端**（复用已装好的
  引擎路径，不再自举）。不自动重放上一次请求——`attach`/`act` 不是幂等操作。
  引擎内状态（attach、闭环）会丢，这是有意的：重来一次比在不确定状态下继续安全。
- **首帧 DXcam 初始化实测 ~340ms**（之后 grab ~5ms）。`attach` 会预热抓屏器，把这
  个成本移出闭环第一拍；闭环里「静止时长」用真实经过时间累积，不用固定 50ms 节拍，
  否则首拍会让阈值失真。实测 `advance` 在真实屏幕上达到 ~16–20 Hz。
- 引擎的 stdio 只走协议，诊断一律 stderr；错误码稳定（`ENGINE_TIMEOUT`、
  `ENGINE_EXITED`、`ENGINE_SPAWN_FAILED`）。

## 7. 平台

v1 仅 Windows 10/11 x64（DXcam、ViGEmBus、Win32 输入）。抽象层留好接口，
但不承诺跨平台；ViGEmBus 已 EOL，长期要给替代路径或退到模拟器键盘通道。



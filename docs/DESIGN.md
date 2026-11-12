# 设计决策（dsh-game-bridge）

> 这份文件只记「为什么这样做」以及被证据钉死的约束。改代码前先读它；
> 与它冲突的实现要么改代码，要么先改这里。项目现状与方向以 [STATUS](STATUS.md) 为准。

## 0. 范围：只做慢节奏游戏（2026-11-12）

插件给模型提供看和按的能力，**决策由模型做**。模型一次决策实测约 9 秒，所以只针对慢节奏游戏
（回合制、益智、菜单为主、视觉小说、模拟经营）。实时动作游戏不在范围内：本地启发式视觉加
60 Hz 策略那条路线在 Cuphead 上验证没有收益，已冻结（见 STATUS「能力层与代码去向」）。

下文 §2.6 描述的 WorldState / PolicyRunner 是那条路线留下的代码，保留是为了记录行为，不代表方向。

## 1. 形态：两层，中间隔一条稳定缝

```
┌──────────────────────────── DSH 宿主进程 ────────────────────────────┐
│  dsh-game-bridge（npm 包，本仓库）                                    │
│    · cordis 插件：defineTool 注册 game_* 工具                         │
│    · 引擎监督：检查 / 自举 / 拉起 / 清理子进程                        │
│    · 安全闸：夺回热键、反作弊拒绝、真实后端审批                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ stdio JSON（MCP 兼容子集）
┌───────────────────────────────▼──────────────────────────────────────┐
│  dsh-game-core（Python 包）                                          │
│    · 抓屏（整屏裁剪 / PrintWindow 窗口级）/ 帧差分 / OCR             │
│    · 虚拟手柄 / 键盘 / 鼠标点击 / 窗口焦点                            │
│    · 本地 20 Hz 有界按键循环（hold / tap / advance）                  │
│    · WorldState + 60 Hz 策略（已冻结）                                │
│    · 游戏档案 profile / GamePack（纯数据）                            │
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
| `game_state` | 读一次通用世界状态 WorldState（场景 / HP / 实体 / UI） | 模型需要时 | 通用基线 ✅ |
| `game_policy` | 起停本地 60 Hz 状态策略（按 profile 射击/前进/闪避/脱困） | 一次/战斗阶段 | **已冻结** |
| `game_intent` | 向运行中的策略提交带 TTL/优先级的战术 Intent（建议性，不直接按键；当前执行 jump/dodge/retreat） | 0.2–1Hz | **已冻结** |
| `game_memory` | 本地游戏档案（profile）CRUD 与选用 | 开局 / 换游戏 | 通用基线 ✅ |
| `game_act` | 单步按键 / 手柄按钮，或带 `x`/`y` 的鼠标点击（默认 dry-run） | 一次/动作 | M2 ✅；鼠标坐标目前是屏幕绝对坐标 |
| `game_stop` | 松手 + 解绑 | 随时，越易越好 | M2 ✅ |
| `game_plan` | 给目标，启动本地 20 Hz 循环（hold / tap / advance 撞墙侧移脱困） | 一次/目标 | M3 ✅（dry-run 验证） |
| `game_status` | 轮询进度与事件 | 稀疏 | M3 ✅ |

**判定标准**：任何工具如果要求模型以高于 1 Hz 的频率调用，就说明它设计错了。
慢节奏游戏里，模型每步一次 `game_snapshot` + `game_act` 是正常用法，不违反这条：游戏本身不要求更快。

闭环实现（`session.plan`）：本地线程按 20 Hz 跑（实测 21.3 Hz），**每一拍重新过
安全闸**——命中反作弊或 F12 闩锁，都在一拍内释放按键并记录 `stop_reason`；
`game_stop` 立刻停止并松手。模型只发一次 `game_plan`，不逐拍调用。

另有一条 60 Hz 状态策略（`game_policy` / `PolicyRunner`，见 §2.6）：它吃 WorldState
的廉价实体与 profile，负责战斗反射（射击 / 前进 / 闪避 / 卡住脱困）。两条闭环都由
本地线程驱动、逐拍复检安全闸，模型只在起停时出现。

## 2.5 M2 的安全闸实现（safety.py / control.py）

输出通道有**两道**硬闸，全部在引擎侧、可注入、可单测：

1. **反作弊**：`tasklist` 进程名前缀匹配 EAC/BattlEye/Vanguard/ACE…，命中即拒绝；
2. **随时可夺回**：F12 一旦按下即闩锁拒绝，重新 `game_attach` 才解除。

**为什么没有「无人不自娱」**：这条规则继承自宿主项目（陪伴场景），对本项目不适用。
本插件的正常用法就是让 agent 自己玩；用 `GetLastInputInfo` 判断「人在不在」会误杀
用手柄的真人玩家，而 keyboard 后端的 SendInput 注入又会刷新该时间戳，闸本身还可
被自己遮蔽。因此 2026-10-30 直接移除了这条规则（而不是修补信号）；无人值守是否
使用由用户自己决定，真实输出后端仍由 DSH 审批闸与 F12 夺回兜底。

输出后端默认 `dry-run`（只记录动作、不碰设备）；真实手柄必须显式
`DSH_GAME_BRIDGE_CONTROL=vgamepad`（单次动作已实机回读验证，长闭环尚未在真实游戏里跑）。

## 2.6 通用玩法基线：WorldState / StateProvider / Policy / GameProfile（策略部分已冻结）

> 2026-11-12：本节的 PolicyRunner、Intent 以及 §2.6 末尾的「两个闭环的分工」都已冻结，见 §0。

> 2026-10-30 起。此前引擎只有方向原语（`game_plan`），「游戏里现在发生了什么」没有
> 通用表示。通用基线把**状态**也抽出来：引擎零游戏代码，游戏差异只进 JSON 档案。
> 数据形状与降级规则见 [STATE.md](STATE.md)。

分层（自下而上）：

1. **采集层**（既有）：DXcam 整屏抓 + 窗口矩形裁剪 / RapidOCR。
2. **视觉保底（StateProvider: vision）**：每帧从画面 + OCR 行产出 WorldState
   （scene / player / entities / ui）。坐标归一化、未知为 `null`、提取器**不抛异常**、
   无 OCR 的廉价实体路径有单独的性能预算（契约目标 <3 ms @962×567，实际以引擎单测为准）。
   这是**地板**：没有档案、没有内存、没有网络也能给出状态，
   哪怕其中一些字段是 `unknown`。
3. **档案（GameProfile，纯数据）**：键位、HUD 区域、场景关键词、颜色阈值、闪避/卡住参数。
   引擎按字段解释，不按游戏名分支；字段全可选，缺省用代码默认值。仓库只放通用样例
   （Cuphead dogfood），用户档案是用户本地数据。
4. **可选 provider（设计位，未实现）**：memory / API。它们能给出更早或更准的状态
   （例如玩家坐标、boss 数值），但只允许覆盖自己声明的字段；失败时保留下层结果并标
   `game.stale`，而不是让整次读取失败。
5. **策略层（PolicyRunner，60 Hz）**：每拍读当帧 WorldState 的廉价实体与 profile 参数，
   输出 hold / advance / dodge / stuck-probe；每拍重过安全闸，退出必 `release_all`。
   它不消费 stale 数据，也不按游戏名分支。

### 为什么内存不是地基

- **稳定性**：内存偏移随补丁失效；视觉地板不会因为一次版本更新就整体瘫痪。
- **合规/可用性**：读内存正是反作弊与 ToS 的红线；本项目公开仓库不携带任何偏移/CT 表。
- **可分发**：仓库只放通用字段的样例档案；用户本地档案不进仓库、不打进 npm 包。
- **降级明确**：provider 缺失时基线仍然成立；provider 失败时是 `stale` + 视觉状态，
  而不是整体失败。因此「先有视觉基线，再按需加加速器」是同时满足公开仓库与
  逐游戏精度的唯一路径。
- **安全不随状态来源改变**：无论状态来自视觉还是 provider，输出仍走反作弊拒绝、
  F12 夺回、真实后端审批与前台校验；provider 不能绕开这四道闸。

### 两个闭环的分工

| 闭环 | 频率 | 输入 | 用途 |
|:--|:--|:--|:--|
| `game_plan` | ~20 Hz | 单方向 + 帧差（撞墙侧移） | 目标级导航/走位，模型给一次目标 |
| `game_policy` | 60 Hz | WorldState 廉价实体 + profile | 战斗反射（射击 / 前进 / 闪避 / 脱困） |

两者都是本地线程、逐拍安全复检、stop 立即松手；模型只在起停时出现。
`game_state` 负责低频「看一眼」，不参与逐拍决策。

### 安全含义

- **状态层只读**：WorldState 全部来自抓屏 + OCR；v1 不读内存、不注入进程。
- **档案边界**：被跟踪的 profile 只有通用键位/HUD/阈值；内存偏移/攻略数据若将来加入，
  只能放用户本地档案，且默认关闭、显式启用、不绕过安全闸。
- **公开边界**：仓库不出现游戏内存地址、CT 表、私服/破解文件或本机路径。
- **验证边界**：通用基线目前只经单测与 dry-run 集成验证；真实对局与逐游戏参数标定
  仍未完成，文档不得把它写成「已校准」。

## 3. 图片：走宿主 attachment，不搬 base64

`ToolOutputDefinition.render(args, value)` 返回 `ContentBlock[]`；图片块是
`{ type: 'image', attachment: ImageAttachmentRef }`，引用由 `ctx.attachments.saveImage()`
落盘。会话文本里只留尺寸与来源，字节不进历史。M0 已用合成帧验证这条链路。

## 3.5 抓屏：默认整屏 grab + 窗口矩形裁剪；可选 PrintWindow 窗口级抓屏

> 2026-11-09 起，`window_capture.py` 提供 `PrintWindow(PW_RENDERFULLCONTENT)` 窗口级抓屏，
> 用 `DSH_GAME_BRIDGE_CAPTURE=window` 开启。默认仍是下面的整屏裁剪，因为 PrintWindow 对部分
> 硬件加速窗口会返回黑帧（需要检查帧方差）。被遮挡的窗口（例如 DSH 窗口盖住 Cuphead）实测用
> window 模式能截到。WGC（Windows Graphics Capture）没有实现。

> 本节于 2026-10-30 修正：旧标题「窗口级抓屏（不是整屏）」与实现不符——实现一直是
> 整屏 grab 再按窗口矩形裁剪，反例见 `docs/FIELD-2026-10-29.md` P1-2。

`game_attach` 接受窗口标题子串，用只读 Win32 API（EnumWindows / GetWindowText /
DwmGetWindowAttribute）解析出窗口矩形；之后每次 `snapshot` 重新读一次矩形，
从 DXcam 抓到的**整块显示器画面**里裁出这一块。窗口移动/缩放不会拍偏，
但**别的窗口盖住游戏时，裁出来的就是遮盖物**——引擎不会魔法般只拿回游戏像素。
找不到窗口时返回 `WINDOW_NOT_FOUND` 并列出当前可见标题——比「随便截个整屏让模型猜」
有用得多。

实测（本机，无遮挡）：attach 到 1280×800 的窗口后，帧尺寸与裁剪区完全一致
（`region {left:239, top:203, width:1280, height:800}`，OCR 读出 32–54 行界面文字）。
2026-10-29 实机则拍到反例：attach 在 Cuphead 上、snapshot 却返回覆盖其上的 DSH
聊天窗口（`docs/FIELD-2026-10-29.md` P1-2）。

**低成本可观测性（已实现）**：短期不换抓屏，但把「拍错人」从静默变成显式信号：

- `foreground_window()`：前台窗口的 `hwnd / title / process / 矩形`；
- `window_occlusion(hwnd)`：只统计 z-order 在目标之上的可见顶层窗口，按交叠面积
  给出 `occluded_ratio`（0–1；`>= 0.5` 记为 `occluded`）与 `covered_by`（前 3 个）；
- `game_snapshot` 返回 `foreground` / `occluded`，渲染追加 `Foreground: ...`，
  遮挡或不在前台时打 `⚠`（带比例）；
- `game_attach` / `game_act` / `game_plan` / `game_status` 也带 `foreground`，
  `game_act` 另带 `delivery`。

**窗口级抓屏**：`PrintWindow` 已作为可选模式实现（见本节开头）；WGC 未实现。
两者都可能对部分游戏 / 受保护内容返回黑帧，需要逐个游戏实机验证。

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

1. **随时可夺回**：F12 本地夺回闩锁，不经模型、不经会话；
2. **反作弊不接**：命中 EAC/BattlEye/Vanguard 等进程即拒绝一切输出通道；
3. **默认只读**：只做抓屏和模拟输入（键盘 / 鼠标 / 手柄），不读内存、不注入进程；
4. **真实后端需批准**：`DSH_GAME_BRIDGE_CONTROL` 不是 dry-run 时，插件注册
   `tools/pre-execute` 钩子，对 `game_attach` 返回 `{kind:'ask'}`，走 DSH
   user-approval 的一次性批准；headless/CI 没有应答者时 fail-closed 拒绝。
   dry-run 下不注册钩子——只记录动作的操作不值得打断用户；
5. **前台校验**：真实后端在 `game_act` 前要求 attached 窗口在前台，否则抛
   `EngineError("FOREGROUND_MISMATCH")`；`game_plan` 逐拍检查，丢前台即中止。
   它与 §3.5 的 `foreground` / `occluded` 元数据一起，挡住「成功但无效」的静默失败；
6. **可审计**：`DSH_GAME_BRIDGE_AUDIT_LOG` 打开后，`attach / act / plan_start /
   plan_end / stop` 与 `act_blocked / plan_blocked` 全部写本地 JSONL；写失败只记
   在条目里，不影响主流程。默认关闭，路径完全由用户指定；
7. **档案是数据**：仓库内 profile 只含通用字段（键位/HUD/阈值），不发布内存偏移/CT 表；
   用户本地档案属于用户数据。memory/API provider 默认关闭且当前未实现，将来接入也
   必须先过上面 1–6 道闸。

**明确不做**：「无人不自娱」（无键鼠输入即停手）已于 2026-10-30 移除，理由见 §2.5；
无人值守是否使用由用户决定。

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



## 9. 待定：游戏数据与记忆的收敛

> 状态：**方案，尚未决定**。在这里定下来之前，不要新增「每款游戏的数据格式」或记忆层代码。
> 背景见 [STATUS § 能力层与代码去向](STATUS.md#能力层与代码去向)。

### 9.1 现状：同一款游戏的数据有 4 种格式，目录有两套

| 格式 | 位置 | 谁读 | 谁写 |
|:--|:--|:--|:--|
| GameProfile | 用户档案目录 `<cache-root>/profiles/`（`DSH_GAME_BRIDGE_PROFILE_DIR`）；仓库里的 `profiles/*.json` 是样例 | `state.py`、`policy.py`、`game_attach profile=` | `game_memory save` |
| GamePack | `experiments/games/packs/*.json` | `gamepack.validate_pack`；`game_attach pack=` 经 `profile_from_pack` 转成 profile | `probe.py` / `onboarding.py` 生成草稿，或手写 |
| 记忆目录的 `game.json` / `ui.json` / `entities.json` / `general.json` / `user/preferences.json` | `<data-root>/memory/`（`DSH_GAME_BRIDGE_MEMORY_DIR`） | `memory_loader.load_game` | **没有任何代码写**（只有 `levels/*.json` 由 level memory 写） |
| 冷启动 profile | 无固定位置 | `coldstart.py` 合并，`instant_play.py` 转成引擎 profile | 没有生产调用 |

另外，认键位有两代实现（见 [AI-NATIVE-PLAN](AI-NATIVE-PLAN.md) 顶部说明）。

### 9.2 建议方案（待你确认）

**每个游戏一个目录，只有三种内容**：

```text
<data-root>/games/<game_id>/
  profile.json    运行时配置：键位、HUD 区域、场景关键词（就是现有 GameProfile，唯一被引擎读取的格式）
  notes.md        模型写给自己的文字笔记（M2 游戏级记忆 + 攻略事实，每条带来源和日期）
  runs/           每局的记录与时间线（recorder 的输出、M5 的结果行）
```

- **GameProfile 是唯一的运行时格式**：它已经有工具（`game_memory`）、存储（`profile-store.js`）、校验和 `game_attach profile=`。
- **GamePack 退为导入格式**：保留合同和校验（反作弊 fail-closed 必须留着），`game_attach pack=` 继续通过现有适配器转成 profile，
  不再作为独立的数据层。
- **笔记用 Markdown，不用结构化 JSON**：读写者是模型，文字最省事。来源 / 日期 / 置信度（M4 元记忆）写成每条笔记的行内标注，
  不单独建一套 manifest。
- **记忆目录的 `game.json` / `ui.json` / `entities.json` / `general.json` / `preferences.json` 废弃**：没人写，也没内容。
  `memory_loader` 的作用域加载思想保留在 `notes.md` 的分节里，代码不保留。
- **认键位**：第二代（`probe.py` + `onboarding.py`）保留，产物写进 `profile.json`；第一代整条链删除。
- 目录统一成一个数据根，`DSH_GAME_BRIDGE_PROFILE_DIR` 和 `DSH_GAME_BRIDGE_MEMORY_DIR` 合并或互相兼容（兼容方式待定）。

### 9.3 要你定的事

1. **GameProfile 还是 GamePack 做唯一格式？** 我倾向 GameProfile，理由见上；代价是 GamePack 的 `capabilities` / `recipes`
   字段在 profile 里没有对应位置，需要决定是丢掉还是并入。
2. **笔记用 Markdown 还是 JSON？** 我倾向 Markdown。
3. ~~第一代冷启动链要不要现在就删？~~ **已决定（2026-11-12）：M5 之后再评估，现在不删。** 理由：这批代码不影响 M5。
   不要整条删，按模块区分（供将来参考）：
   - 可删：`controls_probe`（与 `probe.py` 重复）、`effect_classifier`（偏动作游戏，`probe.py` 有等价的 `summarize_effects`）、
     `instant_play`（服务已冻结的 60 Hz 策略）；
   - 有第二代没有的能力，要评估后再决定：`game_probe`（读游戏配置文件里的键位）、`coldstart.merge_controls`（多来源合并加置信度）、
     `priors` 里回合制 / 菜单为主两类。

### 9.4 落地顺序

1. 9.3 的第 1、2 条已按建议定下（GameProfile 做唯一运行时格式，笔记用 Markdown），第 3 条推迟到 M5 之后；
2. 据此修订 [MEMORY](MEMORY.md)（重写 M2–M5 的落点，删掉已作废的目录结构）；
3. 在 `game_memory` 里加笔记读写（M5 之后，等数据说明需要）；
4. 最后才删代码：记忆目录的读取代码、动作游戏专用的记忆；第一代冷启动链按 9.3 第 3 条等 M5 之后。

# dsh-game-bridge

**让 DeepSeek Harness 的模型能看见并操作慢节奏游戏。**

[English](README.en.md) · [现状](docs/STATUS.md) · [玩法协议](docs/PLAY.md) · [设计](docs/DESIGN.md) · [控制表](docs/CONTROLS.md)

> 状态：**0.0.1 已发布**（npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`），0.0.2 尚未发布。
> 仅支持 Windows。**默认 dry-run**：只记录动作，不碰设备。
> 当前里程碑：模型通过本插件自己玩完一局 2048，并且得分超过随机按键的对照组（见 [STATUS](docs/STATUS.md)）。

## 这是什么

DSH 有模型、工具和会话，但看不见屏幕上的游戏，也按不了键。这个插件补上这两块：

- **看**：抓屏（DXcam，也可以用窗口级 PrintWindow）、OCR（RapidOCR）、帧差事件；
- **按**：键盘（SendInput）、鼠标点击、虚拟 Xbox 手柄（ViGEmBus）；
- **安全**：反作弊游戏一律拒绝、F12 随时夺回、真实输入需要 DSH 审批、只对前台窗口生效、可选审计日志。

**由模型决定怎么玩**：看截图，读 OCR 文本，选一个动作，再看结果。

## 适合玩什么

模型一次决策要 5–10 秒，所以本插件**只针对慢节奏游戏**：

| 适合 | 不适合 |
|:--|:--|
| 2048、扫雷、数独、纸牌、棋类 | 动作、平台跳跃、弹幕 |
| 视觉小说、模拟经营、放置类 | 竞速、FPS、格斗 |
| 回合制策略 / RPG、菜单操作 | 任何需要秒级以下反应的玩法 |

实时动作游戏不在本项目范围内，原因见 [STATUS](docs/STATUS.md)。

## 工具

| 工具 | 用途 |
|:--|:--|
| `game_selftest` | 插件装没装上、引擎和后端是否就绪 |
| `game_windows` | 列出可见窗口 |
| `game_attach` | 绑定游戏窗口（真实后端需要审批） |
| `game_snapshot` | 看一眼：截图 + OCR 文本 + 前台/遮挡信息 |
| `game_events` | 低成本的帧差事件（静止 / 变化 / 切场景） |
| `game_controls` | 当前后端接受的按键名 |
| `game_act` | 按一个键 / 手柄按钮，或点一下鼠标 |
| `game_plan` | 有时长上限的本地按键循环（按住 / 连按 / 撞墙侧移） |
| `game_status` | 绑定状态、安全判定、循环进度、审计记录尾部 |
| `game_stop` | 停止一切、松开按键、解绑 |
| `game_state` | 可选：通用视觉状态 WorldState（[STATE](docs/STATE.md)） |
| `game_memory` | 可选：本地游戏档案（profile）的增删改查，**不读游戏内存** |
| `game_policy` / `game_intent` | **已冻结**：实时动作路线留下的 60 Hz 本地策略，不再开发 |

典型一局：`game_selftest` → `game_windows` → `game_attach` → 循环执行 `game_snapshot` → `game_act` → `game_stop`。

## 安装

DSH 的每个 profile 是独立的插件树，装错了 profile，新会话里就看不到 `game_*` 工具。

| 宿主 | 怎么装 | profile |
|:--|:--|:--|
| 桌面版（Electron） | 应用内 **设置 → 插件** | `desktop`（CLI 管不了） |
| `dsh web` | `dsh plugin --profile web add dsh-game-bridge` | `web` |
| `dsh headless` | `dsh plugin --profile headless add dsh-game-bridge` | `headless` |

其他安装来源：`file:<repo>`（本地开发）、`github:nobu2333/dsh-game-bridge`。

- 要求：DSH `>= 0.2.1-rc.2 < 0.3.0`，Node `>= 22`，**机器上有 `uv`**；
- **装完必须重启宿主**，然后调用一次 `game_selftest` 确认；
- 首次激活时，插件会用 `uv` 在用户缓存目录建 venv 并安装引擎（约 20 秒）。引擎就绪之前只注册自检工具；
- 包里没有 install / postinstall 脚本。

## 配置（环境变量，宿主启动时读取，改完要重启宿主）

| 变量 | 取值 |
|:--|:--|
| `DSH_GAME_BRIDGE_CONTROL` | `dry-run`（默认）/ `keyboard`（SendInput 键鼠）/ `vgamepad`（Xbox 手柄，需要 ViGEmBus） |
| `DSH_GAME_BRIDGE_CAPTURE` | `screen`（默认，整屏抓取后按窗口裁剪）/ `window`（PrintWindow，窗口被遮挡也能截到） |
| `DSH_GAME_BRIDGE_AUDIT_LOG` | 审计 JSONL 的路径；不设就不记录 |
| `DSH_GAME_BRIDGE_PROFILE_DIR` | 本地档案目录 |

```powershell
# CLI：在当前终端设好再启动
$env:DSH_GAME_BRIDGE_CONTROL='keyboard'; dsh web
# 桌面版：写用户级环境变量，然后完全退出再重开应用
setx DSH_GAME_BRIDGE_CONTROL keyboard
```

**审批**：真实后端（`keyboard` / `vgamepad`）在 `game_attach` 时需要 DSH 一次性批准。
权限预设为 `approval: never` 的部署，以及没有审批应答者的 headless / CI，都会直接拒绝。
这是有意的 fail-closed：要么把预设改成 `ask`，要么继续用 dry-run。

## 安全承诺

1. **随时可夺回**：按 F12 立即锁住输出，不经过模型；重新 attach 才解除；
2. **反作弊不接**：检测到 EAC / BattlEye / Vanguard / ACE 等进程，一律拒绝输出；
3. **不读内存、不注入进程**：只抓屏和模拟输入；
4. **真实输入需要批准**，并且只发给前台窗口（不在前台就拒绝，返回 `FOREGROUND_MISMATCH`）；
5. **可审计**：打开审计日志后，每次 attach / act / plan / stop 以及每次被拒绝的尝试都会写入本地 JSONL。

## 开发与验证

```powershell
npm test                                   # 插件契约测试
cd engine; python -m pytest tests -q       # 引擎单测
cd ..
$env:DSH_HOME='<repo>/.dsh-test'           # 隔离的 DSH 环境
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # 全量集成（假模型，不联网）
```

当前测试数字和最近一次实测时间见 [STATUS](docs/STATUS.md)，发布流程见 [RELEASE](docs/RELEASE.md)。

## 已知限制

见 [STATUS § 已知限制](docs/STATUS.md#已知限制)。

## 许可

MIT。

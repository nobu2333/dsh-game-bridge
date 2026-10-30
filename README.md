# dsh-game-bridge

**给 DeepSeek Harness 装上眼睛和手：让 DSH 看得懂游戏、也能替你玩。**

[English](README.en.md) · [现状与交班](docs/STATUS.md)

> 状态：**0.0.1 已发布**（npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`）；
> **0.0.2 已本地打包并安装验证（未发布）**：引擎自举、桌面 profile 安装、真实抓屏/OCR、前台/遮挡诊断。
> 已实测：从 registry 的 tarball 安装 → 引擎自举（PyPI）→ 真实抓屏/OCR → 20 Hz 闭环。
> **默认 dry-run 后端（只记录、不碰设备）**；真实注入已实机验证（2026-10-29：手柄 A + XInput 回读、键盘 W + `AsyncKeyState` 回读）；仅 Windows。

## 这是什么

DSH 有大脑（模型、工具、会话），但没有「眼睛和手」：它能读文件、跑命令、看网页，
却看不见你正在玩的游戏，也按不了手柄。

dsh-game-bridge 把一块薄薄的插件壳装进 DSH，背后接一个本地引擎：

- **眼睛**：抓屏（DXcam）、帧差分、OCR 语义层、20 Hz 实体/弹幕追踪；
- **手**：虚拟手柄（XInput）、虚拟键鼠、窗口焦点与输入法看护；
- **小脑**：本地 20 Hz 闭环（导航、避障、走位、弹反），模型只给目标，不逐步按键；
- **安全**：夺回热键、反作弊游戏硬拒绝；真实后端需 DSH 审批。

## 为什么是「目标级工具」而不是「每步调一次工具」

模型一次工具调用要 3~5 秒。如果让模型逐步决定「往右走一步」，游戏里它就是个植物人。
所以工具面只暴露**目标级**接口（绑定窗口、看一眼、跑一个目标的循环、停下来），
即时反应由本地循环完成。这条约束来自被实测反复验证的延迟事实，不是口味问题。

## 安装（三种宿主，各有各的 profile）

DSH 的 profile 是**互相独立的插件树**：装错 profile，新会话里就永远看不到 `game_*` 工具。
先确认要装在哪一种宿主上：

| 宿主 | 怎么装 | profile | 说明 |
|:--|:--|:--|:--|
| 桌面版（Electron App） | 应用内 **设置 → 插件** 安装 | `desktop`（应用写死） | **CLI 管不了**：`dsh plugin --profile desktop ...` 会报 `profile "desktop" is managed exclusively by the Electron application` |
| `dsh web` | `dsh plugin --profile web add dsh-game-bridge` | `web` | 与桌面版不共享插件 |
| `dsh headless` | `dsh plugin --profile headless add dsh-game-bridge` | `headless` | CI / 无界面场景 |

**装完必须重启宿主**：插件在宿主启动时加载。桌面版退出应用再打开，`dsh web` /
`dsh headless` 重启对应进程；重启后先调一次 `game_selftest` 确认装对了
（见下文「`game_selftest` 现在报什么」）。

安装来源（下面命令用于 `web` / `headless` 这类 CLI profile；桌面版在应用内插件面板里选择来源）：

```powershell
# registry（发布后的推荐路径）
dsh plugin --profile web add dsh-game-bridge

# 本地目录 / tarball（开发或离线）
dsh plugin --profile web add file:<repo>

# GitHub（仓库已 public）
dsh plugin --profile web add github:nobu2333/dsh-game-bridge
```

- 要求：DSH `>= 0.2.1-rc.2 < 0.3.0`；Node `>= 22`。
- 首次激活会自举本地引擎：用 `uv` 建 venv 并安装引擎 wheel，缓存到用户目录；
  **引擎落地前，插件只注册自检工具**，不会假装能玩；机器上需要有 `uv`。
- 平台：**v1 仅 Windows 10/11**（抓屏、虚拟手柄、输入注入都是 Win32）。
- 不需要第二个安装步骤，也不需要手动放行构建脚本（包里没有 install/postinstall）。
- 部署方的安装面板里填包名 `dsh-game-bridge` 即可。

## 切换后端（`DSH_GAME_BRIDGE_CONTROL`）

| 值 | 行为 |
|:--|:--|
| 不设 / `dry-run`（默认） | 只记录动作，不碰设备；可抓屏、OCR、跑闭环演示 |
| `vgamepad` | 创建虚拟 Xbox 手柄注入 XInput（需要 ViGEmBus 驱动） |
| `keyboard` | 用 SendInput 注入键盘按键 |

后端在**宿主启动时**读取（插件模块加载一次、引擎进程启动时再读一次），
**会话中途改环境变量不生效**。切换步骤：

1. 设置环境变量；
2. 完全退出宿主（桌面版退出应用；CLI 结束进程）；
3. 重新启动宿主，再用 `game_selftest` 确认 `backend.name` 和 `backend.ready`。

```powershell
# CLI（dsh web / dsh headless）：在当前终端设好再启动
$env:DSH_GAME_BRIDGE_CONTROL='vgamepad'
dsh web

# 桌面版：写用户级环境变量，然后从开始菜单重启应用（setx 只影响新进程）
setx DSH_GAME_BRIDGE_CONTROL vgamepad
```

`vgamepad` 需要 ViGEmBus 驱动，且引擎 venv 里要有 `vgamepad`：发布版 bootstrap 会按
所选后端自动带上 `[gamepad]` extra；若引擎缓存 venv 没有 pip，用
`uv pip install --python <venv>\Scripts\python.exe vgamepad` 补装。
XInput 槽位（= 玩家序号）会写进 `game_attach` / `game_status` / `game_selftest` 的输出。

## 审批策略：真实后端为什么会被自动拒绝

真实后端（`vgamepad` / `keyboard`）的 `game_attach` 需要 **DSH 一次性审批**。
如果部署的权限预设是 `approval: never`（例如 `danger-full-access`），DSH 对
「需要审批」的动作**一律自动拒绝**——`game_attach` 直接失败，而不是弹窗。

两条可行路径：

1. 把权限预设切换成会询问的（`ask`），或让部署方提供审批应答者 → attach 时点一次批准；
2. 保持 `dry-run` 后端：抓屏 / OCR / 闭环演示都不需要审批。

headless / CI 没有审批应答者，行为同样是 fail-closed（预期）。

## `game_selftest` 现在报什么

重启后先跑一次自检，它同时回答「装对了没有」和「后端能不能用」：

| 字段 | 含义 |
|:--|:--|
| 文本摘要 | 插件版本 / 平台 / 引擎状态；引擎 ping 成功时文本里出现 `answered` |
| `install` | 安装信息：`package_dir`、`profile`、`profile_dir`、`dependency`、`source`（`registry` / `local-file` / `link` / `github` / `unknown`）、`warnings` |
| `backend` | 所选后端就绪度：`name`、`ready`、`detail`、`xinput_slot`、`warnings` |
| `report` | 引擎原始自检：依赖版本、显示器、OCR、前台窗口（`foreground`）、XInput 已连接槽位等 |

- `source=local-file` 且依赖路径位于临时目录（`/tmp/`、`\tmp\`、`/temp/`、`\temp\`）时会告警：
  临时产物被清理后，宿主下次启动就加载不了插件——正式使用请换 registry / github 来源；
- `backend.name=vgamepad` 时会实际创建一次虚拟手柄再关闭（**不按键**），报告能否创建、
  落在哪个 XInput 槽位；槽位不是 0（= 玩家 2）会尝试重建并给出 `warnings`；
- 引擎 / 后端没就绪时，工具会如实说明，不会假装能玩。

## 开发

```bash
# 本地以 file: 依赖装进一个 profile（不碰 npm 上的正式版本）
dsh plugin --profile web add file:<repo>

# 卸载
dsh plugin --profile web remove dsh-game-bridge
```

### 验证

```bash
# 1) 契约测试：用宿主里那份真实的 @deepseek-ai/dsh-tools 校验 defineTool / 图片块
npm test

# 2) 会话级集成测试：隔离 DSH_HOME + 假模型，不联网、不碰真实屏幕与键鼠
$env:DSH_HOME='<repo>/.dsh-test'
dsh --profile headless --dump-config          # 初始化隔离 profile
dsh plugin --profile headless add file:<repo> # 官方安装方式（会顺手选中 bundle）
npm run test:session
```

`test:session` 会起一个本地假模型服务器，让模型调用 `game_snapshot`，再从
**harness 实际发出的请求体**里断言：工具确实出现在 `tools` 数组里、工具结果确实
回来了、图片确实以 `data:image/png` 送到了模型。产物落在 `test/integration/.out/`。

**全量回归**（一次跑完 M0/M1/M2/M3/events/windows/controls/审批/崩溃自愈/bootstrap 十条）：

```powershell
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'   # 不设则跳过需要真实引擎的五条
npm run test:all
```

最近一次实测：10/10 PASS，约 110 秒（含真实抓屏、OCR、闭环、窗口列表、控制表、审批 fail-closed、引擎崩溃自愈、自举安装）。

验证自举安装（不需要系统 Python：uv 建 venv，装仓库内的假引擎包，秒级）：

```powershell
$env:DSH_GAME_BRIDGE_ENGINE_SPEC='<repo>/test/fixtures/fake-engine'
$env:DSH_GAME_BRIDGE_CACHE_DIR='<repo>/tmp/engine-cache'
$env:FAKE_TOOL='game_selftest'
npm run test:session        # 断言：引擎被装上、spawn 起来、ping 有应答
```

**真实引擎自举**（已实测）：用本地构建的 wheel 走 uv 安装，依赖经阿里云镜像下载
17 个包、约 **20 秒**；之后插件直接用缓存里的 Python 起引擎，`ping`/`selftest`
报告 numpy / cv2 / dxcam / rapidocr 就绪、显示器 1920×1200、OCR 预热通过。
再跑一次「只有缓存、不设任何 Python 环境变量」的集成：

```powershell
$env:DSH_GAME_BRIDGE_CACHE_DIR='<repo>/tmp/engine-cache-real'
$env:FAKE_TOOL='game_snapshot'
npm run test:session        # M1 PASS：真实屏幕帧 + OCR 进模型
```

接真实引擎（开发期形态：直接指向一个装好依赖的 Python，跳过自举）：

```powershell
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-numpy-dxcam-rapidocr>'
$env:DSH_GAME_BRIDGE_ENGINE_DIR='<repo>/engine'    # `-m dsh_game_core` 的 cwd
$env:FAKE_TOOL='game_snapshot'
npm run test:session        # 额外断言：帧来自真实屏幕、OCR 文本随帧进入模型
```

引擎自检（不联网、不注入输入）：

```powershell
cd engine
python -m dsh_game_core selftest --capture   # 依赖 / 显示器 / OCR / 前台窗口 / 后端报告 / 抓一帧的真实耗时
# 加 --probe-devices 会按当前后端试建一次（vgamepad 会临时创建并关闭虚拟手柄，不按任何键）
```

### 引擎自举与缓存（发布形态）

插件装载时会在后台准备引擎，状态机 `idle → installing → ready | failed`；
工具调用最多等一小段时间，没等到就用合成帧并写明原因。

- 缓存目录：Windows `%LOCALAPPDATA%\dsh-game-bridge\engine\<version>`，
  macOS `~/Library/Caches/...`，Linux `~/.cache/...`；
- 安装方式：`uv venv` + `uv pip install dsh-game-core==<version>`（uv 自带 Python，
  用户无需预装 Python；但**需要机器上有 uv**，缺失时工具结果里会给出安装命令）；
- 调试覆盖：`DSH_GAME_BRIDGE_PYTHON` / `DSH_GAME_BRIDGE_ENGINE_DIR` 指向现成环境，
  `DSH_GAME_BRIDGE_PYTHON=off` 强制走合成帧，`DSH_GAME_BRIDGE_CACHE_DIR` 换缓存位置；
- 输出后端：`DSH_GAME_BRIDGE_CONTROL=dry-run`（默认，只记录）/ `vgamepad`（Xbox 手柄）/
  `keyboard`（SendInput 键盘，按键名 W/A/S/D/SPACE/ENTER/ESC/ARROWS…）；
  非 dry-run 时 attach 需要 DSH 一次性审批；后端在宿主启动时确定，切换方式见上文「切换后端」；
  真实后端在 attached 窗口不在前台时会拒绝动作；
- 审计：设置 `DSH_GAME_BRIDGE_AUDIT_LOG=<path>` 后，attach/act/plan/stop/拦截
  都会写本地 JSONL（默认关闭；`game_status` 的 `audit` 字段带最近 5 条）。

## 路线图

| 里程碑 | 内容 | 验收 |
|:--|:--|:--|
| M0 ✅ | 插件壳 + 合成帧工具 | 工具出现在列表；图片进上下文；进程干净退出 |
| M1 ✅ | 真实抓屏/OCR + 引擎自举 | 隔离 harness 里拿到真实屏幕帧 + OCR 文本；uv 自举可跑 |
| M2 ✅ | 安全闸 + 输出通道 + 单步 act | 两道安全闸单测钉死；attach → act 端到端通过；真实后端需审批 |
| M3 ✅（dry-run 已验证） | 20 Hz 本地闭环 | 闭环 ~20 Hz、逐拍安全复检、stop 立即松手 |
| 发布 ✅ | npm + PyPI + 插件市场 | 0.0.1 已发布，发布产物安装/M1/M3 实测通过；市场收录待提交 |

## 已知限制（v1）

- **仅 Windows**：抓屏/虚拟手柄/输入注入都是 Win32；非 Windows 在自举阶段直接拒绝。
- **多显示器基本支持**：用 Win32 显示器枚举 + 分辨率/主屏标记把窗口映射到对应
  DXcam output，裁剪区按显示器原点换算。已知边界：两块**同分辨率且都不是主屏**时
  无法从 dxcam 信息里区分，会按序号确定性选择（可能选错）；单屏/常规双屏实测通过。
- **抓屏是「整屏 grab + 窗口矩形裁剪」，不是真正的窗口级抓屏**：DXcam 抓的是整块显示器，
  再按窗口矩形裁剪。别的窗口盖住游戏时，`game_snapshot` 画面里就是遮盖物——它会带
  `foreground` / `occluded` 元数据并显著标注，但画面本身无法绕过遮挡。真正的窗口抓屏
  （`PrintWindow(PW_RENDERFULLCONTENT)` / Windows Graphics Capture）是后续工作。
- **真实后端只对前台窗口生效**：attached 窗口不在前台时，`game_act` 直接拒绝
  （`FOREGROUND_MISMATCH`），`game_plan` 在丢前台时中止——不再静默「成功但无效」。
- **XInput 槽位只报告、不保证**：虚拟手柄可能落到 slot 1+（= 玩家 2）；插件会尝试重建
  最多 2 次并给出 warning，但不敢保证每个游戏都接受非 0 槽位。
- **`approval: never` 的部署用不了真实后端**：attach 会被自动拒绝，见上文「审批策略」。
- **真实注入已验证、但长闭环未在真实游戏里跑**：手柄与键盘后端都通过了设备回读，
  但还没有「连续 20 Hz 操作真实游戏」的实机录像；默认仍是 dry-run。
- **新的前台/遮挡元数据与拒绝逻辑**已通过单元/集成测试，但**尚未在真实游戏里复验**
  （实机证据是修复前的行为，见 `docs/FIELD-2026-10-29.md`）。
- **游戏内语义未校准**：帧差分阈值、OCR 区域都还是通用值，没有按具体游戏调过。

## 安全承诺（发布版必须成立）

1. **随时可夺回**：本地 F12 热键即闩锁夺回，不经过模型、不经过会话；
2. **反作弊不接**：EAC / BattlEye / Vanguard 等游戏一律拒绝输出通道；
3. **默认只读**：发布版默认只做抓屏 + 手柄，不读内存、不注入进程；
4. **真实后端需批准**：`DSH_GAME_BRIDGE_CONTROL` 不是 dry-run（`vgamepad` / `keyboard`）时，`game_attach`
   会走 DSH 的 user-approval 一次性批准；没有批准应答者的部署（headless/CI）
   fail-closed 拒绝；
5. **前台校验**：真实后端在 `game_act` / `game_plan` 前校验 attached 窗口是否在前台，
   不在前台直接拒绝（`FOREGROUND_MISMATCH`），不制造「成功但无效」的动作；
6. **可审计**：打开 `DSH_GAME_BRIDGE_AUDIT_LOG` 后，每一次 attach/act/plan/stop
   与每一次被拒绝的尝试都落本地 JSONL，可自证。

> 「无人不自娱」（无键鼠输入即停手）这条闸继承自宿主项目，对 dsh-game-bridge
> 不适用（误杀手柄玩家、又会被注入输入自我遮蔽），已于 2026-10-30 移除。
> 无人值守是预期用法；真实后端仍受 DSH 审批与 F12 夺回约束。

## 许可

MIT。游戏内的策略/档案数据将来单独许可，见 `LICENSE`。




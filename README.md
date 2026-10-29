# dsh-game-bridge

**给 DeepSeek Harness 装上眼睛和手：让 DSH 看得懂游戏、也能替你玩。**

[English](README.en.md) · [现状与交班](docs/STATUS.md)

> 状态：**已发布 0.0.1**（npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`）。
> 已实测：从 registry 的 tarball 安装 → 引擎自举（PyPI）→ 真实抓屏/OCR → 20 Hz 闭环。
> **默认 dry-run 后端（只记录、不碰设备）**；真实注入（vgamepad 手柄 / keyboard 键鼠）尚未实机验证；仅 Windows。

## 这是什么

DSH 有大脑（模型、工具、会话），但没有「眼睛和手」：它能读文件、跑命令、看网页，
却看不见你正在玩的游戏，也按不了手柄。

dsh-game-bridge 把一块薄薄的插件壳装进 DSH，背后接一个本地引擎：

- **眼睛**：抓屏（DXcam）、帧差分、OCR 语义层、20 Hz 实体/弹幕追踪；
- **手**：虚拟手柄（XInput）、虚拟键鼠、窗口焦点与输入法看护；
- **小脑**：本地 20 Hz 闭环（导航、避障、走位、弹反），模型只给目标，不逐步按键；
- **安全**：夺回热键、无人不自娱、反作弊游戏硬拒绝。

## 为什么是「目标级工具」而不是「每步调一次工具」

模型一次工具调用要 3~5 秒。如果让模型逐步决定「往右走一步」，游戏里它就是个植物人。
所以工具面只暴露**目标级**接口（绑定窗口、看一眼、跑一个目标的循环、停下来），
即时反应由本地循环完成。这条约束来自被实测反复验证的延迟事实，不是口味问题。

## 安装（发布后）

```bash
dsh plugin --profile web add dsh-game-bridge
```

部署方的安装面板里填包名 `dsh-game-bridge` 即可；不需要第二个安装步骤，
也不需要手动放行构建脚本。

- 要求：DSH `>= 0.2.1-rc.2 < 0.3.0`；Node `>= 22`。
- 首次激活会自举本地引擎（下载 uv + 引擎 wheel，缓存到用户目录）；
  **引擎落地前，插件只注册自检工具**，不会假装能玩。
- 平台：**v1 仅 Windows 10/11**（抓屏、虚拟手柄、输入注入都是 Win32）。

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
python -m dsh_game_core selftest --capture   # 依赖 / 显示器 / OCR 预热 / 抓一帧的真实耗时
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
  非 dry-run 时 attach 需要 DSH 一次性审批；
- 安全阈值：`DSH_GAME_BRIDGE_UNATTENDED_S`（默认 180 秒无输入即拒绝输出）；
- 审计：设置 `DSH_GAME_BRIDGE_AUDIT_LOG=<path>` 后，attach/act/plan/stop/拦截
  都会写本地 JSONL（默认关闭；`game_status` 的 `audit` 字段带最近 5 条）。

## 路线图

| 里程碑 | 内容 | 验收 |
|:--|:--|:--|
| M0 ✅ | 插件壳 + 合成帧工具 | 工具出现在列表；图片进上下文；进程干净退出 |
| M1 ✅ | 真实抓屏/OCR + 引擎自举 | 隔离 harness 里拿到真实屏幕帧 + OCR 文本；uv 自举可跑 |
| **M2（进行中）** | 安全闸 + 输出通道 + 单步 act | 三条安全闸单测钉死；attach → dry-run act 端到端通过 |
| **M3（进行中）** | 20 Hz 本地闭环（dry-run 已验证）；发布未做 | 闭环 ~20 Hz、逐拍安全复检、stop 立即松手 |
| 发布 | npm + PyPI + 插件市场 | 真实手柄注入实测、市场收录 |

## 已知限制（v1）

- **仅 Windows**：抓屏/虚拟手柄/输入注入都是 Win32；非 Windows 在自举阶段直接拒绝。
- **多显示器基本支持**：用 Win32 显示器枚举 + 分辨率/主屏标记把窗口映射到对应
  DXcam output，裁剪区按显示器原点换算。已知边界：两块**同分辨率且都不是主屏**时
  无法从 dxcam 信息里区分，会按序号确定性选择（可能选错）；单屏/常规双屏实测通过。
- **真实注入未实机验证**：默认 dry-run；`vgamepad`（手柄）与 `keyboard`（SendInput）两个后端都要等用户授权的实测。
- **游戏内语义未校准**：帧差分阈值、OCR 区域都还是通用值，没有按具体游戏调过。

## 安全承诺（发布版必须成立）

1. **随时可夺回**：本地热键/一动鼠标即松手，不经过模型、不经过会话；
2. **无人不自娱**：没有人类输入且没有显式授权时，停止一切输出；
3. **反作弊不接**：EAC / BattlEye / Vanguard 等游戏一律拒绝输出通道；
4. **默认只读**：发布版默认只做抓屏 + 手柄，不读内存、不注入进程；
5. **真实后端需批准**：`DSH_GAME_BRIDGE_CONTROL` 不是 dry-run（`vgamepad` / `keyboard`）时，`game_attach`
   会走 DSH 的 user-approval 一次性批准；没有批准应答者的部署（headless/CI）
   fail-closed 拒绝；
6. **可审计**：打开 `DSH_GAME_BRIDGE_AUDIT_LOG` 后，每一次 attach/act/plan/stop
   与每一次被拒绝的尝试都落本地 JSONL，可自证。

## 许可

MIT。游戏内的策略/档案数据将来单独许可，见 `LICENSE`。




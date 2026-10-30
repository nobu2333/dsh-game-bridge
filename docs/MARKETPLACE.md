# 插件市场上架材料（草稿）

> 用途：提交 DSH Marketplace / 社区目录时直接复制。发布前按真实版本更新。

## 基本信息

| 字段 | 值 |
|:--|:--|
| 包名 | `dsh-game-bridge` |
| 版本 | `0.0.1`（发布时） |
| 一句话 | 给 DSH 装上眼睛和手：看得懂屏幕上的游戏，也能用本地 20 Hz 闭环替你操作。 |
| 许可证 | MIT |
| 平台 | Windows 10/11 x64 |
| 仓库 | `https://github.com/<owner>/dsh-game-bridge`（待建） |
| 安装命令 | `dsh plugin --profile web add dsh-game-bridge` |
| 分类 | 游戏 / 计算机使用 / 自动化 |

## 长描述（中文）

dsh-game-bridge 让 DSH 具备「看游戏 + 操作游戏」的能力：抓屏与 OCR 把画面变成
模型可读的图像与文字，本地引擎以 ~20 Hz 运行闭环，模型只负责给目标（绑定窗口、
看一眼、跑一段有界动作、停下来），不逐拍按键。默认 dry-run（只记录不注入），
两道安全闸在引擎侧实现：反作弊进程硬阻断、F12 随时夺回；真实注入需 DSH 审批。

## Long description (English)

dsh-game-bridge gives DeepSeek Harness eyes and hands on games. Capture and OCR turn
the screen into images and text the model can read; a local engine runs a bounded
~20 Hz loop while the model only chooses goals. Control is dry-run by default; two
hard gates live in the engine: anti-cheat refusal and an F12 takeover latch; real
injection requires a one-shot DSH approval.

## 风险标记（如实披露）

市场会自动识别并展示以下风险，我们主动说明：

- **terminal surface**：插件会 spawn 本地 Python 引擎进程（首次激活时用 `uv` 安装到用户缓存）；
- **filesystem**：引擎写入缓存目录与可选的 JSONL 审计日志（`DSH_GAME_BRIDGE_AUDIT_LOG`）；
- **input injection**：`DSH_GAME_BRIDGE_CONTROL=vgamepad` 时会向系统注入虚拟手柄输入
  （默认 dry-run 不注入）；
- **no credentials required**：不需要 API key；模型凭据由 DSH 自身管理。

## 安全边界（必须让用户一眼看到）

1. 反作弊游戏（EAC / BattlEye / Vanguard / ACE…）一律拒绝输出通道；
2. F12 本地夺回，不经过模型；
3. 默认只读：不读内存、不注入进程；真实注入需用户显式设置环境变量并走 DSH 审批；
4. 无人值守是预期用法（「无人即停手」闸已移除）；是否让 agent 自己玩由用户决定。

## 上架前检查

- [x] `npm publish` 后，用真实产物在隔离 profile 装通（2026-10-29：registry tarball 安装 + M1/M3 PASS）；
- [x] 首次激活自举安装真实引擎（PyPI 上的 `dsh-game-core==0.0.1`）成功；
- [x] 无 install/postinstall 脚本（市场硬门槛）；
- [x] README 写明 Windows-only、dry-run 默认、需要 `uv`；
- [ ] 录一段 30 秒演示：模型看截图 → 给目标 → 本地闭环执行 → F12 停手；
- [ ] GitHub 仓库加 topic `dsh-plugin`；
- [ ] 仓库创建满 1 天（2026-10-29 创建，最早 2026-10-30 可投）。

## 提交方式（2026-10-29 核对官方 contributing.md）

目录数据在 [`awesome-dsh-plugin/awesome-dsh-plugin`](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin)，
**一个插件一个 YAML 文件，向该仓库提 PR 即完成投稿**（不要改 README，README 由脚本生成）。

新增文件 `data/plugins/nobu2333__dsh-game-bridge.yml`：

```yaml
url: https://github.com/nobu2333/dsh-game-bridge
name: nobu2333/dsh-game-bridge
category: fun
description:
  en: 'Gives DeepSeek Harness eyes and hands on games: window capture, OCR, and a local 20 Hz closed loop with dry-run defaults.'
  zh: '给 DSH 装上游戏的眼睛和手：窗口抓屏、OCR、本地 20Hz 闭环，默认只记录不注入。'
```

注意：`description.en` 里有 `: `（冒号+空格）**必须加引号**，否则 YAML 解析失败。
分类可用 `fun`（游戏/娱乐）；不确定时按 contributing.md 的类别说明选。

### 审核硬门槛（官方 checklist）

1. `package.json` 声明 **`dsh.bundle`**（我们已声明 `dsh.bundle.patch`；只有 `dsh.client` 会被拒）；
2. 仓库有真实可用的代码（不是占位/纯 README）；
3. 仓库创建满 **1 天**；
4. 仓库带 topic **`dsh-plugin`**；
5. 在干净环境里 `dsh plugin add` 能装通（审核方会实测）。

### 操作顺序

1. 仓库 About → ⚙ → 加 topic `dsh-plugin`；
2. 2026-10-30 之后 fork `awesome-dsh-plugin`，在网页里新建上面那个 YAML 文件并提 PR；
3. PR 描述里一句话说明：Windows-only、默认 dry-run、引擎首次激活自举（需要 uv）。
   审核会在沙箱里真的装一遍，这段说明能省一轮来回。

> `dshmarketplace.dev` 的目录种子来自这个 awesome 列表；先上 awesome 列表即可。

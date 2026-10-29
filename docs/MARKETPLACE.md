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
三条安全闸在引擎侧实现：反作弊进程硬阻断、无人时自动停手、F12 随时夺回。

## Long description (English)

dsh-game-bridge gives DeepSeek Harness eyes and hands on games. Capture and OCR turn
the screen into images and text the model can read; a local engine runs a bounded
~20 Hz loop while the model only chooses goals. Control is dry-run by default; three
hard gates live in the engine: anti-cheat refusal, unattended guard and an F12
takeover latch.

## 风险标记（如实披露）

市场会自动识别并展示以下风险，我们主动说明：

- **terminal surface**：插件会 spawn 本地 Python 引擎进程（首次激活时用 `uv` 安装到用户缓存）；
- **filesystem**：引擎写入缓存目录与可选的 JSONL 审计日志（`DSH_GAME_BRIDGE_AUDIT_LOG`）；
- **input injection**：`DSH_GAME_BRIDGE_CONTROL=vgamepad` 时会向系统注入虚拟手柄输入
  （默认 dry-run 不注入）；
- **no credentials required**：不需要 API key；模型凭据由 DSH 自身管理。

## 安全边界（必须让用户一眼看到）

1. 反作弊游戏（EAC / BattlEye / Vanguard / ACE…）一律拒绝输出通道；
2. 无人时不自娱：超过阈值无键鼠输入即停手；拿不到输入遥测也拒绝；
3. F12 本地夺回，不经过模型；
4. 默认只读：不读内存、不注入进程；真实注入需用户显式设置环境变量。

## 上架前检查

- [ ] `npm publish` 后，用**真实包名**在干净 profile 里 `dsh plugin add` 装通；
- [ ] 首次激活自举安装真实引擎（PyPI 上的 `dsh-game-core`）成功；
- [ ] 无 install/postinstall 脚本（市场硬门槛）；
- [ ] README 里写明 Windows-only、dry-run 默认、需要 `uv`；
- [ ] 录一段 30 秒演示：模型看截图 → 给目标 → 本地闭环执行 → F12 停手。

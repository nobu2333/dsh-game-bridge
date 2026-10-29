# 现状与交班（STATUS）

> 更新：2026-10-29（第 17 轮）。**当前工程状态以本文件 + `git log` 为准**；
> 设计理由看 `docs/DESIGN.md`，发布步骤看 `docs/RELEASE.md`。

## 一句话

`dsh-game-bridge`：给 DeepSeek Harness 装上眼睛和手的 npm 插件（MIT，Windows-only v1）。
模型只给目标（看一眼 / 绑窗口 / 跑一段有界动作 / 停），抓屏、OCR、20 Hz 闭环都在本地
Python 引擎里；默认 dry-run（只记录不注入）。

## 现在到哪了

| 里程碑 | 状态 | 关键证据 |
|:--|:--|:--|
| M0 插件壳 | ✅ | 隔离 harness 里工具出现、截图作为 image block 进模型、进程干净退出 |
| M1 引擎 + 自举 | ✅ | 真实抓屏 1280×800 + 54 行 OCR 进模型；uv 自举装 17 个包约 20 秒 |
| M2 手 + 安全闸 | ✅（dry-run） | 反作弊/无人/F12 三道闸单测钉死；attach→act 端到端；真实后端需审批 |
| M3 20 Hz 闭环 | ✅（dry-run） | 实测 21.3 Hz；逐拍安全复检；stop 一拍内松手 |
| 发布 | ✅ 2026-10-29 | npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`；发布版安装+自举+M1/M3 实测通过 |
| 市场收录 | ⏳ 待提交 | 先转 public，再按 MARKETPLACE 提交 |

工具面（10 个）：`game_selftest` · `game_snapshot` · `game_controls` · `game_windows` ·
`game_events` · `game_attach` · `game_act` · `game_plan` · `game_status` · `game_stop`。

## 一次跑完的验证

```powershell
npm test                                   # 10 passed（契约 8 + 版本/平台 2）
cd engine; python -m pytest tests -q       # 33 passed（抓屏/OCR/安全闸/闭环/审计/窗口/帧差）
cd ..
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # 9/9 PASS，约 100 秒
pwsh -File scripts/release.ps1             # 演练：构建 wheel/sdist + npm tarball 并校验
```

另外两条已实测：
- **打包产物真实安装**：`npm pack` → `dsh plugin add <tarball>` → M1/M3 集成 PASS；
- **真实引擎自举**：本地 wheel + 阿里云镜像，19.9 秒装完，缓存内 Python 直接起引擎。

## 安全边界（已实现，不是口号）

1. 反作弊进程（EAC/BattlEye/Vanguard/ACE…）→ 拒绝一切输出；
2. 超时无键鼠输入 / 拿不到输入遥测 → 拒绝（fail-closed）；
3. F12 → 闩锁拒绝，重新 attach 才解除；
4. 真实后端（`vgamepad` 手柄 / `keyboard` SendInput 键盘）→ `game_attach` 走 DSH 审批；
   无审批应答者（headless/CI）→ 拒绝（已实测报文：`requires approval, but no approval channel is available`）；
5. 默认 dry-run，不碰设备；审计日志默认关闭、路径用户指定。

## 已知限制

- Windows-only；非 Windows 自举阶段直接拒绝（可 `DSH_GAME_BRIDGE_ALLOW_UNSUPPORTED=1` 开发覆盖）；
- 多显示器基本支持（显示器枚举 + 分辨率/主屏映射；两块同分辨率非主屏仍可能选错）；
- 真实注入未实机验证（vgamepad 手柄与 keyboard 键盘两个后端都等用户授权实测）；
- 帧差阈值、OCR 区域未按具体游戏校准。

## 发布之后剩下的事

1. ~~建远程仓库~~ ✅ `github.com/nobu2333/dsh-game-bridge`（当前 private，SSH remote）；
2. ~~npm / PyPI 发布~~ ✅ 2026-10-29，两处都是 0.0.1；
3. **转 public**（Settings → Danger Zone），然后按 `docs/MARKETPLACE.md` 提交市场；
4. **真实注入测试**（手柄按 A + XInput 回读，或键盘按 W；约 3 秒、不抢焦点）——
   完成后把 vgamepad / keyboard 从「未实机验证」改成已验证；
5. 可选：把 PyPI sdist 补传（0.0.1 当前只有 wheel；下次发布脚本已会同时发 sdist），
   并把账号级 PyPI token 换成项目级。

## 已知环境问题（2026-10-29 实测）

本机 **pnpm 12.11.2 无法连接任何 npm registry**（`os error 10013`，Node/npm/uv 都正常），
所以 `dsh plugin add <npm 包名>` 在这台机器上会失败。两种绕过：

- 下载 tarball 后 `dsh plugin add file:<tarball>`（本次验收即如此，装的是 registry 上的
  0.0.1 产物）；
- 仓库转 public 后 `dsh plugin add github:nobu2333/dsh-game-bridge`。

这不是包的问题，是 pnpm 的网络栈被本机安全策略拦截；其他用户机器大概率正常。


## 关键决策（一句话版）

- **目标级工具**：模型一次调用 3–5 秒，逐拍按键会毁体验；反射留在本地闭环。
- **图片走 attachment**：不把 base64 塞进会话文本。
- **引擎独立进程**：Python 的 CV/OCR/手柄生态现成；但必须 `unref` 子进程与管道，
  否则会挂住 DSH 事件循环（实测 headless 永不退出）。
- **严格 semver**：`engines.dsh` / peer 必须匹配带预发布标签的运行时版本。
- **默认 dry-run + 真实后端审批**：最便宜的安全默认。




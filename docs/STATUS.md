# 现状与交班（STATUS）

> 更新：2026-10-30（第 18 轮，公开前收尾）。**当前工程状态以本文件 + `git log` 为准**；
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
| M2 手 + 安全闸 | ✅（含真实注入） | 两道闸单测；attach→act 端到端；真实后端需审批；手柄 A / 键盘 W 已实机回读 |
| M3 20 Hz 闭环 | ✅（dry-run 已验证） | 实测 21.3 Hz；逐拍安全复检；stop 一拍内松手；真实后端已接线 |
| 发布 | ✅ 2026-10-29 | npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`；发布版安装+自举+M1/M3 实测通过 |
| 市场收录 | ⏳ 待提交 | 仓库已 public，按 MARKETPLACE 提交 |

工具面（10 个）：`game_selftest` · `game_snapshot` · `game_controls` · `game_windows` ·
`game_events` · `game_attach` · `game_act` · `game_plan` · `game_status` · `game_stop`。

## 一次跑完的验证

```powershell
npm test                                   # 契约 + 版本 + 平台 + 本轮新增后端/安装来源单测
cd engine; python -m pytest tests -q       # 引擎单测（含本轮新增前台/遮挡/槽位用例）
cd ..
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # 全量 PASS（约 110 秒）
pwsh -File scripts/release.ps1             # 演练：构建 wheel/sdist + npm tarball 并校验
```

另外两条已实测：
- **打包产物真实安装**：`npm pack` → `dsh plugin add <tarball>` → M1/M3 集成 PASS；
- **真实引擎自举**：本地 wheel + 阿里云镜像，19.9 秒装完，缓存内 Python 直接起引擎。

## 安全边界（已实现，不是口号）

1. 反作弊进程（EAC/BattlEye/Vanguard/ACE…）→ 拒绝一切输出；
2. F12 → 闩锁拒绝，重新 attach 才解除；
3. 真实后端（`vgamepad` 手柄 / `keyboard` SendInput 键盘）→ `game_attach` 走 DSH 审批；
   无审批应答者（headless/CI）→ 拒绝（实测报文：`requires approval, but no approval channel is available`）；
   权限预设 `approval: never` 的部署同样自动拒绝；
   引擎侧 attach 预检失败 → `BACKEND_UNAVAILABLE` fail-fast（不再等到第一次 act 才炸）；
4. 真实后端动作前校验前台窗口：attached 窗口不在前台 → `FOREGROUND_MISMATCH` 拒绝；
   `game_plan` 逐拍检查，丢前台即中止；
5. 默认 dry-run，不碰设备；审计日志默认关闭、路径用户指定。

## 已知限制

- Windows-only；非 Windows 自举阶段直接拒绝（可 `DSH_GAME_BRIDGE_ALLOW_UNSUPPORTED=1` 开发覆盖）；
- 多显示器基本支持（显示器枚举 + 分辨率/主屏映射；两块同分辨率非主屏仍可能选错）；
- **抓屏是「整屏 grab + 窗口矩形裁剪」，不是真正的窗口级抓屏**：别的窗口盖住游戏时
  snapshot 拍到的是遮盖物。已用 `foreground` / `occluded` 元数据 + `⚠` 标注暴露问题；
  真窗口抓屏（`PrintWindow(PW_RENDERFULLCONTENT)` / WGC）是后续工作（见 DESIGN §3.5）；
- **前台/遮挡元数据与拒绝逻辑已通过单元/集成测试，尚未在真实游戏里复验**（实机证据
  `docs/FIELD-2026-10-29.md` 记录的是修复前行为）；
- **XInput 槽位只报告、不保证**：虚拟手柄可能落到 slot 1+（= 玩家 2）；会尝试重建
  最多 2 次并给 warning，不保证游戏接受非 0 槽位；
- 真实注入已回读通过（vgamepad / keyboard），但**长闭环尚未在真实游戏里跑**；默认仍 dry-run；
- 帧差阈值、OCR 区域未按具体游戏校准。

## 变更记录

- **2026-10-30（公开前加固）**：
  - `game_selftest` 升级为就绪报告：安装来源（`registry` / `local-file` / `link` /
    `github` / `unknown`）、profile 与依赖、所选后端就绪度（含 `xinput_slot` /
    `warnings`）、引擎原始自检；`local-file` 指向临时目录时告警；
  - 引擎自检新增 `foreground` / `backend` / `xinput_slots_connected`，且始终探测
    `vgamepad` 依赖；`vgamepad` 控制器提供 `backend_info()` / `close()`；
  - `game_snapshot` 新增 `foreground` / `occluded`（`occluded_ratio` + `covered_by`），
    attach / act / plan / status 也带前台信息，act 另带 `delivery`；真实后端在 attached
    窗口不在前台时拒绝 act（`FOREGROUND_MISMATCH`），plan 逐拍检查、丢前台即中止；
  - `vgamepad` 创建后扫描 XInput 0–3 槽位并记录；槽位非 0 会尝试重建最多 2 次并告警；
    `session.stop()` / `close()` 会释放并关闭真实控制器，避免幽灵手柄累积；
  - 文档：README 增加「桌面版 / `dsh web` / `dsh headless`」安装矩阵、后端切换必须重启、
    `approval: never` 部署的处理方式与 `game_selftest` 字段说明；DESIGN §3.5 修正为
    「整屏 grab + 窗口矩形裁剪」，并记录真窗口抓屏（PrintWindow/WGC）为后续工作；
  - 公开版：`docs/FIELD-2026-10-29.md` 与证据包入库（本机用户名/绝对路径已泛化，
    游戏来源描述改为 Cuphead（Steam 版）；结论与证据未改）；npm 包纳入
    `README.en.md` / `docs/STATUS.md` / `docs/CONTROLS.md`。
- **2026-10-30**：移除「无人不自娱」闸（`GetLastInputInfo` 超时 / 无遥测 → 拒绝）。
  原因：该规则继承自宿主项目的陪伴场景，对本项目不适用——会误杀用手柄的真人玩家，
  而且 keyboard 后端的注入会刷新时间戳、让闸自我遮蔽。无人值守是否使用由用户决定；
  真实后端仍有 DSH 审批与 F12 夺回兜底。`DSH_GAME_BRIDGE_UNATTENDED_S` 已删除，
  工具输出的 `safety.idle_seconds` 同步移除。实机报告 `docs/FIELD-2026-10-29.md`
  保留为当时实况（其 P2-3 的处置从「修信号」改为「删规则」）。

## 发布之后剩下的事

1. ~~建远程仓库~~ ✅ `github.com/nobu2333/dsh-game-bridge`（public，SSH remote）；
2. ~~npm / PyPI 发布~~ ✅ 2026-10-29，两处都是 0.0.1；
3. ~~转 public~~ ✅ 仓库已 public；按 `docs/MARKETPLACE.md` 提交市场；
4. ~~真实注入测试~~ ✅ 2026-10-29 完成（手柄 A + XInput 回读、键盘 W + AsyncKeyState 回读）——
   完成后把 vgamepad / keyboard 从「未实机验证」改成已验证；
5. 可选：把 PyPI sdist 补传（0.0.1 当前只有 wheel；下次发布脚本已会同时发 sdist），
   并把账号级 PyPI token 换成项目级；
6. 后续：真正的窗口级抓屏（`PrintWindow(PW_RENDERFULLCONTENT)` / Windows Graphics Capture）
   替代「整屏 grab + 窗口矩形裁剪」，并逐游戏实机复验新的前台/遮挡拒绝路径。

## 已知环境问题（2026-10-29 实测）

本机 **pnpm 12.11.2 无法连接任何 npm registry**（`os error 10013`，Node/npm/uv 都正常），
所以 `dsh plugin add <npm 包名>` 在这台机器上会失败。两种绕过：

- 下载 tarball 后 `dsh plugin add file:<tarball>`（本次验收即如此，装的是 registry 上的
  0.0.1 产物）；
- 仓库已 public：`dsh plugin add github:nobu2333/dsh-game-bridge`。

这不是包的问题，是 pnpm 的网络栈被本机安全策略拦截；其他用户机器大概率正常。


## 关键决策（一句话版）

- **目标级工具**：模型一次调用 3–5 秒，逐拍按键会毁体验；反射留在本地闭环。
- **图片走 attachment**：不把 base64 塞进会话文本。
- **引擎独立进程**：Python 的 CV/OCR/手柄生态现成；但必须 `unref` 子进程与管道，
  否则会挂住 DSH 事件循环（实测 headless 永不退出）。
- **严格 semver**：`engines.dsh` / peer 必须匹配带预发布标签的运行时版本。
- **默认 dry-run + 真实后端审批**：最便宜的安全默认。





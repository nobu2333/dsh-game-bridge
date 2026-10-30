# 现状与交班（STATUS）

> 更新：2026-10-30（第 20 轮，通用玩法基线：WorldState + 60 Hz 状态策略 + 本地档案层）。**当前工程状态以本文件 + `git log` 为准**；
> 设计理由看 `docs/DESIGN.md`，数据形状与降级规则看 `docs/STATE.md`，发布步骤看 `docs/RELEASE.md`。

## 一句话

`dsh-game-bridge`：给 DeepSeek Harness 装上眼睛和手的 npm 插件（MIT，Windows-only v1）。
模型只给目标（看一眼 / 绑窗口 / 跑一段有界动作 / 起停策略 / 停），抓屏、OCR、60 Hz 状态策略
都在本地 Python 引擎里；状态是「视觉保底 + 档案数据 + 可选 provider」；默认 dry-run（只记录不注入）。

## 现在到哪了

| 里程碑 | 状态 | 关键证据 |
|:--|:--|:--|
| M0 插件壳 | ✅ | 隔离 harness 里工具出现、截图作为 image block 进模型、进程干净退出 |
| M1 引擎 + 自举 | ✅ | 真实抓屏 1280×800 + 54 行 OCR 进模型；uv 自举装 17 个包约 20 秒 |
| M2 手 + 安全闸 | ✅（含真实注入） | 两道闸单测；attach→act 端到端；真实后端需审批；手柄 A / 键盘 W 已实机回读 |
| M3 20 Hz 闭环 | ✅（dry-run 已验证） | 实测 21.3 Hz；逐拍安全复检；stop 一拍内松手；真实后端已接线 |
| 发布 | ✅ 2026-10-29 | npm `dsh-game-bridge@0.0.1` + PyPI `dsh-game-core==0.0.1`；发布版安装+自举+M1/M3 实测通过 |
| 0.0.2 本地打包 | ✅ 2026-10-30 | wheel/sdist/tarball 构建校验；桌面 profile 安装 0.0.2（引擎缓存 0.0.2）；`game_selftest` 报 0.0.2；**未发布** |
| 通用玩法基线 | ✅ 单测通过（真实对局待复验） | WorldState 视觉提取 + 60 Hz `PolicyRunner` + `game_state`/`game_policy`/`game_memory` + 本地档案库 + Cuphead 样例 profile；`npm test` 44/44、`pytest engine/tests` 154/154；memory/API provider **未实现**；集成/真实对局未复验 |
| 市场收录 | ⏳ 待提交 | 仓库已 public，按 MARKETPLACE 提交 |

工具面（13 个）：`game_selftest` · `game_snapshot` · `game_controls` · `game_windows` ·
`game_events` · `game_attach` · `game_state` · `game_policy` · `game_memory` · `game_act` ·
`game_plan` · `game_status` · `game_stop`。

## 一次跑完的验证

```powershell
npm test                                   # 契约 + 版本 + 平台 + 工具/档案库渲染单测
cd engine; python -m pytest tests -q       # 引擎单测（含 state/policy/grab_raw、前台/遮挡、槽位）
cd ..
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
npm run test:all                           # 全量 PASS（约 110 秒）
pwsh -File scripts/release.ps1             # 演练：构建 wheel/sdist + npm tarball 并校验
```

另外几条已实测：
- **打包产物真实安装**：`npm pack` → `dsh plugin add <tarball>` → M1/M3 集成 PASS；
- **真实引擎自举**：本地 wheel + 阿里云镜像，19.9 秒装完，缓存内 Python 直接起引擎。
- **通用基线单测**（2026-10-30）：`npm test` 44/44、`pytest engine/tests` 154/154；
  全量集成（`test:all`）与真实对局由发布前/Leader 验收时跑。

## 安全边界（已实现，不是口号）

1. 反作弊进程（EAC/BattlEye/Vanguard/ACE…）→ 拒绝一切输出；
2. F12 → 闩锁拒绝，重新 attach 才解除；
3. 真实后端（`vgamepad` 手柄 / `keyboard` SendInput 键盘）→ `game_attach` 走 DSH 审批；
   无审批应答者（headless/CI）→ 拒绝（实测报文：`requires approval, but no approval channel is available`）；
   权限预设 `approval: never` 的部署同样自动拒绝；
   引擎侧 attach 预检失败 → `BACKEND_UNAVAILABLE` fail-fast（不再等到第一次 act 才炸）；
4. 真实后端动作前校验前台窗口：attached 窗口不在前台 → `FOREGROUND_MISMATCH` 拒绝；
   `game_plan` 逐拍检查，丢前台即中止；
5. 默认 dry-run，不碰设备；审计日志默认关闭、路径用户指定；
6. 档案边界：被跟踪 profile 只含通用字段（键位/HUD/阈值），不含内存偏移/攻略数据；
   memory/API provider 默认关闭且**未实现**，将来接入也不得绕开上面 1–5。

## 已知限制

- Windows-only；非 Windows 自举阶段直接拒绝（可 `DSH_GAME_BRIDGE_ALLOW_UNSUPPORTED=1` 开发覆盖）；
- 多显示器基本支持（显示器枚举 + 分辨率/主屏映射；两块同分辨率非主屏仍可能选错）；
- **抓屏是「整屏 grab + 窗口矩形裁剪」，不是真正的窗口级抓屏**：别的窗口盖住游戏时
  snapshot 拍到的是遮盖物。已用 `foreground` / `occluded` 元数据 + `⚠` 标注暴露问题；
  真窗口抓屏（`PrintWindow(PW_RENDERFULLCONTENT)` / WGC）是后续工作（见 DESIGN §3.5）；
- **前台/遮挡元数据与拒绝逻辑已通过单元/集成测试**；桌面实机已复核「attach Cuphead 但被
  DSH 窗口完全遮挡」时 `foreground`/`occluded` 标记正确；前台正向路径（目标窗口在前台）
  与真实后端拒绝路径仍待真实对局复验；
- **XInput 槽位只报告、不保证**：虚拟手柄可能落到 slot 1+（= 玩家 2）；会尝试重建
  最多 2 次并给 warning，不保证游戏接受非 0 槽位。2026-10-30 本机实测（清理幽灵节点后
  仍）新建手柄落在 slot 1/2，疑似 ViGEmBus 驱动/总线状态，需重启后复验；
- 真实注入已回读通过（vgamepad / keyboard），但**长闭环尚未在真实游戏里跑**；默认仍 dry-run；
- **memory/API provider 未实现**：`game_memory` 是本地档案存储，不是内存读取器；
  `game_state` 的 `player.x/y` 等字段要等 provider 落地才能填；
- **60 Hz 状态策略只有单测/dry-run 覆盖**（安全中止、闪避冷却、脱困、松手、status 形状），
  真实后端下的长对局尚未复验；
- **通用状态语义未逐游戏标定**：场景关键词、HP 区域、弹反颜色、威胁半径都还是通用默认值；
  Cuphead 样例 profile 只用于 dogfood，不是校准结果；
- 帧差阈值、OCR 区域未按具体游戏校准。

## 变更记录

- **2026-10-30（通用玩法基线：WorldState + 60 Hz 状态策略 + 档案层）**：
  - 引擎新增 `state.py`（WorldState 提取：场景 / HP / 弹反点 / 移动威胁 / UI 文本；
    坐标归一化、提取器不抛异常）与 `policy.py`（60 Hz `PolicyRunner`：按 profile
    hold / advance / dodge / stuck，逐拍复检安全闸，退出必 `release_all`）；
    `engine.py` 增加 `grab_raw()`（单次抓帧、不 OCR）；`session` 接线 `state` /
    `policy_start` / `policy_stop`。
  - 插件新增 `game_state` / `game_policy` / `game_memory` 与 `lib/profile-store.js`；
    `game_attach` 支持可选 `profile`；profile 目录 `$DSH_GAME_BRIDGE_PROFILE_DIR`
    或缓存根 `profiles/`，id 白名单校验、拒绝路径穿越。
  - 仓库放入 Cuphead 样例 profile（`profiles/cuphead.json`，只含键位/HUD/阈值，
    无内存偏移/攻略数据）。
  - **诚实边界**：memory/API provider 仍是设计位、**未实现**；`game_memory` 只管理本地
    档案，不读游戏内存；`game_state` 的 `player.x/y` 需要 provider；60 Hz 策略只有
    单测/dry-run 验证，真实对局未复验；通用状态语义未逐游戏标定。提交前会跑全量回归。
  - 文档：新增 `docs/STATE.md`（WorldState / GameProfile / provider / 降级 / 安全）；
    README / README.en 工具表 10→13 并增加「通用玩法基线」；DESIGN 新增 §2.6；本文件同步。
- **2026-10-30（0.0.2 打包与安装验证）**：版本号在四处 bump 到 0.0.2；本地产出
  wheel/sdist/npm tarball 并安装进桌面 profile 验证（`game_selftest` 报 plugin/engine
  0.0.2；dry-run `attach → snapshot → act → plan → stop` 通过；attach 到被 DSH 窗口
  完全遮挡的 Cuphead 时，`occluded` 标记正确）。修正两处诊断缺口：`lib/index.js` 的
  `VERSION` 常量漏 bump、桌面宿主不注入 `DSH_PROFILE_DIR` 导致安装来源显示 unknown
  （现在从安装路径/宿主 argv 推断 profile）。安装来源仍是临时 tarball，发布后应换 registry。
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
   替代「整屏 grab + 窗口矩形裁剪」，并逐游戏实机复验新的前台/遮挡拒绝路径；
7. **发布 0.0.2**：wheel/sdist + npm tarball 已本地构建并安装验收；发布后把当前桌面
   profile 的临时 tarball 换回 registry 来源。
8. **通用玩法基线的真实对局验证**：在真实游戏里跑 `game_state` → `game_policy` 长对局，
   标定 Cuphead 样例 profile 的 HP 区域/颜色阈值；在 memory/API provider 落地前，
   文档必须保持「未实现」的表述。

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
- **视觉保底 + 档案数据**：引擎零游戏代码；游戏差异只进 JSON profile，仓库只放通用样例。
- **内存是可选加速器**：provider 缺失/失败只降级为 `stale` + 视觉状态，基线照常工作；
  安全闸与状态来源无关，provider 不绕闸。





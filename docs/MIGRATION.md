# 迁移建议：宿项目 与 dsh-game-core 的关系

> 2026-10-29 记录。**本文只是建议，没有改动 `另一个本地项目` 任何代码**——
> 到目前为止对私人项目只做过只读参考（`observe/ocr.py`、`capture/screen.py`）。

## 现状

两条独立代码线：

| | 宿项目（私人） | dsh-game-core（新，MIT） |
|:--|:--|:--|
| 定位 | 陪伴桌宠 + 双环 + 五席 + 形象 + 记忆 | 只做「眼睛 + 手 + 小脑」的本地引擎 |
| 抓屏 | `capture/screen.py`（DXcam，同款实现） | `capture.py`（同款实现 + 多显示器映射） |
| OCR | `observe/ocr.py`（RapidOCR，`det_limit_type="max"` 的实测调优） | `ocr.py`（同一调优，注释里注明出处） |
| 帧差分 | `capture/diff.py` | `engine.grab_diff`（分类 + 指标） |
| 窗口/输入 | `winwindow.py`、`act/`（vgamepad/SendInput） | `windows.py`、`control.py`（同族能力，另有安全闸/审批/审计） |
| 测试 | 831 个 | 46 个 |

**当前选择：不迁移（选项 A）**。新引擎是插件专用的独立实现；两边共享的是
「实测结论」而不是代码依赖——这条边界让私人项目不必为发布节奏负责。

## 三个选项

### A. 不迁移（现状，推荐先保持）

- 优点：零风险；私人项目不被插件的版本/平台约束；两边可以各自演进。
- 代价：抓屏/OCR/窗口这几块是**两份实现**；实测调优常数（OCR 的 `max`、DXcam
  单次 grab、COM 清理）要在两边同步，漏了就在某一边退化。
- 缓解：把调优常数写成两边的注释 + `docs/DESIGN.md` 引用；新功能优先做进
  `dsh-game-core`，宿项目 需要时再考虑 B。

### B. 宿项目 反向依赖 `dsh-game-core`（发布并稳定后考虑）

前提：`dsh-game-core` 已在 PyPI 发布、版本 ≥ 0.1、连续两个版本没改公开 API。

- 让 宿项目 依赖 PyPI 包（MIT 兼容），只替换**观测/输入底座**：
  `capture`、`observe/ocr`、`windows`、`control`；
- 保留不动：`brain/`（双环、记忆、人设、闸门）、`voice/`、`avatar/`、`seats/`、
  `ui/`、`profile`、`gamepack`——这些是私人项目的核心价值，也不该被插件化。
- 需要一个**适配层**（`playertwo/observe/engine_bridge.py`）把引擎的 dict 结果
  映射回 宿项目 现有数据类（`TextLine` 等），避免 831 个测试大面积改 API。
- 收益：Win32/OCR/多显示器只维护一份；缺陷修复两边同时受益。
- 风险：宿项目 的延迟预算是按「进程内调用」定的，引擎是 stdio 子进程——
  `snapshot` 往返会多 ~5–10ms（实测引擎内部 grab ~5ms）。对 2.5Hz 采样无影响，
  但不能把它塞进 <100ms 的反射链路；反射链路（VAD/打断）继续留在 宿项目 进程内。

### C. 反过来：插件包住私人项目

**否决**。私人项目有玩家数据、资产许可与个人迭代史，不能作为公开依赖；
且会把插件的版本节奏绑死在一个不发布的仓库上。

## 如果将来做 B：步骤

1. `dsh-game-core` 发到 PyPI，锁定版本；
2. 在 宿项目 加适配层，先替换 `observe/ocr.py`（最容易对拍，输出形状简单）；
3. 用现有 `tools/calibrate.py` / `offline_review.py` 对拍两版 OCR 结果与耗时；
4. 再替换抓屏/窗口（注意 `ScreenCapturer` 的构造参数与 `grab()` 语义差异）；
5. 全量 `pytest tests/ -q` 必须全绿；跑一局实机确认延迟预算没被击穿；
6. 观察 2 周再删旧实现（保留 git 历史即可回滚）。

## 不该迁移的

`brain/memory*`、`brain/persona*`、`avatar/`、`voice/`、`seats/`、`ui/`、`profile`、
`gamepack`。它们要么是陪伴逻辑（私人项目 70% 重心），要么依赖玩家本机数据；
插件化只会让两边都变难。

## 边界提醒

- 引擎模块**不允许 import 私人项目的任何模块**——这条反过来也建议成立，
  避免未来出现循环依赖；
- 两边的「三条铁律」（随时夺回 / 无人不自娱 / 反作弊不接）必须各自在代码里
  成立，不能假定对方实现了；
- 许可证：两边都是 MIT 时才能自由互借；若 宿项目 将来改许可，B 方案需重评。

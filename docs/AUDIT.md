# 发布前审计（AUDIT）

> 2026-10-29 · 版本 0.0.1 · 审计时 HEAD `cf8e786`（第 26 个提交）
> 方法：把 `docs/RELEASE.md` 当 checklist 逐项实跑；命令与结果都在下面。

## 结论

**工程侧「可发布」**：版本一致、测试全绿、两条分发产物都真实装过并跑通集成、
仓库无密钥、私人项目零污染。**唯一缺口是发布凭证与真实注入授权**（需要用户）。

## 1. 仓库卫生

| 检查 | 结果 |
|:--|:--|
| 工作区 | 干净（`git status --short` 为空） |
| 被跟踪文件 | 48 个，全部属于插件/引擎/文档/测试/CI；无 `tmp/`、无 `.dsh-test/`、无 `dist/` |
| 密钥扫描 | 对全部被跟踪文件扫 `sk-*` / `yotta_pk_` / `AUTH_TOKEN=` / `api_key=`：**0 命中** |
| gitignore | `.dsh-test/`、`tmp/`、`engine/dist/`、`node_modules/` 均被忽略 |
| 另一个项目 | 工作区干净、未受影响（本次审计只读参考） |

## 2. 版本一致性

`test/versions.test.mjs` 把四处钉死并通过：`package.json` / `lib/bootstrap.js`
（ENGINE_VERSION）/ `engine/pyproject.toml` / `engine/dsh_game_core/__init__.py` = `0.0.1`。
另有一条平台闸单测（非 Windows 拒绝 + 开发覆盖）。

## 3. 测试矩阵

| 套件 | 结果 |
|:--|:--|
| `npm test`（契约 + 版本 + 平台） | 10 passed |
| `python -m pytest engine/tests` | 46 passed |
| `npm run test:all`（隔离 harness 集成） | **10/10 PASS**，约 110 秒 |

集成覆盖：M0 合成帧 / M1 真实屏幕+OCR / M2 attach→dry-run act / M3 闭环 /
events / windows / controls / 审批 fail-closed / 引擎崩溃自愈 / 自举安装。

## 4. 构建与校验

`pwsh -File scripts/release.ps1`（演练模式）通过：

```
dsh_game_core-0.0.1-py3-none-any.whl   28.7 KB
dsh_game_core-0.0.1.tar.gz             32.6 KB
dsh-game-bridge-0.0.1.tgz              22.9 KB, 9 files
```

脚本校验项全部通过：wheel 内含 8 个模块 + license；tarball 含
`package.json` / `cordis.patch.yml` / `lib/index.js`，且不含 `tmp/`、`.dsh-test/`、
`node_modules/`；版本三处一致。

## 5. 分发产物真实安装

不是本地 link，而是 `dsh plugin --profile headless add <tarball>`：

```
M1：real screen frame used: true / OCR text attached: true → PASS
M3：attach → plan → status → stop → PASS
```

（验证完已切回 symlink 以便继续开发。）

## 6. 安全声明核对（代码里成立，不只是文档）

| 声明 | 代码位置 | 已验证 |
|:--|:--|:--|
| 反作弊硬阻断 | `safety.py` KNOWN_ANTICHEAT_PROCESSES | 单测（前缀匹配/阻断） |
| 无人不自娱（fail-closed） | `safety.py` 无遥测也拒绝 | 单测 |
| F12 夺回闩锁 | `safety.py` | 单测 |
| 真实后端需审批 | `lib/index.js` `tools/pre-execute` → `{kind:'ask'}` | 集成（headless 无应答者 → 拒绝，报文实测） |
| 审计可选、路径用户指定 | `audit.py` | 单测 + 集成写入 4 类事件 |
| 默认 dry-run | `control.py` | 全部集成默认走 dry-run |

## 7. 文档完整性

README（中/英）、DESIGN、RELEASE、STATUS、CONTROLS、MARKETPLACE、engine/README、
LICENSE×2、CI workflow 均在库。

## 8. 发布阻塞项（2026-10-29 已解除）

1. ~~`gh auth login`~~ → 仓库已建并 push（SSH remote，private）；
2. ~~`npm login` + `UV_PUBLISH_TOKEN`~~ → 两处均已发布 0.0.1；
3. 用户授权的真实注入实测（vgamepad 按 A / keyboard 按 W，约 3 秒）——**仍未做**；
4. 市场提交——待仓库转 public。

## 9. 0.0.1 发布后验收（2026-10-29 实测）

| 检查 | 结果 |
|:--|:--|
| npm | `dsh-game-bridge@0.0.1`，maintainer `ihuakaze`，dist-tag `latest` 指向 0.0.1 |
| PyPI | `dsh-game-core==0.0.1` 可装；当前 release 只有 wheel（sdist 漏发，脚本已修） |
| 引擎安装 | 全新 venv `uv pip install dsh-game-core==0.0.1` 成功（含依赖约 102s），selftest OCR ready |
| 插件安装 | 从 registry 下载的 0.0.1 tarball → 隔离 profile 安装成功 |
| 端到端 | 同一安装 + **空缓存自举**（PyPI 拉引擎）→ M1 真实抓屏/OCR PASS（18.6s）；M3 闭环 PASS |
| 环境异常 | 本机 pnpm 12 连 registry 报 `os error 10013`（Node/npm/uv 正常），故用 tarball 安装；已记入 STATUS |

发布过程中遇到 npm 的 **staged publishing**：首次网页/上传会生成 `0.0.0-stage` 占位包，
CLI 直接 publish 会报 `E409 Cannot publish over previously staged version`；等暂存版本
批准后 0.0.1 才出现在 registry（本次约 2 分钟后生效）。这条已写进 RELEASE。

**结论：包已发布且发布产物端到端可用。** 剩余：仓库转 public、市场提交、真实注入实测。

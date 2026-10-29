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
| 私人项目 | `另一个本地项目` HEAD 仍为 `<removed>`（<removed>），工作区干净——**零改动** |

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

## 8. 发布阻塞项（唯一缺口）

1. `gh auth login`（建远程 + push）；
2. `npm login` + `UV_PUBLISH_TOKEN`（`scripts/release.ps1 -Publish`）；
3. 用户授权的真实注入实测（vgamepad 按 A / keyboard 按 W，约 3 秒）；
4. 发布后按 RELEASE §2 用**真实包名**复验安装；市场提交按 MARKETPLACE。

在上述 1–3 完成前，**不要**把版本标记为已发布。

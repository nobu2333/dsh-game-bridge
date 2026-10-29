# 发布清单（RELEASE）

> 版本号只在 `package.json` 里改一次；`test/versions.test.mjs` 会检查
> `lib/bootstrap.js`、`engine/pyproject.toml`、`engine/dsh_game_core/__init__.py`
> 三处必须同步，否则测试直接红。

## 一条命令（推荐）

```powershell
pwsh -File scripts/release.ps1            # 演练：测试 + 构建 + 校验产物，不发布
npm login                                 # 一次
$env:UV_PUBLISH_TOKEN='<pypi token>'      # 一次
pwsh -File scripts/release.ps1 -Publish -SkipTests   # 真发布
```

脚本会拒绝：缺 token、npm 未登录、tarball 里出现 `tmp/`、`.dsh-test/`、`node_modules`、
或缺少 `package.json` / `cordis.patch.yml` / `lib/index.js`。

## 0. 发布前自检

```powershell
npm test                                   # 契约 + 版本一致性
cd engine; python -m pytest tests -q       # 引擎单测（含安全闸/闭环）
cd ..
# 集成：真实引擎（dry-run）
$env:DSH_HOME='<repo>/.dsh-test'
$env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'
$env:DSH_GAME_BRIDGE_ENGINE_DIR='<repo>/engine'
$env:DSH_GAME_BRIDGE_UNATTENDED_S='86400'
$env:FAKE_SEQUENCE='game_attach,game_plan,game_status,game_stop'
npm run test:session
```

## 1. 引擎（PyPI）

```powershell
uv build engine
# 产物：engine/dist/dsh_game_core-<v>-py3-none-any.whl + .tar.gz
uv publish engine/dist/*            # 需要 PyPI token：UV_PUBLISH_TOKEN
```

发布后验证「自举安装真实引擎」：清空缓存目录，设
`DSH_GAME_BRIDGE_ENGINE_SPEC='dsh-game-core==<v>'`，跑 `npm run test:session`
（首次会下载 numpy/dxcam/rapidocr，耗时较长）。

## 2. 插件（npm）

```powershell
npm pack --dry-run                  # 确认只含 9 个文件、无 tmp/.dsh-test
npm publish --access public         # 需要 npm 登录（2FA，交互输 OTP）
```

**npm staged publishing（2026-10-29 实测）**：首次通过网页上传/暂存时，registry 会先
生成 `0.0.0-stage` 占位包；此后 CLI 直接 publish 同一版本会报

```
E409 Cannot publish over previously staged version "0.0.1"
```

这不是失败：去 npm 网页的包页面批准该暂存版本（需 2FA），稍后 `npm view` 就能看到
`0.0.1` 且 `latest` 指向它。CLI 非交互环境无法输 OTP，所以发布请在自己的终端跑。

发布后必须用**真实包名**验证官方安装链路（不要用本地路径）：

```powershell
$env:DSH_HOME='<repo>/.dsh-test'
dsh plugin --profile headless remove dsh-game-bridge
dsh plugin --profile headless add dsh-game-bridge      # 从 registry 装
python -m pytest engine/tests -q
```

## 3. 插件市场

- 需要先满足两条硬门槛：**没有 install/postinstall 脚本**、在干净沙箱里装得通；
- 我们的包会在市场里被标 `terminal surface`（会 spawn 引擎进程），README 已写明；
- 提交材料：包名 `dsh-game-bridge`、一句话描述、README、许可证 MIT、
  平台 Windows-only、明确「默认 dry-run、反作弊游戏拒绝输出」。

## 4. 发布后必须实测（目前未做）

1. **真实手柄注入**（vgamepad 后端，需用户同意）：按一次 A 并回读 XInput；
2. **反作弊阻断**：在装有 EAC 的机器上确认 `game_act` 被拒绝；
3. **夺回**：闭环运行中按 F12，确认一拍内松手；
4. **无人不自娱**：闭环运行中停止键鼠输入超过阈值，确认自动 abort；
5. **审批**：`DSH_GAME_BRIDGE_CONTROL=vgamepad` 时，Web 界面里 attach 会弹出
   一次性批准；拒绝后 attach 不执行（headless 下直接 fail-closed）。

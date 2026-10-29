#requires -Version 7
<#
.SYNOPSIS
  dsh-game-bridge 发布助手：测试 → 构建 wheel / npm tarball → 校验 →（可选）发布。

.DESCRIPTION
  默认是「演练模式」：只跑测试、构建产物并校验，不会碰任何 registry。
  只有显式加 -Publish 才真的 uv publish + npm publish，并且要求凭据已就绪。

.EXAMPLE
  pwsh -File scripts/release.ps1                 # 演练：构建并校验
  pwsh -File scripts/release.ps1 -Publish        # 真发布（需要 token / npm 登录）
  pwsh -File scripts/release.ps1 -SkipTests      # 只打包（不建议用于发布）
#>
param(
  [switch]$Publish,
  [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
  $pkg = Get-Content package.json -Raw | ConvertFrom-Json
  $version = $pkg.version
  Write-Host "== dsh-game-bridge $version ==" -ForegroundColor Cyan

  # ── 1. 测试 ────────────────────────────────────────────────────────
  if (-not $SkipTests) {
    Write-Host "`n[1/4] 插件契约 + 版本一致性测试" -ForegroundColor Cyan
    npm test
    if ($LASTEXITCODE -ne 0) { throw "npm test failed" }

    Write-Host "`n[1/4] 引擎单测" -ForegroundColor Cyan
    $enginePython = $env:DSH_GAME_BRIDGE_PYTHON
    if (-not $enginePython) {
      $enginePython = (Get-Command python -ErrorAction Stop).Source
    }
    Push-Location engine
    try {
      & $enginePython -m pytest tests -q
      if ($LASTEXITCODE -ne 0) { throw "engine pytest failed" }
    } finally {
      Pop-Location
    }
  } else {
    Write-Host "`n[1/4] 跳过测试（-SkipTests）" -ForegroundColor Yellow
  }

  # ── 2. 构建引擎 wheel / sdist ─────────────────────────────────────
  Write-Host "`n[2/4] 构建 Python 包" -ForegroundColor Cyan
  Push-Location engine
  try {
    uv build
    if ($LASTEXITCODE -ne 0) { throw "uv build failed" }
  } finally {
    Pop-Location
  }
  $wheel = Get-ChildItem engine/dist/*.whl | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $sdist = Get-ChildItem engine/dist/*.tar.gz | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $wheel) { throw "wheel not found under engine/dist" }

  # ── 3. 构建 npm tarball 并校验内容 ────────────────────────────────
  Write-Host "`n[3/4] 打包 npm 并校验内容" -ForegroundColor Cyan
  if (Test-Path tmp/pack) { Remove-Item tmp/pack -Recurse -Force }
  New-Item -ItemType Directory -Force -Path tmp/pack | Out-Null
  $packOutput = npm pack --pack-destination tmp/pack 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) { throw "npm pack failed`n$packOutput" }
  $tgz = Get-ChildItem tmp/pack/*.tgz | Select-Object -First 1
  if (-not $tgz) { throw "npm tarball not found" }

  $listing = (tar -tzf $tgz.FullName) -split "`n" | Where-Object { $_ -and $_ -notmatch '/$' }
  $expected = @('package/package.json', 'package/cordis.patch.yml', 'package/lib/index.js')
  foreach ($item in $expected) {
    if ($listing -notcontains $item) { throw "tarball missing $item" }
  }
  $forbidden = $listing | Where-Object { $_ -match '\.dsh-test|node_modules|/tmp/' }
  if ($forbidden) { throw "tarball contains forbidden paths: $($forbidden -join ', ')" }

  Write-Host "`n产物：" -ForegroundColor Green
  Write-Host ("  {0}  ({1:N1} KB)" -f $wheel.Name, ($wheel.Length / 1KB))
  if ($sdist) { Write-Host ("  {0}  ({1:N1} KB)" -f $sdist.Name, ($sdist.Length / 1KB)) }
  Write-Host ("  {0}  ({1:N1} KB, {2} files)" -f $tgz.Name, ($tgz.Length / 1KB), $listing.Count)

  # ── 4. 发布（仅 -Publish）─────────────────────────────────────────
  if (-not $Publish) {
    Write-Host "`n[4/4] 演练模式：不发布。" -ForegroundColor Yellow
    Write-Host "  真发布：" -ForegroundColor Yellow
    Write-Host "    `$env:UV_PUBLISH_TOKEN='<pypi token>'" -ForegroundColor Yellow
    Write-Host "    npm login" -ForegroundColor Yellow
    Write-Host "    pwsh -File scripts/release.ps1 -Publish -SkipTests" -ForegroundColor Yellow
    Write-Host "`n发布后按 docs/RELEASE.md 的清单做安装与实机验收。" -ForegroundColor Yellow
    return
  }

  Write-Host "`n[4/4] 发布到 PyPI" -ForegroundColor Cyan
  if (-not $env:UV_PUBLISH_TOKEN) { throw "UV_PUBLISH_TOKEN is not set" }
  if ($sdist) {
    uv publish $wheel.FullName $sdist.FullName
  } else {
    uv publish $wheel.FullName
  }
  if ($LASTEXITCODE -ne 0) { throw "uv publish failed" }

  Write-Host "`n[4/4] 发布到 npm" -ForegroundColor Cyan
  $whoami = npm whoami 2>&1
  if ($LASTEXITCODE -ne 0) { throw "npm not logged in: run `npm login` first" }
  npm publish $tgz.FullName
  if ($LASTEXITCODE -ne 0) { throw "npm publish failed" }

  Write-Host "`n发布完成：dsh-game-core==$version / dsh-game-bridge@$version" -ForegroundColor Green
  Write-Host "下一步：用真实包名验证官方安装（docs/RELEASE.md §2）。" -ForegroundColor Green
} finally {
  Pop-Location
}

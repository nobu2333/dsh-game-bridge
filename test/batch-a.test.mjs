/**
 * Batch A 单元测试：自举 spec 与安装来源分类。
 *
 * 全是纯函数，不 spawn 引擎、不读写用户 profile、不触碰真实路径——
 * 产出的诊断文本会进模型上下文，所以这里也顺带钉住「不能把本机路径写死」。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { ENGINE_VERSION, cacheHealthProgram, engineInstallSpec, requestedBackend } from '../lib/bootstrap.js'
import { classifyInstallSource, describeInstall } from '../lib/index.js'

// 通用、与机器无关的 profile 路径（测试只验证派生逻辑，不读真实文件）。
const PROFILE_DIR = 'profiles/headless'
const PACKAGE_DIR = 'plugin-package'

function fakeReadJson(manifest) {
  return () => manifest
}

function installFor(dependency, env = { DSH_PROFILE_DIR: PROFILE_DIR }) {
  const manifest = dependency === null ? { dependencies: {} } : { dependencies: { 'dsh-game-bridge': dependency } }
  return describeInstall({ env, packageDir: PACKAGE_DIR, readJson: fakeReadJson(manifest) })
}

test('requestedBackend defaults to dry-run when nothing is set', () => {
  assert.equal(requestedBackend({}), 'dry-run')
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: '' }), 'dry-run')
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: '   ' }), 'dry-run')
})

test('requestedBackend accepts the gamepad alias and normalizes case', () => {
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: 'gamepad' }), 'vgamepad')
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: 'VGAMEPAD' }), 'vgamepad')
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: ' keyboard ' }), 'keyboard')
  // 引擎侧接受的别名也归一化，避免插件与引擎对同一个后端叫法不一致。
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: 'sendinput' }), 'keyboard')
})

test('requestedBackend passes unknown backends through for forward compatibility', () => {
  assert.equal(requestedBackend({ DSH_GAME_BRIDGE_CONTROL: 'xinput' }), 'xinput')
})

test('engineInstallSpec installs the pinned engine, with the gamepad extra only when requested', () => {
  assert.equal(engineInstallSpec({}), `dsh-game-core==${ENGINE_VERSION}`)
  assert.equal(engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'keyboard' }), `dsh-game-core==${ENGINE_VERSION}`)
  assert.equal(
    engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad' }),
    `dsh-game-core[gamepad]==${ENGINE_VERSION}`,
  )
  assert.equal(
    engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'gamepad' }),
    `dsh-game-core[gamepad]==${ENGINE_VERSION}`,
  )
})

test('engineInstallSpec injects the gamepad extra before the version operator', () => {
  assert.equal(
    engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad', DSH_GAME_BRIDGE_ENGINE_SPEC: 'dsh-game-core==0.0.1' }),
    'dsh-game-core[gamepad]==0.0.1',
  )
  assert.equal(
    engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad', DSH_GAME_BRIDGE_ENGINE_SPEC: 'dsh-game-core>=0.0.1,<0.1' }),
    'dsh-game-core[gamepad]>=0.0.1,<0.1',
  )
  assert.equal(
    engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad', DSH_GAME_BRIDGE_ENGINE_SPEC: 'dsh-game-core' }),
    'dsh-game-core[gamepad]',
  )
})

test('engineInstallSpec keeps an explicit extra instead of rewriting it', () => {
  for (const spec of ['dsh-game-core[gamepad]==0.0.1', 'dsh-game-core[other]', 'dsh-game-core[gamepad]']) {
    assert.equal(
      engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad', DSH_GAME_BRIDGE_ENGINE_SPEC: spec }),
      spec,
    )
  }
})

test('engineInstallSpec leaves local paths and URLs untouched', () => {
  const specs = [
    './tmp/dsh-game-core-build',
    '../engine',
    'tmp/wheels/dsh_game_core-0.0.1-py3-none-any.whl',
    'dsh_game_core-0.0.1-py3-none-any.whl',
    'https://example.com/dsh-game-core-0.0.1.tar.gz',
    'file:../engine',
    'github:someone/dsh-game-core',
    'dsh-game-core @ https://example.com/dsh-game-core.whl',
  ]
  for (const spec of specs) {
    assert.equal(
      engineInstallSpec({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad', DSH_GAME_BRIDGE_ENGINE_SPEC: spec }),
      spec,
      `spec ${spec} must be passed through`,
    )
  }
})

test('cacheHealthProgram validates the selected backend', () => {
  assert.equal(cacheHealthProgram({}), 'import dsh_game_core')
  assert.equal(cacheHealthProgram({ DSH_GAME_BRIDGE_CONTROL: 'keyboard' }), 'import dsh_game_core')
  assert.equal(
    cacheHealthProgram({ DSH_GAME_BRIDGE_CONTROL: 'vgamepad' }),
    'import dsh_game_core; import vgamepad',
  )
  assert.equal(
    cacheHealthProgram({ DSH_GAME_BRIDGE_CONTROL: 'gamepad' }),
    'import dsh_game_core; import vgamepad',
  )
})

test('describeInstall reports a registry install without warnings', () => {
  const install = installFor('^0.0.1')
  assert.equal(install.source, 'registry')
  assert.equal(install.dependency, '^0.0.1')
  assert.equal(install.profile, 'headless')
  assert.equal(install.profile_dir, PROFILE_DIR)
  assert.equal(install.package_dir, PACKAGE_DIR)
  assert.deepEqual(install.warnings, [])
})

test('describeInstall recognizes file:, link: and github installs', () => {
  assert.equal(installFor('file:../vendor/dsh-game-bridge').source, 'local-file')
  assert.equal(installFor('link:../dsh-game-bridge').source, 'link')
  assert.equal(installFor('github:someone/dsh-game-bridge').source, 'github')
  assert.equal(installFor('https://github.com/someone/dsh-game-bridge/archive/main.tar.gz').source, 'github')
})

test('describeInstall warns when the package was installed from a temporary directory', () => {
  const install = installFor('file:./tmp/dsh-game-bridge')
  assert.equal(install.source, 'local-file')
  assert.equal(install.warnings.length, 1)
  assert.match(install.warnings[0], /temporary directory/)
  // `\temp\` 也要识别（Windows 下 profile 里是反斜杠路径）。
  const windowsTemp = installFor('file:./temp\\dsh-game-bridge')
  assert.equal(windowsTemp.source, 'local-file')
  assert.match(windowsTemp.warnings[0], /temporary directory/)
  // 稳定的本地目录不告警。
  assert.deepEqual(installFor('file:../vendor/dsh-game-bridge').warnings, [])
})

test('describeInstall degrades gracefully without a profile directory or manifest', () => {
  const noProfile = describeInstall({ env: {}, packageDir: PACKAGE_DIR, readJson: () => ({}) })
  assert.equal(noProfile.source, 'unknown')
  assert.equal(noProfile.profile_dir, null)
  assert.equal(noProfile.dependency, null)
  assert.equal(noProfile.package_dir, PACKAGE_DIR)
  assert.ok(noProfile.warnings.some((warning) => /DSH_PROFILE_DIR/.test(warning)))

  const unreadable = describeInstall({
    env: { DSH_PROFILE_DIR: PROFILE_DIR },
    packageDir: PACKAGE_DIR,
    readJson: () => {
      throw new Error('ENOENT: no such file')
    },
  })
  assert.equal(unreadable.source, 'unknown')
  assert.ok(unreadable.warnings.some((warning) => /cannot read/.test(warning)))

  const missingDependency = installFor(null)
  assert.equal(missingDependency.source, 'unknown')
  assert.equal(missingDependency.dependency, null)
  assert.ok(missingDependency.warnings.some((warning) => /no dsh-game-bridge dependency/.test(warning)))
})

test('describeInstall prefers DSH_PROFILE over the profile directory name', () => {
  const install = installFor('^0.0.1', { DSH_PROFILE_DIR: PROFILE_DIR, DSH_PROFILE: 'web' })
  assert.equal(install.profile, 'web')
})

test('classifyInstallSource covers the documented source set', () => {
  assert.equal(classifyInstallSource('0.0.1'), 'registry')
  assert.equal(classifyInstallSource('latest'), 'registry')
  assert.equal(classifyInstallSource('npm:dsh-game-bridge@^0.0.1'), 'registry')
  assert.equal(classifyInstallSource('workspace:*'), 'link')
  assert.equal(classifyInstallSource('https://example.com/pkg.tgz'), 'unknown')
  assert.equal(classifyInstallSource('git+https://example.com/pkg.git'), 'unknown')
  assert.equal(classifyInstallSource(''), 'unknown')
})

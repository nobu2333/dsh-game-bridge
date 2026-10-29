/**
 * 全量集成回归：一次性把六条路径跑完并汇总。
 *
 * 前置（一次性）：
 *   $env:DSH_HOME='<repo>/.dsh-test'
 *   dsh --profile headless --dump-config
 *   dsh plugin --profile headless add link:<repo>      # 开发用 symlink
 *
 * 运行：
 *   $env:DSH_GAME_BRIDGE_PYTHON='<python-with-deps>'   # 不设则跳过真实引擎三条
 *   npm run test:all
 *
 * 每条都通过 test/integration/m0-session.mjs 跑一个隔离 headless 会话，
 * 用假模型脚本化工具调用，再从「harness 实际发给模型的请求体」里断言。
 */
import { spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '../..')
const dshHome = process.env.DSH_HOME ?? resolve(repo, '.dsh-test')
const python = process.env.DSH_GAME_BRIDGE_PYTHON
const engineDir = process.env.DSH_GAME_BRIDGE_ENGINE_DIR ?? resolve(repo, 'engine')
const cacheDir = resolve(repo, `tmp/regression-cache-${Date.now()}`)

const baseEnv = { ...process.env, DSH_HOME: dshHome }
for (const key of Object.keys(baseEnv)) {
  if (key.startsWith('DSH_GAME_BRIDGE_') || key.startsWith('FAKE_')) delete baseEnv[key]
}

const real = { DSH_GAME_BRIDGE_PYTHON: python, DSH_GAME_BRIDGE_ENGINE_DIR: engineDir }
const unattended = { DSH_GAME_BRIDGE_UNATTENDED_S: '86400' }

const cases = [
  {
    name: 'M0 synthetic snapshot',
    env: { DSH_GAME_BRIDGE_PYTHON: 'off', FAKE_TOOL: 'game_snapshot' },
    expect: 'M0 INTEGRATION PASS',
  },
  {
    name: 'M1 real screen + OCR',
    env: { ...real, FAKE_TOOL: 'game_snapshot' },
    expect: 'M1 INTEGRATION PASS',
    requiresPython: true,
  },
  {
    name: 'M2 attach → dry-run act',
    env: { ...real, ...unattended, FAKE_WINDOW: 'unspecified', FAKE_SEQUENCE: 'game_attach,game_act' },
    expect: 'M2 PASS',
    requiresPython: true,
  },
  {
    name: 'M3 attach → plan → status → stop',
    env: {
      ...real,
      ...unattended,
      FAKE_WINDOW: 'unspecified',
      FAKE_SEQUENCE: 'game_attach,game_plan,game_status,game_stop',
    },
    expect: 'M3 PASS',
    requiresPython: true,
  },
  {
    name: 'events (real frame differencing)',
    env: { ...real, FAKE_SEQUENCE: 'game_events' },
    expect: 'EVENTS PASS',
    requiresPython: true,
  },
  {
    name: 'windows (real window list)',
    env: { ...real, FAKE_SEQUENCE: 'game_windows' },
    expect: 'WINDOWS PASS',
    requiresPython: true,
  },
  {
    name: 'bootstrap (fixture engine install)',
    env: {
      DSH_GAME_BRIDGE_ENGINE_SPEC: resolve(repo, 'test/fixtures/fake-engine'),
      DSH_GAME_BRIDGE_CACHE_DIR: cacheDir,
      FAKE_TOOL: 'game_selftest',
    },
    expect: 'M1 BOOTSTRAP PASS',
  },
]

function runCase(testCase) {
  return new Promise((resolvePromise) => {
    const child = spawn(process.execPath, ['test/integration/m0-session.mjs'], {
      cwd: repo,
      env: { ...baseEnv, ...testCase.env },
      windowsHide: true,
    })
    let output = ''
    child.stdout.on('data', (chunk) => (output += chunk))
    child.stderr.on('data', (chunk) => (output += chunk))
    const timer = setTimeout(() => {
      child.kill()
      resolvePromise({ ok: false, output: `${output}\n(timed out)` })
    }, 240_000)
    child.on('close', (code) => {
      clearTimeout(timer)
      const ok = code === 0 && output.includes(testCase.expect)
      resolvePromise({ ok, output })
    })
  })
}

const results = []
for (const testCase of cases) {
  if (testCase.requiresPython && !python) {
    results.push({ name: testCase.name, status: 'SKIP (set DSH_GAME_BRIDGE_PYTHON)' })
    console.log(`SKIP  ${testCase.name}`)
    continue
  }
  process.stdout.write(`RUN   ${testCase.name} ... `)
  const result = await runCase(testCase)
  results.push({ name: testCase.name, status: result.ok ? 'PASS' : 'FAIL' })
  console.log(result.ok ? 'PASS' : 'FAIL')
  if (!result.ok) console.log(result.output.split('\n').slice(-25).join('\n'))
}

rmSync(cacheDir, { recursive: true, force: true })

const failed = results.filter((item) => item.status === 'FAIL')
console.log('\n=== summary ===')
for (const item of results) console.log(`${item.status}\t${item.name}`)
process.exitCode = failed.length ? 1 : 0

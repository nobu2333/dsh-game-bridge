/**
 * 引擎自举：让插件在「用户没有 Python」的机器上也能用起来。
 *
 * 顺序：
 *   1. 开发/调试覆盖：DSH_GAME_BRIDGE_PYTHON 指向的 Python 直接可用；
 *   2. 缓存命中：<cache>/<version>/ 里已有 venv 就直接用；
 *   3. 自举：找 uv（PATH 或 DSH_GAME_BRIDGE_UV）→ `uv venv` →
 *      `uv pip install <spec>`（默认 `dsh-game-core==<version>`）→ 用缓存里的 python。
 *
 * 为什么用 uv：它能自己带一个 Python 解释器，用户机器不需要预装 Python；
 * 而且 venv 建在插件自己的缓存目录，卸载插件时删目录即可，不污染系统。
 *
 * 失败的语义：**绝不自作聪明重试或静默降级**——把 stderr 尾巴带回去，
 * 让工具结果里能直接看到是哪一步断了。
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, rmSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const ENGINE_VERSION = '0.0.1'

const isWindows = process.platform === 'win32'

/** 引擎可选依赖：真实手柄后端（vgamepad 需要一块虚拟 XInput 手柄）。 */
const GAMEPAD_EXTRA = 'gamepad'

/** `DSH_GAME_BRIDGE_CONTROL` 的别名归一化表；表外的值原样保留（便于前向兼容新后端）。 */
const BACKEND_ALIASES = new Map([
  ['gamepad', 'vgamepad'],
  ['dryrun', 'dry-run'],
  ['dry_run', 'dry-run'],
  ['sendinput', 'keyboard'],
])

/**
 * 用户请求的输出后端（纯函数，便于单测）。
 * @param {Record<string, string | undefined>} env
 * @returns {string} `"dry-run" | "vgamepad" | "keyboard"`，未知值原样返回（小写去空白）。
 */
export function requestedBackend(env = process.env) {
  const raw = String(env.DSH_GAME_BRIDGE_CONTROL ?? '').trim().toLowerCase()
  if (!raw) return 'dry-run'
  return BACKEND_ALIASES.get(raw) ?? raw
}

/** 本地路径 / wheel / URL / direct reference —— pip 不需要也不允许在包名后加 extra。 */
const NON_REGISTRY_SPEC = /[\\/]|^[.~]|^[A-Za-z]:|\.(?:whl|zip|tgz|tar\.gz)$|\s@\s/i
const URL_SPEC = /^[a-z][a-z0-9+.-]*:\/\//i
const OTHER_SCHEME_SPEC = /^(?:file|link|github|git|git\+|npm):/i

/**
 * 自举时该装什么（纯函数，便于单测）。
 *
 * 默认 `dsh-game-core==<version>`；vgamepad 后端会带上 `[gamepad]` extra。
 * `DSH_GAME_BRIDGE_ENGINE_SPEC` 覆盖时：像包名（可带 [extra]/版本操作符）就在版本
 * 操作符前补 `[gamepad]`；像本地路径 / URL / wheel 就原样透传。
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function engineInstallSpec(env = process.env) {
  const wantGamepad = requestedBackend(env) === 'vgamepad'
  const raw = String(env.DSH_GAME_BRIDGE_ENGINE_SPEC ?? '').trim()
  if (!raw) return `dsh-game-core${wantGamepad ? `[${GAMEPAD_EXTRA}]` : ''}==${ENGINE_VERSION}`
  if (URL_SPEC.test(raw) || OTHER_SCHEME_SPEC.test(raw) || NON_REGISTRY_SPEC.test(raw)) return raw
  const parsed = /^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?(.*)$/s.exec(raw)
  if (!parsed) return raw
  const [, name, extras, rest] = parsed
  // 已经写了自己的 extra 就不动它：用户显式选择优先，避免装进意料之外的依赖。
  if (!wantGamepad || extras) return raw
  return `${name}[${GAMEPAD_EXTRA}]${rest}`
}

/**
 * 缓存健康检查要跑的 import 语句（纯函数）。
 *
 * 不能只 `import dsh_game_core`：venv 里没有 vgamepad 时缓存看起来「命中」，
 * 但一 attach 真实手柄后端就 BACKEND_UNAVAILABLE（实测踩到）。
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function cacheHealthProgram(env = process.env) {
  return requestedBackend(env) === 'vgamepad' ? 'import dsh_game_core; import vgamepad' : 'import dsh_game_core'
}

export function engineRoot(env = process.env) {
  if (env.DSH_GAME_BRIDGE_CACHE_DIR) return env.DSH_GAME_BRIDGE_CACHE_DIR
  if (isWindows) return join(env.LOCALAPPDATA ?? homedir(), 'dsh-game-bridge', 'engine')
  if (process.platform === 'darwin') return join(homedir(), 'Library', 'Caches', 'dsh-game-bridge', 'engine')
  return join(env.XDG_CACHE_HOME ?? join(homedir(), '.cache'), 'dsh-game-bridge', 'engine')
}

function venvPython(dir) {
  return isWindows ? join(dir, 'Scripts', 'python.exe') : join(dir, 'bin', 'python')
}

/** 找 uv：显式路径 > PATH。找不到返回 null（由调用方给出人话级错误）。 */
export function locateUv(env = process.env) {
  const explicit = env.DSH_GAME_BRIDGE_UV
  if (explicit) return existsSync(explicit) ? explicit : null
  const probe = spawnSync('uv', ['--version'], { windowsHide: true, encoding: 'utf8' })
  if (probe.status === 0) return 'uv'
  return null
}

/**
 * 跑一个子进程并流式收集输出；超时会整棵杀掉。
 * @returns {Promise<string>} 合并后的 stderr/stdout 尾巴
 */
function run(command, args, { env, timeoutMs = 600_000, onOutput, signal } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env: { ...process.env, ...env },
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let output = ''
    const timer = setTimeout(() => {
      try {
        spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
      } catch {
        /* 已经退出 */
      }
      reject(new Error(`${command} ${args.join(' ')} timed out after ${timeoutMs}ms\n${output.slice(-2000)}`))
    }, timeoutMs)
    const abort = () => {
      try {
        child.kill()
      } catch {
        /* 已经退出 */
      }
    }
    signal?.addEventListener('abort', abort, { once: true })
    const collect = (chunk) => {
      const text = String(chunk)
      output = (output + text).slice(-8000)
      onOutput?.(text.trim())
    }
    child.stdout.on('data', collect)
    child.stderr.on('data', collect)
    child.on('error', (error) => {
      clearTimeout(timer)
      reject(new Error(`${command} failed to start: ${error.message}`))
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      if (code === 0) resolve(output)
      else reject(new Error(`${command} ${args.join(' ')} exited ${code}\n${output.slice(-2000)}`))
    })
  })
}

/**
 * 平台闸：v1 的抓屏、虚拟手柄、输入注入全是 Win32，非 Windows 提前说清楚，
 * 而不是等用户 attach/snapshot 时才炸。
 *
 * @returns {string | null} 不支持时返回人话原因；支持时返回 null。
 */
export function checkPlatform(platform = process.platform, env = process.env) {
  if (platform === 'win32') return null
  if (env.DSH_GAME_BRIDGE_ALLOW_UNSUPPORTED === '1') return null
  return (
    `dsh-game-bridge ${ENGINE_VERSION} supports Windows only (capture and input injection are Win32); ` +
    `current platform is ${platform}. Set DSH_GAME_BRIDGE_ALLOW_UNSUPPORTED=1 to override for development.`
  )
}

/** 缓存健康检查：venv 里的 Python 必须真的能 import 引擎模块（以及所选后端）。 */
function cacheHealthy(python, env = process.env) {
  try {
    const result = spawnSync(python, ['-c', cacheHealthProgram(env)], { windowsHide: true, timeout: 30_000 })
    return result.status === 0
  } catch {
    return false
  }
}

/**
 * 确保引擎可用。**串行化**：并发调用共享同一个 Promise（插件可能同时被
 * selftest 与 snapshot 触发）。
 */
export function createEngineBootstrap({ env = process.env, onProgress = () => {} } = {}) {
  let promise = null
  let controller = null

  async function bootstrap() {
    const devPython = env.DSH_GAME_BRIDGE_PYTHON
    if (devPython && devPython !== 'off') {
      onProgress(`using dev python ${devPython}`)
      return { python: devPython, cwd: env.DSH_GAME_BRIDGE_ENGINE_DIR, source: 'dev' }
    }
    if (devPython === 'off') throw new Error('engine disabled by DSH_GAME_BRIDGE_PYTHON=off')

    const unsupported = checkPlatform(process.platform, env)
    if (unsupported) throw new Error(unsupported)

    const root = engineRoot(env)
    const dir = join(root, ENGINE_VERSION)
    const python = venvPython(dir)
    // ⚠️ 不能只看 python.exe 存在：venv 建好但 pip install 失败会留下空环境，
    // 之后每次启动都「缓存命中」，工具全部报 No module named dsh_game_core（实测踩到）。
    // 健康检查也覆盖所选后端：vgamepad 后端要求 vgamepad 真的能 import。
    if (existsSync(python) && cacheHealthy(python, env)) {
      onProgress(`engine cache hit: ${dir}`)
      return { python, cwd: undefined, source: 'cache' }
    }
    if (existsSync(dir)) {
      onProgress(`repairing incomplete engine cache (backend ${requestedBackend(env)}): ${dir}`)
      rmSync(dir, { recursive: true, force: true })
    }

    const uv = locateUv(env)
    if (!uv) {
      throw new Error(
        'uv not found. Install it once (Windows: `winget install astral-sh.uv` or see https://docs.astral.sh/uv/) ' +
          'or set DSH_GAME_BRIDGE_UV to the uv executable.',
      )
    }

    controller = new AbortController()
    mkdirSync(dir, { recursive: true })
    onProgress(`creating engine venv at ${dir}`)
    await run(uv, ['venv', dir, '--python', env.DSH_GAME_BRIDGE_PYTHON_VERSION ?? '3.13'], {
      env,
      signal: controller.signal,
      timeoutMs: 300_000,
      onOutput: (text) => onProgress(text),
    })
    const spec = engineInstallSpec(env)
    onProgress(`installing ${spec}`)
    await run(uv, ['pip', 'install', '--python', python, spec], {
      env,
      signal: controller.signal,
      timeoutMs: 900_000,
      onOutput: (text) => onProgress(text),
    })
    if (!existsSync(python)) throw new Error(`engine install finished but ${python} is missing`)
    onProgress(`engine ready: ${python}`)
    return { python, cwd: undefined, source: 'installed' }
  }

  return {
    /** @returns {Promise<{python: string, cwd?: string, source: string}>} */
    ensure() {
      if (!promise) {
        promise = bootstrap().catch((error) => {
          promise = null // 允许下一次调用重试（例如用户装好了 uv）
          throw error
        })
      }
      return promise
    },
    /** 取消进行中的安装（插件卸载时用）。 */
    cancel() {
      controller?.abort()
      controller = null
    },
    cacheDir() {
      return join(engineRoot(env), ENGINE_VERSION)
    },
  }
}

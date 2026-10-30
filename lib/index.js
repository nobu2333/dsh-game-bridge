/**
 * dsh-game-bridge —— 插件入口（M1：自举引擎 + 真实抓屏 + OCR）。
 *
 * 工具面保持「目标级」：M1 只有自检与看一眼；`attach` / `plan` / `stop`
 * 在 M2 随「手 + 20 Hz 闭环」一起加。设计约束见 docs/DESIGN.md。
 *
 * 引擎状态机：idle → installing → ready | failed。
 * 插件装载时就开始自举（不阻塞 DSH 启动）；工具调用最多等一小段时间，
 * 没等到就降级成合成帧并把原因写进结果——绝不假装自己看见了屏幕。
 */
import { readFileSync, appendFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { EngineClient } from './engine.js'
import { createEngineBootstrap, ENGINE_VERSION, requestedBackend } from './bootstrap.js'
import { deleteProfile, listProfiles, readProfile, validateProfileId, writeProfile } from './profile-store.js'

export const name = 'dsh-game-bridge'

/** 依赖的宿主服务：工具注册表 + 图片附件存储。缺任一服务插件不会激活。 */
export const inject = ['tools', 'attachments']

const VERSION = '0.0.2'
const SYNTHETIC_FRAME = readFileSync(new URL('./frames/synthetic-frame.png', import.meta.url))

/** 插件自己的包目录（`lib/..`）——只用于诊断「这个插件是从哪装进来的」。 */
const PACKAGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))

/** profile package.json 里记录的依赖 spec → 安装来源。 */
const INSTALL_SOURCES = new Set(['registry', 'local-file', 'link', 'github', 'unknown'])
const PLUGIN_PACKAGE = 'dsh-game-bridge'
/** 从临时目录装进来的包迟早会消失（/tmp、%TEMP% 会被清理）。 */
const TEMP_PATH = /(?:^|[\\/])(?:tmp|temp)(?:[\\/]|$)/i

/**
 * 把依赖 spec 归类成安装来源（纯函数）。
 * @param {unknown} spec
 * @returns {'registry' | 'local-file' | 'link' | 'github' | 'unknown'}
 */
export function classifyInstallSource(spec) {
  const value = String(spec ?? '').trim()
  if (!value) return 'unknown'
  if (/^link:/i.test(value) || /^workspace:/i.test(value)) return 'link'
  if (/^file:/i.test(value) || /^\.\.?([\\/]|$)/.test(value)) return 'local-file'
  if (/github\.com/i.test(value) || /^(?:github|git\+github):/i.test(value)) return 'github'
  if (/^git[+@]/i.test(value) || /^git:/i.test(value)) return 'unknown'
  if (/^npm:/i.test(value)) return 'registry'
  if (/^https?:\/\//i.test(value)) return /registry\.npmjs\.org/i.test(value) ? 'registry' : 'unknown'
  // semver 区间 / 精确版本 / dist-tag（`^0.0.1`、`>=1 <2`、`latest`）。
  if (/^[\^~><=]*\s*v?\d/i.test(value) || /^[a-z][a-z0-9._-]*$/i.test(value)) return 'registry'
  return 'unknown'
}

function defaultReadJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

/** profile 目录推断：`<profile>/node_modules/dsh-game-bridge` → `<profile>`。 */
function profileDirFromPackageDir(packageDir) {
  if (!packageDir) return null
  const modules = dirname(packageDir)
  if (basename(modules) !== 'node_modules') return null
  const profileDir = dirname(modules)
  return profileDir && profileDir !== '.' ? profileDir : null
}

/** profile 目录推断：宿主命令行里通常带一个 `.../profiles/<name>` 参数。 */
function profileDirFromArgv(argv) {
  for (const raw of argv ?? []) {
    const value = String(raw ?? '').trim()
    if (/(?:^|[\\/])profiles[\\/][^\\/]+[\\/]?$/i.test(value)) return value.replace(/[\\/]+$/, '')
  }
  return null
}

/**
 * 诊断「这个插件是怎么装进当前 profile 的」（纯函数，依赖可注入，便于单测）。
 *
 * profile 目录优先取 `DSH_PROFILE_DIR`；桌面宿主不给这个 env 时，退化为
 * 「插件自己所在路径的 node_modules 父目录」或「宿主命令行里的 profiles/<name>」。
 *
 * @param {{
 *   env?: Record<string, string | undefined>,
 *   packageDir?: string,
 *   argv?: string[],
 *   readJson?: (path: string) => unknown,
 * }} [options]
 * @returns {{package_dir: string | null, profile: string | null, profile_dir: string | null,
 *   dependency: string | null, source: string, warnings: string[]}}
 */
export function describeInstall({
  env = process.env,
  packageDir = PACKAGE_ROOT,
  argv = process.argv,
  readJson = defaultReadJson,
} = {}) {
  const profileDir =
    (env.DSH_PROFILE_DIR ? String(env.DSH_PROFILE_DIR) : null) ??
    profileDirFromPackageDir(packageDir) ??
    profileDirFromArgv(argv)
  const profile = env.DSH_PROFILE ? String(env.DSH_PROFILE) : profileDir ? basename(profileDir) : null
  /** @type {string[]} */
  const warnings = []
  const install = {
    package_dir: packageDir ?? null,
    profile,
    profile_dir: profileDir,
    dependency: /** @type {string | null} */ (null),
    source: 'unknown',
    warnings,
  }
  if (!profileDir) {
    warnings.push(
      'profile directory is unknown (DSH_PROFILE_DIR is not set and it could not be inferred); ' +
        'cannot tell how this plugin was installed',
    )
    return install
  }
  let manifest
  try {
    manifest = readJson(join(profileDir, 'package.json'))
  } catch (error) {
    warnings.push(`cannot read the profile package.json: ${error.message}`)
    return install
  }
  const spec =
    manifest?.dependencies?.[PLUGIN_PACKAGE] ??
    manifest?.optionalDependencies?.[PLUGIN_PACKAGE] ??
    manifest?.devDependencies?.[PLUGIN_PACKAGE]
  if (!spec || typeof spec !== 'string') {
    warnings.push(`the profile package.json has no ${PLUGIN_PACKAGE} dependency entry`)
    return install
  }
  install.dependency = spec
  install.source = classifyInstallSource(spec)
  if (!INSTALL_SOURCES.has(install.source)) install.source = 'unknown'
  if (install.source === 'local-file' && TEMP_PATH.test(spec)) {
    warnings.push(
      'installed from a temporary directory; that directory may be cleaned up and the plugin will ' +
        'disappear — reinstall from a stable path or a registry version',
    )
  }
  if (install.source === 'unknown') {
    warnings.push(`unrecognized install spec ${JSON.stringify(spec)}; source unknown`)
  }
  return install
}

/** 「dry-run ready (records actions only), xinput slot 0」这类一行后端描述。 */
function controlSummary(control) {
  if (!control || typeof control !== 'object') return null
  const name = control.name ?? control.backend ?? requestedBackend(process.env)
  const state = control.ready === true ? 'ready' : control.ready === false ? 'not ready' : 'readiness unknown'
  let text = `${name} ${state}`
  if (control.detail) text += ` (${control.detail})`
  if (control.xinput_slot != null) text += `, xinput slot ${control.xinput_slot}`
  const warnings = Array.isArray(control.warnings) ? control.warnings.filter(Boolean) : []
  if (warnings.length) text += `, ⚠ ${warnings.join('; ')}`
  return text
}

/** `Fixture Game (hwnd 4242)`。 */
function foregroundSummary(foreground) {
  if (!foreground || typeof foreground !== 'object') return null
  const title = foreground.title ?? 'untitled window'
  return foreground.hwnd == null ? String(title) : `${title} (hwnd ${foreground.hwnd})`
}

/** 目标窗口被遮挡时的 ⚠ 一行（不可用时返回 null）。 */
function occlusionWarning(occluded) {
  if (!occluded || typeof occluded !== 'object' || !occluded.occluded) return null
  const ratio = Number(occluded.occluded_ratio ?? 0)
  const percent = Math.round((Number.isFinite(ratio) ? ratio : 0) * 100)
  const coveredBy = Array.isArray(occluded.covered_by) ? occluded.covered_by[0] : null
  return `⚠ target window is ${percent}% occluded${coveredBy?.title ? ` (mostly by ${coveredBy.title})` : ''}`
}

/**
 * 当前会话选中的 profile（懒加载）。
 *
 * attach 只记 id，真正需要键位/HUD/阈值时才读文件：profile 缺失或坏 JSON 都
 * **不是**工具错误——降级成引擎默认值并返回一行警告，绝不因此让 attach 失败。
 *
 * @param {{ profileId?: string | null }} runtime
 * @param {Record<string, string | undefined>} [env]
 * @returns {{ id: string | null, profile: Record<string, unknown> | null, warning: string | null }}
 */
function runtimeProfile(runtime, env = process.env) {
  const id = runtime.profileId ?? null
  if (!id) return { id: null, profile: null, warning: null }
  try {
    const profile = readProfile(env, id)
    return {
      id,
      profile,
      warning: profile
        ? null
        : `profile ${JSON.stringify(id)} was not found in the profile store; falling back to engine defaults`,
    }
  } catch (error) {
    return {
      id,
      profile: null,
      warning: `profile ${JSON.stringify(id)} could not be loaded (${error.message}); falling back to engine defaults`,
    }
  }
}

/** 引擎自检里的 backend 可能叫 `name`（selftest）或 `backend`（session 的 control）。 */
function normalizeBackend(reported, { reason = null } = {}) {
  const requested = requestedBackend(process.env)
  const base = { name: requested, ready: null, detail: '', xinput_slot: null, warnings: [] }
  if (reported && typeof reported === 'object') {
    return {
      name: String(reported.name ?? reported.backend ?? requested),
      ready: reported.ready === true ? true : reported.ready === false ? false : null,
      detail: reported.detail == null ? '' : String(reported.detail),
      xinput_slot: reported.xinput_slot ?? null,
      warnings: Array.isArray(reported.warnings) ? reported.warnings.map(String) : [],
    }
  }
  if (reason) {
    base.ready = false
    base.detail = reason
  } else {
    base.detail = 'engine did not report a backend'
    if (requested === 'vgamepad') base.warnings = ['engine is too old to probe vgamepad; reinstall the engine to verify the backend']
  }
  return base
}

/** 可选诊断日志：只写隔离环境里给出的路径，默认不落盘。 */
function debugLog(message) {
  const path = process.env.DSH_GAME_BRIDGE_DEBUG_LOG
  if (!path) return
  try {
    appendFileSync(path, `${new Date().toISOString()} ${message}\n`)
  } catch {
    /* 诊断日志失败不能影响主流程 */
  }
}

/**
 * 每次插件装载创建一个运行时。
 * - 引擎懒建、自举串行（bootstrap 内部共享同一个 Promise）；
 * - dispose 时取消安装并杀掉引擎。
 */
function createRuntime() {
  const env = process.env
  const runtime = {
    status: 'idle',
    detail: 'engine not started',
    client: null,
    engineInfo: null,
    error: null,
    /** attach 成功后的目标窗口（给 snapshot 的「是否前台/被遮挡」判断用）。 */
    attachedWindow: null,
    attachedHwnd: null,
    /** 当前会话使用的 profile id（game_memory use / game_attach profile 设置）。 */
    profileId: null,
    bootstrap: createEngineBootstrap({
      env,
      onProgress: (message) => {
        const text = message.split('\n').filter(Boolean).slice(-1)[0] ?? message
        runtime.detail = text
        debugLog(`bootstrap: ${text}`)
      },
    }),
    waitMs: Number(env.DSH_GAME_BRIDGE_WAIT_MS ?? 20_000),
  }

  runtime.start = () => {
    if (runtime.status === 'installing' || runtime.status === 'ready') return
    runtime.status = 'installing'
    runtime.detail = 'installing engine (first run only)'
    debugLog('bootstrap start')
    runtime.bootstrap
      .ensure()
      .then(({ python, cwd, source }) => {
        runtime.engineInfo = { python, cwd }
        runtime.client = new EngineClient({ python, cwd, env, timeoutMs: 30_000 })
        runtime.status = 'ready'
        runtime.detail = `engine ready (${source})`
        debugLog(`bootstrap ready: ${source} ${python}`)
      })
      .catch((error) => {
        runtime.status = 'failed'
        runtime.error = error.message
        runtime.detail = `engine unavailable: ${error.message}`
        debugLog(`bootstrap failed: ${error.message}`)
      })
  }

  /**
   * 引擎崩溃自愈：下一次工具调用时重建客户端（同一份已装好的引擎，不再自举）。
   * 不自动重放上一次请求——attach/act 不是幂等的，重放可能按下两次。
   */
  runtime.recover = () => {
    if (runtime.status !== 'ready' || !runtime.client?.failure || !runtime.engineInfo) return
    debugLog(`engine recovery after: ${runtime.client.failure.split('\n')[0]}`)
    runtime.client.dispose()
    runtime.client = new EngineClient({
      python: runtime.engineInfo.python,
      cwd: runtime.engineInfo.cwd,
      env,
      timeoutMs: 30_000,
    })
  }

  /** 在线性等待上限内等引擎就绪；超时返回当前状态，不抛。 */
  runtime.waitForEngine = (timeoutMs = runtime.waitMs) =>
    new Promise((resolve) => {
      const started = Date.now()
      const tick = () => {
        if (runtime.status === 'ready' || runtime.status === 'failed') return resolve(runtime.status)
        if (Date.now() - started >= timeoutMs) return resolve(runtime.status)
        setTimeout(tick, 200)
      }
      tick()
    })

  runtime.dispose = () => {
    debugLog('runtime dispose')
    runtime.bootstrap.cancel()
    runtime.client?.dispose()
    runtime.status = 'disposed'
  }

  return runtime
}

function engineStatusText(runtime) {
  if (runtime.status === 'ready') return `ready (${runtime.detail})`
  if (runtime.status === 'installing') return `installing (${runtime.detail})`
  if (runtime.status === 'failed') return `failed (${runtime.detail})`
  return runtime.detail
}

/** 取一个就绪的引擎客户端；没就绪就抛人话错误（不静默降级）。 */
async function requireEngine(runtime, waitMs = 20_000) {
  runtime.start()
  await runtime.waitForEngine(waitMs)
  if (runtime.status !== 'ready' || !runtime.client) {
    throw new Error(`game engine is not ready (${engineStatusText(runtime)})`)
  }
  runtime.recover()
  return runtime.client
}

const safetySchema = {
  type: 'object',
  required: true,
  additionalProperties: true,
  properties: {
    allowed: { type: 'boolean', required: true },
    reasons: { type: 'array', items: { type: 'string' } },
    anticheat: { type: 'array', items: { type: 'string' } },
    takeover: { type: 'boolean' },
  },
}

/**
 * 审批闸：只有「真实输出后端」才需要用户点头。
 *
 * dry-run 只记录动作、不碰设备，所以不打扰用户；一旦 `DSH_GAME_BRIDGE_CONTROL`
 * 指向真实后端（vgamepad），attach 这一步会走 DSH 的 user-approval 一次性批准。
 * 没有批准 seam 的部署（headless/CI）会 fail-closed 拒绝——这是期望行为。
 */
function controlApprovalHook(env = process.env) {
  const backend = env.DSH_GAME_BRIDGE_CONTROL || 'dry-run'
  if (backend === 'dry-run') return null
  return async (exec, next) => {
    if (exec?.name !== 'game_attach') return next()
    return {
      kind: 'ask',
      reason: `Allow dsh-game-bridge to attach with real input control (${backend})?`,
      displayReason: {
        en: `dsh-game-bridge wants to attach a window with real input control (${backend}). Approve once to continue.`,
        zh: `dsh-game-bridge 将用真实输入后端（${backend}）绑定窗口，是否允许？`,
      },
    }
  }
}


function selftestTool(runtime) {
  return defineTool({
    name: 'game_selftest',
    description:
      'Report whether the dsh-game-bridge plugin is loaded, its version, the host platform, whether the local ' +
      'capture/OCR engine is ready, which input backend is selected and ready, and how the plugin was installed. ' +
      'Call this before claiming any game capability to the user.',
    parameters: {},
    // 首次调用可能要等引擎自举（下载 uv/装 wheel），给一个宽松的协作超时。
    timeoutMs: 300_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          plugin: { type: 'string', required: true },
          version: { type: 'string', required: true },
          platform: { type: 'string', required: true },
          engine: { type: 'string', required: true },
          engine_ready: { type: 'boolean', required: true },
          detail: { type: 'string' },
          install: { type: 'json' },
          backend: { type: 'json' },
          report: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const head =
          `${value.plugin} ${value.version} on ${value.platform}; engine: ${value.engine}.` +
          `${value.detail ? ` ${value.detail}` : ''}`
        const extras = []
        const backend = controlSummary(value.backend)
        if (backend) extras.push(`backend: ${backend}.`)
        if (value.install) {
          const install = value.install
          const where = install.dependency ? ` (${install.dependency})` : ''
          const profile = install.profile ? ` in profile ${install.profile}` : ''
          const warnings = Array.isArray(install.warnings) ? install.warnings.filter(Boolean) : []
          extras.push(
            `install: ${install.source}${where}${profile}.${warnings.length ? ` ⚠ ${warnings.join('; ')}` : ''}`,
          )
        }
        return [{ type: 'text', text: [head, ...extras].join(' ') }]
      },
    },
    execute: async () => {
      runtime.start()
      const waitMs = Number(process.env.DSH_GAME_BRIDGE_SELFTEST_WAIT_MS ?? 120_000)
      await runtime.waitForEngine(waitMs)
      const base = {
        plugin: 'dsh-game-bridge',
        version: VERSION,
        platform: `${process.platform}-${process.arch}`,
        engine: engineStatusText(runtime),
        engine_ready: runtime.status === 'ready',
      }
      // 安装来源即使在引擎不可用时也有诊断价值（最常见的问题就是装错/装在临时目录）。
      const install = describeInstall({ env: process.env, packageDir: PACKAGE_ROOT })
      if (runtime.status !== 'ready' || !runtime.client) {
        return { ...base, install, backend: normalizeBackend(null, { reason: engineStatusText(runtime) }) }
      }
      let pong
      try {
        pong = await runtime.client.request('ping', {}, { timeoutMs: 8_000 })
      } catch (error) {
        return {
          ...base,
          engine_ready: false,
          detail: `engine unreachable: ${error.message}`,
          install,
          backend: normalizeBackend(null, { reason: 'engine unreachable' }),
        }
      }
      let detail = `engine ${pong.version} answered (engine core ${ENGINE_VERSION})`
      let report = null
      try {
        report = await runtime.client.request(
          'selftest',
          // vgamepad 后端才真的去建一块虚拟手柄来验证（不按键）；其它后端不碰设备。
          { capture: false, probe_devices: requestedBackend(process.env) === 'vgamepad' },
          { timeoutMs: 60_000 },
        )
      } catch (error) {
        detail += `; engine selftest failed: ${error.message}`
      }
      const backend = normalizeBackend(report?.backend)
      return {
        ...base,
        engine_ready: true,
        detail,
        install,
        backend,
        ...(report ? { report } : {}),
      }
    },
  })
}

function snapshotTool(ctx, runtime) {
  return defineTool({
    name: 'game_snapshot',
    description:
      'Return one frame of what the game bridge can see: a screenshot as an image plus any OCR text found in it. ' +
      'When the local engine is unavailable this returns a synthetic frame and says why.',
    parameters: {},
    timeoutMs: 300_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          width: { type: 'number', required: true },
          height: { type: 'number', required: true },
          source: { type: 'string', required: true },
          note: { type: 'string' },
          region: { type: 'json' },
          foreground: { type: 'json' },
          occluded: { type: 'json' },
          attachment: {
            type: 'object',
            required: true,
            additionalProperties: true,
            properties: {
              attachmentId: { type: 'string', required: true },
              mediaType: { type: 'string', required: true },
              bytes: { type: 'number', required: true },
              width: { type: 'number', required: true },
              height: { type: 'number', required: true },
            },
          },
        },
      },
      render: (_args, value) => {
        const head = `Frame ${value.width}x${value.height} (${value.source}).${value.note ? ` ${value.note}` : ''}`
        const extras = []
        const foreground = foregroundSummary(value.foreground)
        if (foreground) extras.push(`Foreground: ${foreground}.`)
        // attach 过的目标窗口现在不在前台 = 后续真实输入会送错进程，必须显式提醒。
        if (value.foreground && runtime.attachedHwnd != null && Number(value.foreground.hwnd) !== runtime.attachedHwnd) {
          extras.push(`⚠ the attached window is not in the foreground (now: ${value.foreground.title ?? 'unknown'}).`)
        }
        const occluded = occlusionWarning(value.occluded)
        if (occluded) extras.push(`${occluded}.`)
        else if (value.occluded?.available) {
          const ratio = Number(value.occluded.occluded_ratio ?? 0)
          const percent = Math.round((Number.isFinite(ratio) ? ratio : 0) * 100)
          extras.push(`Occlusion: ${percent}% covered.`)
        }
        return [
          { type: 'text', text: [head, ...extras].join(' ') },
          { type: 'image', attachment: value.attachment },
        ]
      },
    },
    execute: async () => {
      runtime.start()
      await runtime.waitForEngine(Number(process.env.DSH_GAME_BRIDGE_SNAPSHOT_WAIT_MS ?? 20_000))
      if (runtime.status === 'ready' && runtime.client) {
        try {
          const frame = await runtime.client.request('snapshot', { ocr: true, max_width: 1280 })
          const bytes = new Uint8Array(Buffer.from(frame.png_b64, 'base64'))
          const ref = await ctx.attachments.saveImage({ data: bytes, mediaType: 'image/png' })
          const texts = (frame.ocr ?? []).slice(0, 12).map((line) => `${line.text} (${line.score})`)
          const note = texts.length ? `OCR: ${texts.join(' | ')}` : 'OCR: no text found'
          return {
            width: ref.width,
            height: ref.height,
            source: frame.region ? 'window via dsh-game-core' : 'screen via dsh-game-core',
            note,
            ...(frame.region ? { region: frame.region } : {}),
            ...(frame.foreground ? { foreground: frame.foreground } : {}),
            ...(frame.occluded ? { occluded: frame.occluded } : {}),
            attachment: ref,
          }
        } catch (error) {
          const ref = await ctx.attachments.saveImage({
            data: new Uint8Array(SYNTHETIC_FRAME),
            mediaType: 'image/png',
          })
          return {
            width: ref.width,
            height: ref.height,
            source: 'synthetic fallback',
            note: `engine failed: ${error.message}`,
            attachment: ref,
          }
        }
      }
      const ref = await ctx.attachments.saveImage({
        data: new Uint8Array(SYNTHETIC_FRAME),
        mediaType: 'image/png',
      })
      return {
        width: ref.width,
        height: ref.height,
        source: 'synthetic fallback',
        note: `engine not ready (${engineStatusText(runtime)}); no screen captured`,
        attachment: ref,
      }
    },
  })
}

/** 当前后端支持哪些按钮/按键——省得模型瞎猜键名。 */
function controlsTool(runtime) {
  return defineTool({
    name: 'game_controls',
    description:
      'List the button/key names accepted by the current control backend (dry-run, vgamepad or keyboard), plus a ' +
      'one-line note. Call this before game_act / game_plan when you are unsure which names are valid.',
    parameters: {},
    timeoutMs: 60_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          backend: { type: 'string', required: true },
          buttons: { type: 'array', required: true, items: { type: 'string' } },
          note: { type: 'string', required: true },
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `Controls (backend ${value.backend}): ${value.buttons.join(', ')}. ${value.note}.`,
        },
      ],
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      return client.request('controls', {}, { timeoutMs: 15_000 })
    },
  })
}

/** 列出可见窗口：让模型自己发现该 attach 哪个，而不是靠用户报标题。 */
function windowsTool(runtime) {
  return defineTool({
    name: 'game_windows',
    description:
      'List visible top-level windows (title, process, size) so you can pick the right game to attach to. ' +
      'Read-only; it does not focus or capture anything.',
    parameters: {},
    timeoutMs: 60_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          count: { type: 'number', required: true },
          windows: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: true,
              properties: {
                title: { type: 'string', required: true },
                process: { type: 'string' },
                width: { type: 'number', required: true },
                height: { type: 'number', required: true },
              },
            },
          },
        },
      },
      render: (_args, value) => {
        const lines = value.windows
          .slice(0, 12)
          .map((window) => `${window.title} (${window.process ?? 'unknown'}, ${window.width}x${window.height})`)
        return [
          {
            type: 'text',
            text: lines.length
              ? `Visible windows (${value.count}): ${lines.join(' | ')}`
              : 'No visible top-level windows found.',
          },
        ]
      },
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      return client.request('windows', { limit: 40 }, { timeoutMs: 15_000 })
    },
  })
}


/** 帧差分事件：不截图、不 OCR 的廉价「刚才画面变了没有」。 */
function eventsTool(runtime) {
  return defineTool({
    name: 'game_events',
    description:
      'Cheap frame-difference event since the previous game_events call: baseline | static | changed | scene_cut, ' +
      'with mean_diff and changed_ratio. No screenshot and no OCR, so it is much cheaper than game_snapshot. ' +
      'Thresholds are not calibrated per game; treat the label as a hint and the numbers as ground truth.',
    parameters: {},
    timeoutMs: 60_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          event: { type: 'string', required: true },
          mean_diff: { type: 'number', required: true },
          changed_ratio: { type: 'number', required: true },
          elapsed_ms: { type: 'json' },
          width: { type: 'number', required: true },
          height: { type: 'number', required: true },
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `Frame event: ${value.event} (mean_diff=${value.mean_diff}, changed_ratio=${value.changed_ratio}` +
            `${value.elapsed_ms == null ? '' : `, after ${value.elapsed_ms}ms`}).`,
        },
      ],
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      return client.request('events', {}, { timeoutMs: 15_000 })
    },
  })
}

/** 绑定一个目标窗口。绑定是「用户授权」的动作，后续 act 才可能放行。 */
function attachTool(runtime) {
  return defineTool({
    name: 'game_attach',
    description:
      'Attach the bridge to a game window. This is the user-authorization step: no act is executed before attach. ' +
      'Returns the safety state (anti-cheat detection, takeover latch). The optional profile id (from game_memory) ' +
      'selects key/HUD/threshold defaults for game_state and game_policy; a missing profile never fails the attach.',
    parameters: {
      window: { type: 'string', description: 'Window title or a short identifier of the target game.' },
      profile: {
        type: 'string',
        description:
          'Optional profile id in the local profile store (see game_memory). Omit to keep the current profile.',
      },
    },
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          attached: {
            type: 'object',
            required: true,
            additionalProperties: true,
            properties: { window: { type: 'string', required: true } },
          },
          backend: { type: 'string', required: true },
          safety: safetySchema,
          control: { type: 'json' },
          foreground: { type: 'json' },
          // 只描述「选了哪个 profile、文件在不在」；缺失时 attach 仍然成功。
          profile: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const parts = [`Attached to ${value.attached.window} (control backend: ${value.backend}).`]
        const control = controlSummary(value.control)
        if (control) parts.push(`Control: ${control}.`)
        const foreground = foregroundSummary(value.foreground)
        if (foreground) parts.push(`Foreground: ${foreground}.`)
        if (value.profile) {
          const state = value.profile.found ? 'loaded' : `⚠ ${value.profile.warning ?? 'not found'}`
          parts.push(`Profile: ${value.profile.id} (${state}).`)
        }
        parts.push(
          `Safety: ${
            value.safety.allowed ? 'allowed' : `blocked — ${(value.safety.reasons ?? []).join('; ')}`
          }.`,
        )
        return [{ type: 'text', text: parts.join(' ') }]
      },
    },
    execute: async (args) => {
      const client = await requireEngine(runtime)
      // profile 只影响视觉/策略默认值，不参与绑定本身：先 attach，再解析 id。
      const requested = args.profile == null ? '' : String(args.profile).trim()
      const result = await client.request(
        'attach',
        { window: args.window ?? 'unspecified', ...(requested ? { profile: requested } : {}) },
        { timeoutMs: 20_000 },
      )
      // 记住目标窗口：snapshot 要据此判断「目标是否还在前台 / 被遮挡」。
      runtime.attachedWindow = result?.attached?.window ?? null
      runtime.attachedHwnd = result?.attached?.hwnd ?? null
      if (!requested) return result
      let profile
      try {
        const id = validateProfileId(requested)
        runtime.profileId = id
        const loaded = runtimeProfile(runtime)
        profile = { id, found: loaded.profile != null, warning: loaded.warning }
      } catch (error) {
        // 非法 id 只告警：绑定已经成功，用引擎默认值继续。
        profile = { id: requested, found: false, warning: error.message }
      }
      return { ...result, profile }
    },
  })
}

/** 单步动作。默认 dry-run：只记录，不碰设备。 */
function actTool(runtime) {
  return defineTool({
    name: 'game_act',
    description:
      'Press one gamepad button for a short duration after game_attach. The engine refuses when an anti-cheat is ' +
      'running or after the takeover hotkey (F12). The default backend is dry-run: ' +
      'it records the action instead of injecting input. Real input backends refuse when the attached window is ' +
      'not in the foreground, because injected input goes to whatever window has focus.',
    parameters: {
      button: {
        type: 'string',
        description:
          'Gamepad button (A/B/X/Y/START/DPAD_*) for the vgamepad backend, or keyboard key (W/A/S/D/SPACE/ENTER/ESC/ARROWS) for the keyboard backend.',
      },
      duration_ms: { type: 'number', description: 'Hold duration in milliseconds (1..2000, default 80).' },
    },
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          action: {
            type: 'object',
            required: true,
            additionalProperties: true,
            properties: {
              backend: { type: 'string', required: true },
              button: { type: 'string', required: true },
              duration_ms: { type: 'number', required: true },
              dry_run: { type: 'boolean', required: true },
            },
          },
          safety: safetySchema,
          attached: {
            type: 'object',
            additionalProperties: true,
            properties: { window: { type: 'string' } },
          },
          actions_total: { type: 'number', required: true },
          delivery: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const head =
          `${value.action.dry_run ? 'DRY-RUN: would press' : 'Pressed'} ${value.action.button} for ${
            value.action.duration_ms
          }ms (backend: ${value.action.backend}); total actions: ${value.actions_total}.`
        const extras = []
        if (value.delivery) {
          const delivery = value.delivery
          if (delivery.foreground === true) extras.push('Delivery: target window is in the foreground.')
          else if (delivery.foreground === false) {
            extras.push(`Delivery: target window is NOT in the foreground${delivery.title ? ` (now: ${delivery.title})` : ''}.`)
          } else if (delivery.checked === false) {
            extras.push('Delivery: foreground not checked (no attached window handle).')
          } else {
            extras.push('Delivery: foreground state unknown.')
          }
        }
        return [{ type: 'text', text: [head, ...extras].join(' ') }]
      },
    },
    execute: async (args) => {
      const client = await requireEngine(runtime)
      return client.request(
        'act',
        { button: args.button ?? 'A', duration_ms: args.duration_ms ?? 80 },
        { timeoutMs: 20_000 },
      )
    },
  })
}

const planSchema = {
  type: 'object',
  required: true,
  additionalProperties: true,
  properties: {
    id: { type: 'string', required: true },
    mode: { type: 'string', required: true },
    button: { type: 'string', required: true },
    duration_ms: { type: 'number', required: true },
    status: { type: 'string', required: true },
    ticks: { type: 'number' },
    hz: { type: 'number' },
    elapsed_ms: { type: 'number' },
    escapes: { type: 'number' },
    last_event: { type: 'json' },
  },
}

/** 启动本地 20 Hz 闭环：模型只给目标，逐拍执行留在引擎里。 */
function planTool(runtime) {
  return defineTool({
    name: 'game_plan',
    description:
      'Start a local closed loop (about 20 Hz) that drives one gamepad direction for a bounded duration. ' +
      'Modes: hold (keep it pressed), tap (repeated short presses), advance (keep walking; when the screen stops ' +
      'changing for stuck_after_ms, briefly sidestep and continue — a generic "walk toward something" primitive). ' +
      'The loop re-checks the safety gate every tick, so anti-cheat detection or the takeover hotkey stops it ' +
      'immediately. Real input backends refuse when the attached window is not in the foreground and abort the ' +
      'loop if it loses the foreground. Prefer this over repeated game_act calls.',
    parameters: {
      button: {
        type: 'string',
        description: 'Gamepad direction/button (DPAD_RIGHT/A...) or keyboard key (W/A/S/D/ARROWS...) depending on the control backend.',
      },
      mode: { type: 'string', description: 'hold (default), tap, or advance.' },
      duration_ms: { type: 'number', description: 'How long the loop may run (100..120000, default 1000).' },
      tap_interval_ms: { type: 'number', description: 'For tap mode: interval between presses (20..1000, default 150).' },
      stuck_after_ms: { type: 'number', description: 'For advance: how long the screen must stay static before sidestepping (200..10000, default 800).' },
      escape_tap_ms: { type: 'number', description: 'For advance: sidestep press duration (30..1000, default 150).' },
    },
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { plan: planSchema, safety: safetySchema, control: { type: 'json' }, foreground: { type: 'json' } },
      },
      render: (_args, value) => {
        const head =
          `Plan ${value.plan.id}: ${value.plan.mode} ${value.plan.button} for ${value.plan.duration_ms}ms ` +
          `(status: ${value.plan.status}${value.plan.escapes ? `, escapes: ${value.plan.escapes}` : ''}).`
        const extras = []
        const control = controlSummary(value.control)
        if (control) extras.push(`Control: ${control}.`)
        const foreground = foregroundSummary(value.foreground)
        if (foreground) extras.push(`Foreground: ${foreground}.`)
        return [{ type: 'text', text: [head, ...extras].join(' ') }]
      },
    },
    execute: async (args) => {
      const client = await requireEngine(runtime)
      return client.request(
        'plan',
        {
          button: args.button ?? 'A',
          mode: args.mode ?? 'hold',
          duration_ms: args.duration_ms ?? 1000,
          tap_interval_ms: args.tap_interval_ms ?? 150,
          stuck_after_ms: args.stuck_after_ms ?? 800,
          escape_tap_ms: args.escape_tap_ms ?? 150,
        },
        { timeoutMs: 20_000 },
      )
    },
  })
}

/** 查询闭环进度与安全状态。 */
function statusTool(runtime) {
  return defineTool({
    name: 'game_status',
    description:
      'Report the current attach state, control backend, safety verdict, action count and closed-loop progress ' +
      '(ticks, measured Hz, stop reason if it aborted).',
    parameters: {},
    timeoutMs: 60_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          attached: { type: 'json' },
          backend: { type: 'string', required: true },
          safety: safetySchema,
          actions_total: { type: 'number', required: true },
          last_action: { type: 'json' },
          plan: { type: 'json' },
          audit: { type: 'json' },
          control: { type: 'json' },
          foreground: { type: 'json' },
          policy: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const plan = value.plan
        const planText = plan
          ? `plan ${plan.status} (${plan.mode} ${plan.button}; ticks=${plan.ticks ?? 0}, hz=${plan.hz ?? 0}` +
            `${plan.stop_reason ? `, stopped: ${plan.stop_reason}` : ''})`
          : 'no plan'
        const policy = value.policy
        const policyText = policy
          ? `policy ${policy.running ? 'running' : 'stopped'} (ticks=${policy.ticks ?? 0}, hz=${policy.hz ?? 0}` +
            `${policy.stop_reason ? `, stop_reason: ${policy.stop_reason}` : ''})`
          : 'no policy'
        const extras = []
        const control = controlSummary(value.control)
        if (control) extras.push(`Control: ${control}.`)
        const foreground = foregroundSummary(value.foreground)
        if (foreground) extras.push(`Foreground: ${foreground}.`)
        // `backend: <backend>;` 必须逐字保留：集成测试断言这一串。
        const text =
          `Attached: ${value.attached?.window ?? 'none'}; backend: ${value.backend}; ${planText}; ` +
          `${policyText}; safety: ${value.safety.allowed ? 'allowed' : `blocked — ${(value.safety.reasons ?? []).join('; ')}`}.` +
          `${extras.length ? ` ${extras.join(' ')}` : ''}`
        return [{ type: 'text', text }]
      },
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      const result = await client.request('status', {}, { timeoutMs: 15_000 })
      // 引擎重启（崩溃自愈）后 attach 状态以引擎为准，别拿旧 hwnd 做前台判断。
      if (result && 'attached' in result) {
        runtime.attachedWindow = result.attached?.window ?? null
        runtime.attachedHwnd = result.attached?.hwnd ?? null
      }
      return result
    },
  })
}

/** 通用世界状态：视觉保底，profile 只提供 HUD 框/场景关键词/颜色阈值。 */
function stateTool(runtime) {
  return defineTool({
    name: 'game_state',
    description:
      'Read one frame and return the generic WorldState for the attached game: scene, player HP/position, ' +
      'visible threats/parry windows (normalized 0..1 coordinates), UI text/prompt and the active profile. ' +
      'Vision-based fallback that never requires cheat offsets; the optional profile (see game_memory) only ' +
      'supplies HUD boxes, scene keywords and color thresholds. Warnings report a missing profile, an occluded ' +
      'target window or a lost foreground.',
    parameters: {},
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          state: { type: 'json', required: true },
          profile: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const state = value.state && typeof value.state === 'object' ? value.state : {}
        const player = state.player && typeof state.player === 'object' ? state.player : {}
        const hp =
          player.hp == null
            ? 'unknown'
            : player.max_hp == null
              ? String(player.hp)
              : `${player.hp}/${player.max_hp}`
        const entities = Array.isArray(state.entities) ? state.entities.length : 0
        const prompt = state.ui?.prompt ? String(state.ui.prompt) : 'none'
        const scene = state.scene ? String(state.scene) : 'unknown'
        const extras = []
        if (value.profile?.warning) extras.push(`⚠ ${value.profile.warning}.`)
        if (value.profile?.id && !value.profile.warning) extras.push(`Profile: ${value.profile.id}.`)
        const foreground = foregroundSummary(state.foreground)
        if (foreground) extras.push(`Foreground: ${foreground}.`)
        if (
          state.foreground &&
          runtime.attachedHwnd != null &&
          Number(state.foreground.hwnd) !== runtime.attachedHwnd
        ) {
          extras.push(`⚠ the attached window is not in the foreground (now: ${state.foreground.title ?? 'unknown'}).`)
        }
        const occluded = occlusionWarning(state.occluded)
        if (occluded) extras.push(`${occluded}.`)
        return [
          {
            type: 'text',
            text: [`scene=${scene}, hp=${hp}, entities=${entities}, prompt=${prompt}.`, ...extras].join(' '),
          },
        ]
      },
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      // profile 懒加载：缺失/坏 JSON 只降级成默认值，不打断状态读取。
      const { id, profile, warning } = runtimeProfile(runtime)
      const state = await client.request('state', { profile }, { timeoutMs: 30_000 })
      return {
        state,
        ...(id || warning ? { profile: { id, found: profile != null, warning } } : {}),
      }
    },
  })
}

/**
 * 本地反射策略：引擎里 60 Hz 的闭环（持枪/前进/闪避/卡住脱困），
 * 只按 profile 里列出的键，安全闸每拍复查。
 */
function policyTool(runtime) {
  const policyText = (action, policy) => {
    const head = `Policy ${action}:`
    if (!policy || typeof policy !== 'object') return `${head} not running.`
    const bits = [`running=${policy.running === true ? 'yes' : 'no'}`]
    if (policy.ticks != null) bits.push(`ticks=${policy.ticks}`)
    if (policy.hz != null) bits.push(`hz=${policy.hz}`)
    if (policy.actions != null) bits.push(`actions=${policy.actions}`)
    if (policy.escapes != null) bits.push(`escapes=${policy.escapes}`)
    if (policy.scene) bits.push(`scene=${policy.scene}`)
    if (policy.last_entities != null) bits.push(`entities=${policy.last_entities}`)
    if (policy.stop_reason) bits.push(`stop_reason=${policy.stop_reason}`)
    return `${head} ${bits.join(', ')}.`
  }
  return defineTool({
    name: 'game_policy',
    description:
      'Control the local 60 Hz policy loop that plays from a profile: start, stop or read its status. ' +
      'On start the profile from game_memory/game_attach supplies hold/advance/dodge/stuck keys; the loop ' +
      're-checks the safety gate every tick (anti-cheat or the takeover hotkey stops it immediately), dodges ' +
      'threats inside the profile radius and probes keys when the screen goes static. Prefer this over ' +
      'repeated game_plan calls for continuous play.',
    parameters: {
      action: {
        type: 'string',
        required: true,
        enum: ['start', 'stop', 'status'],
        description: 'start | stop | status.',
      },
    },
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          action: { type: 'string', required: true },
          policy: { type: 'json' },
          profile: { type: 'json' },
        },
      },
      render: (_args, value) => {
        const extras = []
        if (value.profile?.warning) extras.push(`⚠ ${value.profile.warning}.`)
        return [{ type: 'text', text: [policyText(value.action, value.policy), ...extras].join(' ') }]
      },
    },
    execute: async (args) => {
      const client = await requireEngine(runtime)
      const action = String(args.action ?? '').trim().toLowerCase()
      if (action === 'start') {
        const { id, profile, warning } = runtimeProfile(runtime)
        const result = await client.request('policy_start', { profile }, { timeoutMs: 30_000 })
        return {
          action: 'start',
          policy: result?.policy ?? null,
          ...(id || warning ? { profile: { id, found: profile != null, warning } } : {}),
        }
      }
      if (action === 'stop') {
        const result = await client.request('policy_stop', {}, { timeoutMs: 20_000 })
        return { action: 'stop', policy: result?.policy ?? null }
      }
      if (action !== 'status') {
        throw new Error(`unknown game_policy action ${JSON.stringify(action)}; expected start, stop or status`)
      }
      // 策略状态挂在通用 status 上：一次调用同时拿到 attach/safety/policy。
      const result = await client.request('status', {}, { timeoutMs: 15_000 })
      return { action: 'status', policy: result?.policy ?? null }
    },
  })
}

/** 用户 profile 存储：游戏键位/HUD/阈值等差异都放这里，引擎保持游戏无关。 */
function memoryTool(runtime) {
  return defineTool({
    name: 'game_memory',
    description:
      'Manage local game profiles (JSON: controls, hud, scene, combat, colors) used by game_state/game_policy. ' +
      'Actions: list | get | save | delete | use. `use` makes a profile active for the current session (same as ' +
      'game_attach profile). Profiles live in the plugin cache directory; save validates the id and JSON and ' +
      'never writes outside that directory. Public-safe data only: no memory offsets or cheat tables.',
    parameters: {
      action: {
        type: 'string',
        required: true,
        enum: ['list', 'get', 'save', 'delete', 'use'],
        description: 'list | get | save | delete | use.',
      },
      id: { type: 'string', description: 'Profile id (1..64 chars from [A-Za-z0-9._-]).' },
      data: { type: 'json', description: 'For save: the profile JSON object.' },
    },
    timeoutMs: 30_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { result: { type: 'json', required: true } },
      },
      render: (_args, value) => {
        const result = value.result && typeof value.result === 'object' ? value.result : {}
        const parts = []
        const warnings = []
        if (Array.isArray(result.errors)) {
          for (const error of result.errors) warnings.push(`⚠ ${error.id}: ${error.error}`)
        }
        switch (result.action) {
          case 'list': {
            const profiles = Array.isArray(result.profiles) ? result.profiles : []
            if (!profiles.length) parts.push('No profiles saved.')
            else {
              const names = profiles.map((entry) => (entry.name ? `${entry.id} (${entry.name})` : entry.id))
              parts.push(`Profiles (${profiles.length}): ${names.join(', ')}.`)
            }
            break
          }
          case 'get': {
            parts.push(
              result.found
                ? `Profile ${result.id}: found${result.profile?.name ? ` (${result.profile.name})` : ''}.`
                : `Profile ${result.id}: not found.`,
            )
            break
          }
          case 'save':
            parts.push(`Saved profile ${result.id} (${result.bytes} bytes).`)
            break
          case 'delete':
            parts.push(
              result.deleted ? `Deleted profile ${result.id}.` : `Profile ${result.id} was not in the store.`,
            )
            break
          case 'use': {
            parts.push(`Active profile: ${result.id}.`)
            if (result.warning) warnings.push(`⚠ ${result.warning}`)
            break
          }
          default:
            parts.push(`Profile store action ${result.action}.`)
        }
        return [{ type: 'text', text: [parts.join(' '), ...warnings].filter(Boolean).join(' ') }]
      },
    },
    execute: async (args) => {
      const action = String(args.action ?? '').trim().toLowerCase()
      const env = process.env
      const requireId = () => validateProfileId(args.id)
      switch (action) {
        case 'list': {
          const listing = listProfiles(env)
          return { result: { action, dir: listing.dir, profiles: listing.profiles, errors: listing.errors } }
        }
        case 'get': {
          const id = requireId()
          const profile = readProfile(env, id)
          return { result: { action, id, found: profile != null, profile } }
        }
        case 'save': {
          const id = requireId()
          const data = args.data
          if (!data || typeof data !== 'object' || Array.isArray(data)) {
            throw new Error('game_memory save needs data: a JSON object describing the profile')
          }
          const written = writeProfile(env, id, data)
          return { result: { action, id, saved: true, bytes: written.bytes } }
        }
        case 'delete': {
          const id = requireId()
          const removed = deleteProfile(env, id)
          return { result: { action, id, deleted: removed.deleted } }
        }
        case 'use': {
          const id = requireId()
          runtime.profileId = id
          let found = false
          let warning = null
          try {
            found = readProfile(env, id) != null
          } catch (error) {
            warning = error.message
          }
          if (!found && !warning) {
            warning = `profile ${JSON.stringify(id)} was not found; it will be used if you save it later`
          }
          return { result: { action, id, active: true, found, warning } }
        }
        default:
          throw new Error(`unknown game_memory action ${JSON.stringify(action)}; expected list, get, save, delete or use`)
      }
    },
  })
}

/** 停手：释放所有按键并解除绑定。越容易调用越好。 */
function stopTool(runtime) {
  return defineTool({
    name: 'game_stop',
    description: 'Stop any running plan, release every held button and detach from the game. Call this whenever the user asks to stop.',
    parameters: {},
    timeoutMs: 60_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          stopped: { type: 'boolean', required: true },
          actions_total: { type: 'number', required: true },
          plan: { type: 'json' },
        },
      },
      render: (_args, value) => [
        { type: 'text', text: `Stopped; total actions this session: ${value.actions_total}.` },
      ],
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      const result = await client.request('stop', {}, { timeoutMs: 15_000 })
      runtime.attachedWindow = null
      runtime.attachedHwnd = null
      return result
    },
  })
}

/** Cordis 插件入口。装载即开始自举；卸载时取消安装并杀引擎。 */
export function apply(ctx) {
  const runtime = createRuntime()
  runtime.start()
  ctx.tools.register(selftestTool(runtime))
  ctx.tools.register(snapshotTool(ctx, runtime))
  ctx.tools.register(windowsTool(runtime))
  ctx.tools.register(eventsTool(runtime))
  ctx.tools.register(controlsTool(runtime))
  ctx.tools.register(attachTool(runtime))
  ctx.tools.register(actTool(runtime))
  ctx.tools.register(planTool(runtime))
  ctx.tools.register(statusTool(runtime))
  ctx.tools.register(stopTool(runtime))
  ctx.tools.register(stateTool(runtime))
  ctx.tools.register(policyTool(runtime))
  ctx.tools.register(memoryTool(runtime))
  const approvalHook = controlApprovalHook()
  if (approvalHook && typeof ctx.on === 'function') ctx.on('tools/pre-execute', approvalHook)
  if (typeof ctx.on === 'function') ctx.on('dispose', () => runtime.dispose())
}



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
import { defineTool } from '@deepseek-ai/dsh-tools'
import { EngineClient } from './engine.js'
import { createEngineBootstrap, ENGINE_VERSION } from './bootstrap.js'

export const name = 'dsh-game-bridge'

/** 依赖的宿主服务：工具注册表 + 图片附件存储。缺任一服务插件不会激活。 */
export const inject = ['tools', 'attachments']

const VERSION = '0.0.1'
const SYNTHETIC_FRAME = readFileSync(new URL('./frames/synthetic-frame.png', import.meta.url))

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
    error: null,
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

function selftestTool(runtime) {
  return defineTool({
    name: 'game_selftest',
    description:
      'Report whether the dsh-game-bridge plugin is loaded, its version, the host platform, and whether the local ' +
      'capture/OCR engine is ready. Call this before claiming any game capability to the user.',
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
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `${value.plugin} ${value.version} on ${value.platform}; engine: ${value.engine}.${value.detail ? ` ${value.detail}` : ''}`,
        },
      ],
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
      if (runtime.status !== 'ready' || !runtime.client) return base
      try {
        const pong = await runtime.client.request('ping', {}, { timeoutMs: 8_000 })
        return { ...base, engine_ready: true, detail: `engine ${pong.version} answered (engine core ${ENGINE_VERSION})` }
      } catch (error) {
        return { ...base, engine_ready: false, detail: `engine unreachable: ${error.message}` }
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
      render: (_args, value) => [
        {
          type: 'text',
          text: `Frame ${value.width}x${value.height} (${value.source}).${value.note ? ` ${value.note}` : ''}`,
        },
        { type: 'image', attachment: value.attachment },
      ],
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
          return { width: ref.width, height: ref.height, source: 'screen via dsh-game-core', note, attachment: ref }
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

/** Cordis 插件入口。装载即开始自举；卸载时取消安装并杀引擎。 */
export function apply(ctx) {
  const runtime = createRuntime()
  runtime.start()
  ctx.tools.register(selftestTool(runtime))
  ctx.tools.register(snapshotTool(ctx, runtime))
  if (typeof ctx.on === 'function') ctx.on('dispose', () => runtime.dispose())
}

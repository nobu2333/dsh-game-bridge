/**
 * dsh-game-bridge —— 插件入口（M1：接上真实抓屏 + OCR）。
 *
 * 工具面保持「目标级」：M1 只有自检与看一眼；`attach` / `plan` / `stop`
 * 在 M2 随「手 + 20 Hz 闭环」一起加。设计约束见 docs/DESIGN.md。
 *
 * 引擎就绪前（或引擎报错时）截图降级为合成帧，并在结果里写明原因——
 * 绝不假装自己看见了屏幕。
 */
import { readFileSync, appendFileSync } from 'node:fs'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { EngineClient, resolveEngineConfig } from './engine.js'

export const name = 'dsh-game-bridge'

/** 依赖的宿主服务：工具注册表 + 图片附件存储。缺任一服务插件不会激活。 */
export const inject = ['tools', 'attachments']

const VERSION = '0.0.1'
const SYNTHETIC_FRAME = readFileSync(new URL('./frames/synthetic-frame.png', import.meta.url))

/** 可选诊断日志：只写进程隔离环境里给出的路径，默认不落盘。 */
function debugLog(message) {
  const path = process.env.DSH_GAME_BRIDGE_DEBUG_LOG
  if (!path) return
  try {
    appendFileSync(path, `${new Date().toISOString()} ${message}\n`)
  } catch {
    /* 诊断日志失败不能影响主流程 */
  }
}

/** 每次插件装载创建一个运行时：引擎懒启动，dispose 时整棵杀掉。 */
function createRuntime() {
  const config = resolveEngineConfig()
  const engine = config ? new EngineClient(config) : null
  debugLog(`runtime created; engine=${config ? 'configured' : 'off'}`)
  return {
    config,
    engine,
    dispose() {
      debugLog('runtime dispose: killing engine if any')
      engine?.dispose()
      debugLog('runtime dispose: done')
    },
  }
}

function engineStatus(runtime) {
  if (!runtime.config) return 'not configured (set DSH_GAME_BRIDGE_PYTHON to an engine-enabled Python)'
  return `configured (${runtime.config.python})`
}

function selftestTool(runtime) {
  return defineTool({
    name: 'game_selftest',
    description:
      'Report whether the dsh-game-bridge plugin is loaded, its version, the host platform, and whether the local ' +
      'capture/OCR engine is reachable. Call this before claiming any game capability to the user.',
    parameters: {},
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
      const base = {
        plugin: 'dsh-game-bridge',
        version: VERSION,
        platform: `${process.platform}-${process.arch}`,
        engine: engineStatus(runtime),
        engine_ready: false,
      }
      if (!runtime.engine) return base
      try {
        const pong = await runtime.engine.request('ping', {}, { timeoutMs: 8_000 })
        return { ...base, engine_ready: true, detail: `engine ${pong.version} answered` }
      } catch (error) {
        return { ...base, detail: `engine unreachable: ${error.message}` }
      }
    },
  })
}

function snapshotTool(ctx, runtime) {
  return defineTool({
    name: 'game_snapshot',
    description:
      'Return one frame of what the game bridge can see: a screenshot as an image plus any OCR text found in it. ' +
      'When the local engine is unavailable this returns a synthetic frame and says so in the text.',
    parameters: {},
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
      if (runtime.engine) {
        try {
          const frame = await runtime.engine.request('snapshot', { ocr: true, max_width: 1280 })
          const bytes = new Uint8Array(Buffer.from(frame.png_b64, 'base64'))
          const ref = await ctx.attachments.saveImage({ data: bytes, mediaType: 'image/png' })
          const texts = (frame.ocr ?? []).slice(0, 12).map((line) => `${line.text} (${line.score})`)
          const note = texts.length ? `OCR: ${texts.join(' | ')}` : 'OCR: no text found'
          return { width: ref.width, height: ref.height, source: 'screen via dsh-game-core', note, attachment: ref }
        } catch (error) {
          // 引擎挂了：降级合成帧，并把原因写进结果，让模型和用户都知道真相。
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
        source: 'synthetic M0 frame',
        note: 'no engine configured, so no screen is captured',
        attachment: ref,
      }
    },
  })
}

/** Cordis 插件入口。注册返回的 disposer 由宿主管；引擎在 dispose 时被杀。 */
export function apply(ctx) {
  const runtime = createRuntime()
  ctx.tools.register(selftestTool(runtime))
  ctx.tools.register(snapshotTool(ctx, runtime))
  if (typeof ctx.on === 'function') ctx.on('dispose', () => runtime.dispose())
}

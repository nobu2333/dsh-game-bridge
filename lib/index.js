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
    engineInfo: null,
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
    idle_seconds: { type: 'number' },
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
          region: { type: 'json' },
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
          return {
            width: ref.width,
            height: ref.height,
            source: frame.region ? 'window via dsh-game-core' : 'screen via dsh-game-core',
            note,
            ...(frame.region ? { region: frame.region } : {}),
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
      'Returns the safety state (anti-cheat detection, whether a human is present, takeover latch).',
    parameters: {
      window: { type: 'string', description: 'Window title or a short identifier of the target game.' },
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
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `Attached to ${value.attached.window} (control backend: ${value.backend}). Safety: ${
            value.safety.allowed ? 'allowed' : `blocked — ${(value.safety.reasons ?? []).join('; ')}`
          }.`,
        },
      ],
    },
    execute: async (args) => {
      const client = await requireEngine(runtime)
      return client.request('attach', { window: args.window ?? 'unspecified' }, { timeoutMs: 20_000 })
    },
  })
}

/** 单步动作。默认 dry-run：只记录，不碰设备。 */
function actTool(runtime) {
  return defineTool({
    name: 'game_act',
    description:
      'Press one gamepad button for a short duration after game_attach. The engine refuses when an anti-cheat is ' +
      'running, when nobody is at the keyboard, or after the takeover hotkey (F12). The default backend is dry-run: ' +
      'it records the action instead of injecting input.',
    parameters: {
      button: { type: 'string', description: 'Gamepad button name, e.g. A / B / X / Y / START / DPAD_UP.' },
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
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `${value.action.dry_run ? 'DRY-RUN: would press' : 'Pressed'} ${value.action.button} for ${
            value.action.duration_ms
          }ms (backend: ${value.action.backend}); total actions: ${value.actions_total}.`,
        },
      ],
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
  },
}

/** 启动本地 20 Hz 闭环：模型只给目标，逐拍执行留在引擎里。 */
function planTool(runtime) {
  return defineTool({
    name: 'game_plan',
    description:
      'Start a local closed loop (about 20 Hz) that holds or repeatedly taps one gamepad button for a bounded ' +
      'duration. The loop re-checks the safety gate every tick, so anti-cheat detection, the takeover hotkey or the ' +
      'user coming back stop it immediately. Prefer this over repeated game_act calls.',
    parameters: {
      button: { type: 'string', description: 'Gamepad button to hold/tap, e.g. DPAD_RIGHT / A.' },
      mode: { type: 'string', description: 'hold (default) or tap.' },
      duration_ms: { type: 'number', description: 'How long the loop may run (100..120000, default 1000).' },
      tap_interval_ms: { type: 'number', description: 'For tap mode: interval between presses (20..1000, default 150).' },
    },
    timeoutMs: 120_000,
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: { plan: planSchema, safety: safetySchema },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `Plan ${value.plan.id}: ${value.plan.mode} ${value.plan.button} for ${value.plan.duration_ms}ms ` +
            `(status: ${value.plan.status}).`,
        },
      ],
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
        },
      },
      render: (_args, value) => {
        const plan = value.plan
        const planText = plan
          ? `plan ${plan.status} (${plan.mode} ${plan.button}; ticks=${plan.ticks ?? 0}, hz=${plan.hz ?? 0}` +
            `${plan.stop_reason ? `, stopped: ${plan.stop_reason}` : ''})`
          : 'no plan'
        return [
          {
            type: 'text',
            text: `Attached: ${value.attached?.window ?? 'none'}; backend: ${value.backend}; ${planText}; ` +
              `safety: ${value.safety.allowed ? 'allowed' : `blocked — ${(value.safety.reasons ?? []).join('; ')}`}.`,
          },
        ]
      },
    },
    execute: async () => {
      const client = await requireEngine(runtime)
      return client.request('status', {}, { timeoutMs: 15_000 })
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
      return client.request('stop', {}, { timeoutMs: 15_000 })
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
  ctx.tools.register(attachTool(runtime))
  ctx.tools.register(actTool(runtime))
  ctx.tools.register(planTool(runtime))
  ctx.tools.register(statusTool(runtime))
  ctx.tools.register(stopTool(runtime))
  const approvalHook = controlApprovalHook()
  if (approvalHook && typeof ctx.on === 'function') ctx.on('tools/pre-execute', approvalHook)
  if (typeof ctx.on === 'function') ctx.on('dispose', () => runtime.dispose())
}

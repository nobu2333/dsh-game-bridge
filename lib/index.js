/**
 * dsh-game-bridge —— 插件入口（M0 脚手架）。
 *
 * 目标：给 DeepSeek Harness 装上「眼睛 + 手」。本文件是最小一版，只注册两个
 * 只读工具，用来证明三件事，任何一件不成立都不值得继续往下做：
 *   1. 插件能被 DSH 的 loader 加载，工具出现在模型的工具列表里；
 *   2. 工具返回的截图能以「图片块」进入模型上下文（attachment → image block），
 *      而不是把 base64 塞进会话文本；
 *   3. 插件被卸载（HMR / 重启）时没有残留（真正的引擎子进程在 M1 才接进来）。
 *
 * 设计约束（写进代码，不靠自觉）：
 *   - 模型只做「目标级」决策，绝不逐步输出按键：一次 tool call 3~5 秒，
 *     游戏里等于植物人；即时反应必须留在本地循环里（见 docs/DESIGN.md）。
 *   - 图像一律走宿主的 attachment 服务；工具结果只带引用，不搬字节。
 *   - 抓屏与输入注入只在本地，且必须过「夺回」与「反作弊拒绝」两道闸（M2）。
 */
import { readFileSync } from 'node:fs'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'dsh-game-bridge'

/** 依赖的宿主服务：工具注册表 + 图片附件存储。缺任一服务插件不会激活。 */
export const inject = ['tools', 'attachments']

const VERSION = '0.0.1'

/**
 * M0 的合成帧：不碰真实屏幕，只验证「字节 → attachment → 图片块」这条链路。
 * 真实抓屏在 M1 由 Python 引擎返回，同样走这个出口。
 */
const SYNTHETIC_FRAME = readFileSync(new URL('./frames/synthetic-frame.png', import.meta.url))

/** 只读自检：回答「插件装上了吗、引擎在哪一步」。 */
function selftestTool() {
  return defineTool({
    name: 'game_selftest',
    description:
      'Report whether the dsh-game-bridge plugin is loaded in this harness, its version, the host platform, ' +
      'and whether the local game engine is installed. Call this before claiming any game capability to the user.',
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
        },
      },
      render: (_args, value) => [
        {
          type: 'text',
          text: `${value.plugin} ${value.version} loaded on ${value.platform}. Engine: ${value.engine}.`,
        },
      ],
    },
    execute: async () => ({
      plugin: 'dsh-game-bridge',
      version: VERSION,
      platform: `${process.platform}-${process.arch}`,
      engine: 'not installed (M0 scaffold: synthetic frames only)',
    }),
  })
}

/**
 * 截图工具。M0 返回合成帧；M1 起改由引擎抓屏，但返回契约不变：
 * 一张图片块 + 一行可读的元数据。
 */
function snapshotTool(ctx) {
  return defineTool({
    name: 'game_snapshot',
    description:
      'Return one frame of what the game bridge can currently see, as an image plus its dimensions. ' +
      'In this M0 build the frame is synthetic and proves the image pipeline only; no screen is captured yet.',
    parameters: {},
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          width: { type: 'number', required: true },
          height: { type: 'number', required: true },
          source: { type: 'string', required: true },
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
        { type: 'text', text: `Frame ${value.width}x${value.height} (${value.source}).` },
        { type: 'image', attachment: value.attachment },
      ],
    },
    execute: async () => {
      const ref = await ctx.attachments.saveImage({
        data: new Uint8Array(SYNTHETIC_FRAME),
        mediaType: 'image/png',
      })
      return {
        width: ref.width,
        height: ref.height,
        source: 'synthetic M0 frame',
        attachment: ref,
      }
    },
  })
}

/** Cordis 插件入口。注册返回的 disposer 由宿主管，这里不需要额外清理。 */
export function apply(ctx) {
  ctx.tools.register(selftestTool())
  ctx.tools.register(snapshotTool(ctx))
}

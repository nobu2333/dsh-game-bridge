/**
 * 引擎子进程客户端：stdio 上一行一个 JSON 请求/响应。
 *
 * 设计要点：
 * - **懒启动**：第一次真正需要眼睛时才 spawn，卸载/退出时整棵杀掉；
 * - **请求超时**：抓屏偶尔会卡在 DXGI 上，不能让工具调用无限挂住模型轮次；
 * - **失败可诊断**：把子进程最近的 stderr 带进错误消息，用户能看到真实原因；
 * - **不重试**：引擎崩溃时由调用方决定降级（M1 降级为合成帧），不静默重启。
 */
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'

export class EngineError extends Error {
  constructor(message, code = 'ENGINE_ERROR') {
    super(message)
    this.name = 'EngineError'
    this.code = code
  }
}

export class EngineClient {
  constructor({ python, cwd, env, timeoutMs = 30_000 }) {
    this.python = python
    this.cwd = cwd
    this.env = env
    this.timeoutMs = timeoutMs
    this.child = null
    this.stderr = ''
    this.pending = new Map()
    this.nextId = 1
    this.failure = null
  }

  start() {
    if (this.child) return
    const child = spawn(this.python, ['-m', 'dsh_game_core', 'serve'], {
      cwd: this.cwd,
      env: this.env,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    this.child = child
    // ⚠️ 关键：插件跑在 DSH 宿主进程里，子进程（及其管道）默认会把它的事件循环
    // 挂住——`dsh headless` 跑完就退出不了（实测：任务完成后进程永久挂起，
    // 最终被外部超时杀掉，表现为 exit code 1）。unref 之后宿主可以正常退出，
    // 引擎的清理交给 dispose 与下面的 exit 兜底。
    child.unref()
    child.stdin?.unref?.()
    child.stdout?.unref?.()
    child.stderr?.unref?.()

    // 宿主进程无论怎么退出，都不许留下孤儿引擎进程。
    this.exitHook = () => {
      try {
        child.kill()
      } catch {
        /* 已经死了 */
      }
    }
    process.once('exit', this.exitHook)

    const reader = createInterface({ input: child.stdout })
    reader.on('line', (line) => this.#onLine(line))
    child.stdin.on('error', () => {
      /* 引擎已死时写入会 EPIPE；由 exit/超时路径统一报错，这里只吞掉流错误 */
    })
    child.on('error', (error) => {
      this.failure = `engine failed to start: ${error.message}`
      for (const { reject } of this.pending.values()) reject(new EngineError(this.failure, 'ENGINE_SPAWN_FAILED'))
      this.pending.clear()
      this.child = null
    })
    child.stderr.on('data', (chunk) => {
      this.stderr = (this.stderr + String(chunk)).slice(-4000)
    })
    child.on('exit', (code, signal) => {
      this.failure = `engine exited (code=${code}, signal=${signal}): ${this.stderr.trim()}`
      for (const { reject } of this.pending.values()) reject(new EngineError(this.failure, 'ENGINE_EXITED'))
      this.pending.clear()
      this.child = null
    })
  }

  #onLine(line) {
    if (!line.trim()) return
    let message
    try {
      message = JSON.parse(line)
    } catch {
      return
    }
    const entry = this.pending.get(message.id)
    if (!entry) return
    this.pending.delete(message.id)
    if (message.ok) {
      entry.resolve(message.result)
    } else {
      entry.reject(new EngineError(message.error?.message ?? 'engine error', message.error?.code ?? 'ENGINE_ERROR'))
    }
  }

  request(method, params = {}, { timeoutMs } = {}) {
    this.start()
    if (this.failure) return Promise.reject(new EngineError(this.failure, 'ENGINE_EXITED'))
    const id = this.nextId++
    const limit = timeoutMs ?? this.timeoutMs
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new EngineError(`engine request '${method}' timed out after ${limit}ms`, 'ENGINE_TIMEOUT'))
      }, limit)
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer)
          resolve(value)
        },
        reject: (error) => {
          clearTimeout(timer)
          reject(error)
        },
      })
      this.child.stdin.write(`${JSON.stringify({ id, method, params })}\n`)
    })
  }

  dispose() {
    if (this.exitHook) {
      process.off('exit', this.exitHook)
      this.exitHook = null
    }
    if (!this.child) return
    try {
      this.child.stdin.end()
      this.child.kill()
    } catch {
      /* 进程可能已经死了，忽略 */
    }
    this.child = null
  }
}

/**
 * 从环境变量解析引擎位置。
 *
 * M1 的开发/自测形态：
 *   DSH_GAME_BRIDGE_PYTHON      指向一个装好依赖的 Python（本机先用 宿项目 的 venv）
 *   DSH_GAME_BRIDGE_ENGINE_DIR  引擎包所在目录（spawn 的 cwd，保证 `-m dsh_game_core` 可解析）
 *   DSH_GAME_BRIDGE_ENGINE_TIMEOUT_MS
 *
 * M2 会换成「自举安装 + 缓存路径」，用户不再需要配这些。
 */
export function resolveEngineConfig(env = process.env) {
  const python = env.DSH_GAME_BRIDGE_PYTHON
  // 'off' 是显式关掉引擎的开关（测试用；也让用户能一键退化为纯合成帧排查问题）。
  if (!python || python === 'off') return null
  return {
    python,
    cwd: env.DSH_GAME_BRIDGE_ENGINE_DIR || process.cwd(),
    env: { ...process.env },
    timeoutMs: Number(env.DSH_GAME_BRIDGE_ENGINE_TIMEOUT_MS || 30_000),
  }
}

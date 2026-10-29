/**
 * M0 会话级集成测试（隔离环境，不碰用户 ~/.dsh、不碰键鼠、不联网）。
 *
 * 做三件事：
 *   1. 在隔离的 DSH_HOME 里，给 headless profile 写一条「假的本地模型」补丁；
 *   2. 起一个 OpenAI 兼容的假服务器：第一次请求回 tool_call 让模型调用
 *      game_snapshot，第二次请求回最终文本；
 *   3. 跑 `dsh --profile headless --json`，然后用假服务器**记录到的请求体**断言：
 *      - harness 真的把 game_selftest / game_snapshot 暴露给了模型（tools 数组）；
 *      - 工具执行后，harness 把图片作为 data:image/png 送回了模型（图片块链路）；
 *      - 进程正常退出并输出最终文本。
 *
 * 用法：node test/integration/m0-session.mjs
 * 前置：隔离 profile 里已装好本地包
 *   $env:DSH_HOME='<repo>/.dsh-test'
 *   dsh --profile headless --dump-config      # 初始化 profile
 *   dsh plugin --profile headless add file:<repo>
 */
import { createServer } from 'node:http'
import { spawn } from 'node:child_process'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '../..')
const dshHome = process.env.DSH_HOME ?? resolve(repo, '.dsh-test')
const profileDir = resolve(dshHome, 'profiles/headless')
const outDir = resolve(here, '.out')
const dshCmd = process.env.DSH_CMD ?? 'C:/Users/<user>/AppData/Roaming/npm/dsh.cmd'

const requests = []

function sse(res, payload) {
  res.write(`data: ${JSON.stringify(payload)}\n\n`)
}

function startFakeProvider() {
  const server = createServer((req, res) => {
    if (req.method === 'GET' && req.url.endsWith('/models')) {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ object: 'list', data: [{ id: 'fake-1', object: 'model' }] }))
      return
    }
    let raw = ''
    req.on('data', (chunk) => (raw += chunk))
    req.on('end', () => {
      let body = {}
      try {
        body = JSON.parse(raw)
      } catch {
        /* 记录原文便于排障 */
      }
      requests.push({ url: req.url, body })
      const messages = Array.isArray(body.messages) ? body.messages : []
      const sawToolResult = messages.some((message) => message?.role === 'tool')

      res.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      })
      const base = {
        id: 'chatcmpl-fake',
        object: 'chat.completion.chunk',
        created: Math.floor(Date.now() / 1000),
        model: 'fake-1',
      }
      if (!sawToolResult) {
        // 第一次：要求模型调用 game_snapshot。
        sse(res, {
          ...base,
          choices: [
            {
              index: 0,
              delta: {
                role: 'assistant',
                tool_calls: [
                  { index: 0, id: 'call_fake_1', type: 'function', function: { name: 'game_snapshot', arguments: '' } },
                ],
              },
              finish_reason: null,
            },
          ],
        })
        sse(res, {
          ...base,
          choices: [
            { index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: '{}' } }] }, finish_reason: null },
          ],
        })
        sse(res, {
          ...base,
          choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }],
          usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
        })
      } else {
        // 第二次：看到工具结果了，给最终文本。
        sse(res, {
          ...base,
          choices: [{ index: 0, delta: { role: 'assistant', content: 'M0-INTEGRATION-OK' }, finish_reason: null }],
        })
        sse(res, {
          ...base,
          choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
          usage: { prompt_tokens: 20, completion_tokens: 3, total_tokens: 23 },
        })
      }
      res.write('data: [DONE]\n\n')
      res.end()
    })
  })
  return new Promise((resolvePromise) => {
    server.listen(0, '127.0.0.1', () => resolvePromise({ server, port: server.address().port }))
  })
}

function writePatch(port) {
  const patch = `# 由 test/integration/m0-session.mjs 生成；隔离 profile 专用，勿提交。
- id: llm-pi-ai
  name: '@deepseek-ai/dsh-llm-pi-ai'
  config:
    providers:
      fake-local:
        displayName: Fake Local
        api: openai-completions
        baseURL: http://127.0.0.1:${port}/v1
        headers:
          Authorization: Bearer fake-test-key
        models:
          - id: fake-1
            name: fake-1
            contextWindow: 65536
            input: [text, image]
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: fake-local
    model: fake-1
`
  writeFileSync(resolve(profileDir, 'cordis.patch.yml'), patch, 'utf8')
}

function runHeadless() {
  return new Promise((resolvePromise) => {
    const child = spawn(process.env.ComSpec ?? 'cmd.exe', ['/c', dshCmd, '--profile', 'headless', '--json', 'Call game_snapshot once, then report what you saw.'], {
      cwd: repo,
      env: { ...process.env, DSH_HOME: dshHome },
      windowsHide: true,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => (stdout += chunk))
    child.stderr.on('data', (chunk) => (stderr += chunk))
    const timer = setTimeout(() => {
      child.kill()
      resolvePromise({ code: 'timeout', stdout, stderr })
    }, 180_000)
    child.on('close', (code) => {
      clearTimeout(timer)
      resolvePromise({ code, stdout, stderr })
    })
  })
}

async function main() {
  if (!existsSync(resolve(profileDir, 'package.json'))) {
    throw new Error(`isolated headless profile missing: ${profileDir}. Initialize it with DSH_HOME=${dshHome} dsh --profile headless --dump-config`)
  }
  const manifest = JSON.parse(readFileSync(resolve(profileDir, 'package.json'), 'utf8'))
  if (!manifest.dependencies?.['dsh-game-bridge']) {
    throw new Error(`dsh-game-bridge is not installed in ${profileDir}. Run: DSH_HOME=${dshHome} dsh plugin --profile headless add file:${repo}`)
  }

  const { server, port } = await startFakeProvider()
  writePatch(port)
  console.log(`fake provider on 127.0.0.1:${port}; running isolated headless session...`)
  const run = await runHeadless()
  server.close()

  mkdirSync(outDir, { recursive: true })
  writeFileSync(resolve(outDir, 'headless.stdout.txt'), run.stdout, 'utf8')
  writeFileSync(resolve(outDir, 'headless.stderr.txt'), run.stderr, 'utf8')
  writeFileSync(resolve(outDir, 'provider-requests.json'), JSON.stringify(requests, null, 2), 'utf8')

  const toolNames = (requests[0]?.body?.tools ?? []).map((tool) => tool?.function?.name ?? tool?.name)
  const allRequestText = JSON.stringify(requests)
  const sawImage = allRequestText.includes('data:image/png')
  const sawToolResult = requests.some((request) => (request?.body?.messages ?? []).some((message) => message?.role === 'tool'))

  console.log(`run exit: ${run.code}`)
  console.log(`tools exposed to the model: ${JSON.stringify(toolNames)}`)
  console.log(`tool result came back: ${sawToolResult}`)
  console.log(`image bytes returned to the model as data:image/png: ${sawImage}`)

  assert.equal(run.code, 0, `headless exited ${run.code}\nstderr:\n${run.stderr}\nstdout:\n${run.stdout}`)
  assert.ok(toolNames.includes('game_selftest'), 'game_selftest was not exposed to the model')
  assert.ok(toolNames.includes('game_snapshot'), 'game_snapshot was not exposed to the model')
  assert.ok(sawToolResult, 'the tool result did not come back to the model')
  assert.ok(sawImage, 'the screenshot did not reach the model as an image')
  assert.ok(run.stdout.includes('M0-INTEGRATION-OK'), 'final assistant text missing from headless output')
  console.log('M0 INTEGRATION PASS')
}

main().catch((error) => {
  console.error('M0 INTEGRATION FAIL:', error.message)
  process.exitCode = 1
})

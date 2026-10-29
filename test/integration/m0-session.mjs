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
import { spawn, spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs'
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
      mkdirSync(outDir, { recursive: true })
      appendFileSync(resolve(outDir, 'provider-requests.jsonl'), `${JSON.stringify({ url: req.url, body })}\n`)
      const messages = Array.isArray(body.messages) ? body.messages : []
      const toolResults = messages.filter((message) => message?.role === 'tool').length
      // FAKE_SEQUENCE 允许脚本化多步工具调用，例如 "game_attach,game_act"。
      const sequence = (process.env.FAKE_SEQUENCE ?? process.env.FAKE_TOOL ?? 'game_snapshot')
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean)
      const nextTool = toolResults < sequence.length ? sequence[toolResults] : null

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
      if (nextTool) {
        const defaultArgs =
          nextTool === 'game_attach'
            ? JSON.stringify({ window: process.env.FAKE_WINDOW ?? 'fixture-game' })
            : nextTool === 'game_act'
              ? '{"button":"A","duration_ms":50}'
              : nextTool === 'game_plan'
                ? '{"button":"DPAD_RIGHT","mode":"hold","duration_ms":300}'
                : '{}'
        const args = process.env.FAKE_ARGS ?? defaultArgs
        sse(res, {
          ...base,
          choices: [
            {
              index: 0,
              delta: {
                role: 'assistant',
                tool_calls: [
                  {
                    index: 0,
                    id: `call_fake_${toolResults + 1}`,
                    type: 'function',
                    function: { name: nextTool, arguments: args },
                  },
                ],
              },
              finish_reason: null,
            },
          ],
        })
        sse(res, {
          ...base,
          choices: [
            { index: 0, delta: { tool_calls: [{ index: 0, function: { arguments: '' } }] }, finish_reason: null },
          ],
        })
        sse(res, {
          ...base,
          choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }],
          usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
        })
      } else {
        // 序列走完：给最终文本。
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
    mkdirSync(outDir, { recursive: true })
    const stdoutPath = resolve(outDir, 'headless.stdout.txt')
    const stderrPath = resolve(outDir, 'headless.stderr.txt')
    writeFileSync(stdoutPath, '')
    writeFileSync(stderrPath, '')
    const nodeArgs = []
    if (process.env.DSH_GAME_BRIDGE_TRACE) nodeArgs.push('--trace-exit', '--trace-uncaught')
    const child = spawn(
      process.execPath,
      [
        ...nodeArgs,
        process.env.DSH_BIN ?? 'C:/Users/<user>/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/lib/bin.js',
        '--profile',
        'headless',
        '--json',
        'Call game_snapshot once, then report what you saw.',
      ],
      {
        cwd: repo,
        env: { ...process.env, DSH_HOME: dshHome },
        windowsHide: true,
      },
    )
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolvePromise({ code, stdout, stderr })
    }
    child.stdout.on('data', (chunk) => {
      stdout += chunk
      appendFileSync(stdoutPath, chunk)
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk
      appendFileSync(stderrPath, chunk)
    })
    const timeoutMs = Number(process.env.DSH_GAME_BRIDGE_TEST_TIMEOUT_MS || 120_000)
    const timer = setTimeout(() => {
      // cmd.exe 的孙进程（dsh 的 node、插件的 python）不会随 child.kill() 消失，
      // 必须整棵杀掉，否则测试永远等不到 close。
      try {
        spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
      } catch {
        /* 进程可能已退出 */
      }
      setTimeout(() => finish('timeout'), 3000)
    }, timeoutMs)
    child.on('close', (code) => finish(code))
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
  const sequence = (process.env.FAKE_SEQUENCE ?? process.env.FAKE_TOOL ?? 'game_snapshot')
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)
  const toolCalled = sequence[0]
  const engineExpected =
    (Boolean(process.env.DSH_GAME_BRIDGE_PYTHON) && process.env.DSH_GAME_BRIDGE_PYTHON !== 'off') ||
    Boolean(process.env.DSH_GAME_BRIDGE_ENGINE_SPEC) ||
    Boolean(process.env.DSH_GAME_BRIDGE_CACHE_DIR)
  const sawScreenFrame = allRequestText.includes('screen via dsh-game-core')
  const sawOcr = /OCR: [^"]+/.test(allRequestText)
  const sawEngineAnswered = allRequestText.includes('answered')
  const sawAttach = allRequestText.includes('Attached to')
  const sawDryRun = allRequestText.includes('DRY-RUN')
  const sawPlan = allRequestText.includes('Plan plan-')
  const sawStatus = allRequestText.includes('backend: dry-run;')
  const sawWindows = allRequestText.includes('Visible windows')
  const sawEvent = allRequestText.includes('Frame event')
  const expectApprovalDenied = process.env.DSH_GAME_BRIDGE_EXPECT_APPROVAL_DENIED === '1'
  const sawApprovalDenied = allRequestText.includes('requires approval')
  const expectRecovery = process.env.DSH_GAME_BRIDGE_EXPECT_RECOVERY === '1'

  console.log(`run exit: ${run.code}`)
  console.log(`tool sequence: ${sequence.join(' → ')}`)
  console.log(`tools exposed to the model: ${JSON.stringify(toolNames)}`)
  console.log(`tool result came back: ${sawToolResult}`)
  console.log(`image bytes returned to the model as data:image/png: ${sawImage}`)
  if (engineExpected) {
    console.log(`real screen frame used: ${sawScreenFrame}`)
    console.log(`OCR text attached: ${sawOcr}`)
    console.log(`engine answered ping: ${sawEngineAnswered}`)
  }
  if (sequence.includes('game_attach')) console.log(`attach result seen: ${sawAttach}`)
  if (sequence.includes('game_act')) console.log(`dry-run action seen: ${sawDryRun}`)

  assert.equal(run.code, 0, `headless exited ${run.code}\nstderr:\n${run.stderr}\nstdout:\n${run.stdout}`)
  for (const name of ['game_selftest', 'game_snapshot', 'game_attach', 'game_act', 'game_stop']) {
    assert.ok(toolNames.includes(name), `${name} was not exposed to the model`)
  }
  assert.ok(sawToolResult, 'the tool result did not come back to the model')
  if (toolCalled === 'game_snapshot') {
    assert.ok(sawImage, 'the screenshot did not reach the model as an image')
    if (engineExpected) {
      assert.ok(sawScreenFrame, 'the engine was configured but the frame was not a real screen capture')
      assert.ok(sawOcr, 'the engine returned no OCR text with the frame')
    }
  }
  if (toolCalled === 'game_selftest' && engineExpected) {
    assert.ok(sawEngineAnswered, 'the engine was expected but the selftest did not report a ping answer')
  }
  if (sequence.includes('game_attach')) {
    if (expectApprovalDenied) {
      assert.ok(sawApprovalDenied, 'approval was expected to fail closed but no approval error was reported')
    } else {
      assert.ok(sawAttach, 'game_attach did not produce an attach result')
    }
  }
  if (sequence.includes('game_act')) assert.ok(sawDryRun, 'game_act did not report a dry-run action')
  if (sequence.includes('game_plan')) assert.ok(sawPlan, 'game_plan did not report a started plan')
  if (sequence.includes('game_status')) assert.ok(sawStatus, 'game_status did not report status')
  if (sequence.includes('game_windows')) assert.ok(sawWindows, 'game_windows did not list visible windows')
  if (sequence.includes('game_events')) assert.ok(sawEvent, 'game_events did not report a frame-difference event')
  assert.ok(run.stdout.includes('M0-INTEGRATION-OK'), 'final assistant text missing from headless output')
  let mode
  if (expectRecovery) mode = 'RECOVERY PASS (engine restarted after exit)'
  else if (expectApprovalDenied) mode = 'APPROVAL PASS (real backend without responder fails closed)'
  else if (sequence.includes('game_plan')) mode = 'M3 PASS (attach → plan → status → stop, dry-run loop)'
  else if (sequence.includes('game_act')) mode = 'M2 PASS (attach → dry-run act, no real input)'
  else if (sequence.includes('game_events')) mode = 'EVENTS PASS (frame differencing)'
  else if (sequence.includes('game_windows')) mode = 'WINDOWS PASS (visible window list)'
  else if (engineExpected) {
    mode = toolCalled === 'game_selftest' ? 'M1 BOOTSTRAP PASS (engine installed and answered)' : 'M1 INTEGRATION PASS (real capture + OCR)'
  } else mode = 'M0 INTEGRATION PASS (synthetic frame)'
  console.log(mode)
}

main().catch((error) => {
  console.error('M0 INTEGRATION FAIL:', error.message)
  process.exitCode = 1
})


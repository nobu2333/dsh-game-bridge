/**
 * M0 契约测试：不启动 DSH、不碰真实屏幕，只验证插件对宿主契约的用法是否正确。
 *
 * 依赖宿主里那份真实的 `@deepseek-ai/dsh-tools`（本机以 junction 链接到
 * %USERPROFILE%\.dsh\profiles\node_modules 下的副本），因此这里校验的是
 * defineTool 的真实行为，而不是我们自造的桩：
 *   - 插件身份与 inject 声明；
 *   - apply() 注册出的工具名；
 *   - 输出 schema 能接受 execute() 的返回值；
 *   - 图片块的形状是 { type: 'image', attachment: { ... } }。
 */
import test from 'node:test'
import assert from 'node:assert/strict'

// 单元测试不许触发真实引擎自举（会去建 venv / 装包）：显式关掉。
process.env.DSH_GAME_BRIDGE_PYTHON = 'off'

const { apply, inject, name } = await import('../lib/index.js')

function fakeCtx() {
  const registered = []
  const listeners = new Map()
  return {
    registered,
    listeners,
    on(event, listener) {
      listeners.set(event, listener)
    },
    tools: {
      register(definition) {
        registered.push(definition)
        return () => {}
      },
    },
    attachments: {
      async saveImage({ data, mediaType }) {
        assert.equal(mediaType, 'image/png')
        assert.ok(data instanceof Uint8Array)
        // 与宿主 AttachmentStore.saveImage 的返回形状保持一致（M0 桩）。
        return { attachmentId: 'att_m0_test', mediaType, bytes: data.length, width: 320, height: 180 }
      },
    },
  }
}

function tool(ctx, toolName) {
  const found = ctx.registered.find((definition) => definition.name === toolName)
  assert.ok(found, `tool ${toolName} was not registered`)
  return found
}

test('plugin declares identity and the services it needs', () => {
  assert.equal(name, 'dsh-game-bridge')
  assert.deepEqual(inject, ['tools', 'attachments'])
})

test('apply() registers the current tool surface', () => {
  const ctx = fakeCtx()
  apply(ctx)
  assert.deepEqual(
    ctx.registered.map((definition) => definition.name).sort(),
    ['game_act', 'game_attach', 'game_controls', 'game_events', 'game_plan', 'game_selftest', 'game_snapshot', 'game_status', 'game_stop', 'game_windows'],
  )
})

test('game_attach refuses loudly when the engine is unavailable', async () => {
  const ctx = fakeCtx()
  apply(ctx)
  const definition = tool(ctx, 'game_attach')
  await assert.rejects(() => definition.execute({ window: 'SomeGame' }, {}), /not ready/)
})

test('game_selftest reports a failed engine instead of pretending', async () => {
  const ctx = fakeCtx()
  apply(ctx)
  const definition = tool(ctx, 'game_selftest')
  const value = await definition.execute({}, {})
  assert.equal(value.plugin, 'dsh-game-bridge')
  assert.equal(value.engine_ready, false)
  assert.equal(value.engine.includes('failed'), true)
  JSON.stringify(value) // 输出值必须是无损 JSON
  const blocks = definition.output.render({}, value)
  assert.equal(blocks.length, 1)
  assert.equal(blocks[0].type, 'text')
})

test('game_snapshot falls back to the synthetic frame when the engine is off', async () => {
  const ctx = fakeCtx()
  apply(ctx)
  const definition = tool(ctx, 'game_snapshot')
  const value = await definition.execute({}, {})
  assert.equal(value.width, 320)
  assert.equal(value.height, 180)
  assert.equal(value.source, 'synthetic fallback')
  assert.equal(value.attachment.attachmentId, 'att_m0_test')
  JSON.stringify(value) // 图片引用必须是可序列化的，不能带原始字节
  const blocks = definition.output.render({}, value)
  assert.equal(blocks.length, 2)
  assert.equal(blocks[0].type, 'text')
  assert.equal(blocks[1].type, 'image')
  assert.equal(blocks[1].attachment.attachmentId, 'att_m0_test')
})

test('dry-run registers no approval hook', () => {
  delete process.env.DSH_GAME_BRIDGE_CONTROL
  const ctx = fakeCtx()
  apply(ctx)
  assert.equal(ctx.listeners.has('tools/pre-execute'), false)
})

test('real backend asks approval before attach and passes other tools through', async () => {
  process.env.DSH_GAME_BRIDGE_CONTROL = 'vgamepad'
  try {
    const ctx = fakeCtx()
    apply(ctx)
    const hook = ctx.listeners.get('tools/pre-execute')
    assert.ok(hook, 'real backend must register the approval hook')

    const asked = await hook({ name: 'game_attach' }, async () => ({ kind: 'allow' }))
    assert.equal(asked.kind, 'ask')
    assert.match(asked.displayReason.en, /real input control/)
    assert.match(asked.displayReason.zh, /真实输入后端/)

    let nextCalled = false
    const passed = await hook({ name: 'game_act' }, async () => {
      nextCalled = true
      return { kind: 'allow' }
    })
    assert.equal(passed.kind, 'allow')
    assert.equal(nextCalled, true)
  } finally {
    delete process.env.DSH_GAME_BRIDGE_CONTROL
  }
})

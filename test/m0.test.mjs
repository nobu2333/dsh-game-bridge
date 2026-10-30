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
  // 单元测试不该依赖调用者 shell 里的后端选择。
  const savedControl = process.env.DSH_GAME_BRIDGE_CONTROL
  delete process.env.DSH_GAME_BRIDGE_CONTROL
  let value
  try {
    value = await definition.execute({}, {})
  } finally {
    if (savedControl !== undefined) process.env.DSH_GAME_BRIDGE_CONTROL = savedControl
  }
  assert.equal(value.plugin, 'dsh-game-bridge')
  assert.equal(value.engine_ready, false)
  assert.equal(value.engine.includes('failed'), true)
  // 新诊断字段：安装来源与后端就绪状态即使引擎不可用也要有。
  assert.equal(typeof value.install, 'object')
  assert.equal(typeof value.install.package_dir, 'string')
  assert.ok(
    ['registry', 'local-file', 'link', 'github', 'unknown'].includes(value.install.source),
    `unexpected install source ${value.install.source}`,
  )
  assert.ok(Array.isArray(value.install.warnings))
  assert.equal(typeof value.backend, 'object')
  assert.equal(value.backend.name, 'dry-run')
  assert.equal(value.backend.ready, false)
  assert.ok(Array.isArray(value.backend.warnings))
  assert.equal(value.report, undefined, 'no engine selftest report when the engine is off')
  JSON.stringify(value) // 输出值必须是无损 JSON
  const blocks = definition.output.render({}, value)
  assert.equal(blocks.length, 1)
  assert.equal(blocks[0].type, 'text')
  assert.match(blocks[0].text, /engine: failed/)
  assert.match(blocks[0].text, /backend: dry-run/)
  assert.match(blocks[0].text, /install: /)
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
  // 没有引擎就没有前台/遮挡信息：字段应整个缺省，而不是塞一个假值。
  assert.equal(value.foreground, undefined)
  assert.equal(value.occluded, undefined)
  JSON.stringify(value) // 图片引用必须是可序列化的，不能带原始字节
  const blocks = definition.output.render({}, value)
  assert.equal(blocks.length, 2)
  assert.equal(blocks[0].type, 'text')
  assert.equal(blocks[1].type, 'image')
  assert.equal(blocks[1].attachment.attachmentId, 'att_m0_test')
})

test('renders keep the integration substrings and surface the new diagnostics', () => {
  const ctx = fakeCtx()
  apply(ctx)
  const control = {
    backend: 'dry-run',
    ready: true,
    detail: 'records actions only',
    xinput_slot: null,
    warnings: [],
  }
  const foreground = { hwnd: 11, title: 'Fixture Game', process: 'fixture.exe' }

  const [attachBlock] = tool(ctx, 'game_attach').output.render(
    {},
    { attached: { window: 'Fixture Game' }, backend: 'dry-run', safety: { allowed: true, reasons: [] }, control, foreground },
  )
  assert.ok(attachBlock.text.startsWith('Attached to Fixture Game'))
  assert.match(attachBlock.text, /Safety: allowed/)
  assert.match(attachBlock.text, /Control: dry-run ready/)
  assert.match(attachBlock.text, /Foreground: Fixture Game \(hwnd 11\)/)

  const [actBlock] = tool(ctx, 'game_act').output.render(
    {},
    {
      action: { backend: 'dry-run', button: 'A', duration_ms: 80, dry_run: true },
      safety: { allowed: true, reasons: [] },
      actions_total: 1,
      delivery: { checked: true, foreground: true, hwnd: 11, title: 'Fixture Game' },
    },
  )
  assert.match(actBlock.text, /^DRY-RUN: would press A for 80ms/)
  assert.match(actBlock.text, /Delivery: target window is in the foreground/)

  const [pressedBlock] = tool(ctx, 'game_act').output.render(
    {},
    {
      action: { backend: 'vgamepad', button: 'B', duration_ms: 40, dry_run: false },
      safety: { allowed: true, reasons: [] },
      actions_total: 2,
      delivery: { checked: true, foreground: false, hwnd: 11, title: 'Editor' },
    },
  )
  assert.ok(pressedBlock.text.startsWith('Pressed B for 40ms'))
  assert.match(pressedBlock.text, /NOT in the foreground \(now: Editor\)/)

  const [planBlock] = tool(ctx, 'game_plan').output.render(
    {},
    {
      plan: { id: 'plan-123', mode: 'hold', button: 'DPAD_RIGHT', duration_ms: 300, status: 'running' },
      safety: { allowed: true, reasons: [] },
      control,
      foreground,
    },
  )
  assert.ok(planBlock.text.startsWith('Plan plan-123: hold DPAD_RIGHT'))
  assert.match(planBlock.text, /Foreground: Fixture Game \(hwnd 11\)/)

  const [statusBlock] = tool(ctx, 'game_status').output.render(
    {},
    {
      attached: { window: 'Fixture Game' },
      backend: 'dry-run',
      safety: { allowed: true, reasons: [] },
      actions_total: 0,
      control,
      foreground,
    },
  )
  assert.match(statusBlock.text, /backend: dry-run;/)
  assert.match(statusBlock.text, /Foreground: Fixture Game \(hwnd 11\)/)

  const [snapshotBlock] = tool(ctx, 'game_snapshot').output.render(
    {},
    {
      width: 16,
      height: 9,
      source: 'window via dsh-game-core',
      note: 'OCR: fixture text (0.9)',
      attachment: { attachmentId: 'att_render', mediaType: 'image/png', bytes: 1, width: 16, height: 9 },
      foreground,
      occluded: {
        available: true,
        occluded_ratio: 0.62,
        occluded: true,
        covered_by: [{ hwnd: 22, title: 'Editor', ratio: 0.62 }],
      },
    },
  )
  assert.match(snapshotBlock.text, /^Frame 16x9 \(window via dsh-game-core\)\./)
  assert.match(snapshotBlock.text, /OCR: fixture text/)
  assert.match(snapshotBlock.text, /Foreground: Fixture Game \(hwnd 11\)/)
  assert.match(snapshotBlock.text, /⚠ target window is 62% occluded \(mostly by Editor\)/)

  const [clearSnapshot] = tool(ctx, 'game_snapshot').output.render(
    {},
    {
      width: 16,
      height: 9,
      source: 'screen via dsh-game-core',
      note: 'OCR: no text found',
      attachment: { attachmentId: 'att_render', mediaType: 'image/png', bytes: 1, width: 16, height: 9 },
      occluded: { available: true, occluded_ratio: 0.0, occluded: false, covered_by: [] },
    },
  )
  assert.match(clearSnapshot.text, /screen via dsh-game-core/)
  assert.match(clearSnapshot.text, /Occlusion: 0% covered/)
  assert.doesNotMatch(clearSnapshot.text, /⚠/)
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

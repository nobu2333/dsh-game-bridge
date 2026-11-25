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
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// 单元测试不许触发真实引擎自举（会去建 venv / 装包）：显式关掉。
process.env.DSH_GAME_BRIDGE_PYTHON = 'off'

const { apply, inject, name, normalizeOcrBoxes } = await import('../lib/index.js')

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
    [
      'game_act',
      'game_act_batch',
      'game_attach',
      'game_controls',
      'game_events',
      'game_intent',
      'game_memory',
      'game_plan',
      'game_policy',
      'game_selftest',
      'game_snapshot',
      'game_state',
      'game_status',
      'game_stop',
      'game_windows',
    ],
  )
})

test('game_attach refuses loudly when the engine is unavailable', async () => {
  const ctx = fakeCtx()
  apply(ctx)
  const definition = tool(ctx, 'game_attach')
  await assert.rejects(() => definition.execute({ window: 'SomeGame' }, {}), /not ready/)
})

test('game_state, game_policy and game_intent refuse loudly when the engine is unavailable', async () => {
  const ctx = fakeCtx()
  apply(ctx)
  await assert.rejects(() => tool(ctx, 'game_state').execute({}, {}), /not ready/)
  await assert.rejects(() => tool(ctx, 'game_policy').execute({ action: 'status' }, {}), /not ready/)
  await assert.rejects(
    () => tool(ctx, 'game_intent').execute({ intent: { goal: 'advance', skill: 'advance' } }, {}),
    /not ready/,
  )
})

test('game_memory works without an engine and validates the profile id', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'dsh-game-bridge-profiles-'))
  const previous = process.env.DSH_GAME_BRIDGE_PROFILE_DIR
  process.env.DSH_GAME_BRIDGE_PROFILE_DIR = dir
  try {
    const ctx = fakeCtx()
    apply(ctx)
    const memory = tool(ctx, 'game_memory')

    const saved = await memory.execute(
      { action: 'save', id: 'fixture', data: { name: 'Fixture Game', controls: { jump: 'Z' } } },
      {},
    )
    assert.equal(saved.result.saved, true)
    assert.match(readFileSync(join(dir, 'fixture.json'), 'utf8'), /"id": "fixture"/)

    const listed = await memory.execute({ action: 'list' }, {})
    assert.deepEqual(listed.result.profiles.map((profile) => profile.id), ['fixture'])
    const [block] = memory.output.render({}, listed)
    assert.equal(block.type, 'text')
    assert.match(block.text, /Profiles \(1\): fixture \(Fixture Game\)/)

    // save 校验 id：路径穿越必须被拒绝（也不会在目录外留下文件）。
    await assert.rejects(
      () => memory.execute({ action: 'save', id: '../escape', data: {} }, {}),
      /invalid profile id/,
    )
  } finally {
    if (previous === undefined) delete process.env.DSH_GAME_BRIDGE_PROFILE_DIR
    else process.env.DSH_GAME_BRIDGE_PROFILE_DIR = previous
    rmSync(dir, { recursive: true, force: true })
  }
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

    const askedAutoFocus = await hook({ name: 'game_attach', arguments: { auto_focus: true } }, async () => ({ kind: 'allow' }))
    assert.equal(askedAutoFocus.kind, 'ask')
    assert.match(askedAutoFocus.displayReason.en, /auto_focus enabled/)
    assert.match(askedAutoFocus.displayReason.zh, /自动恢复窗口前台/)

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

test('status, stop, act and snapshot render/validate relative coords, attach_actions and auto_focus', async () => {
  const ctx = fakeCtx()
  apply(ctx)

  const [statusBlock] = tool(ctx, 'game_status').output.render(
    {},
    {
      attached: { window: 'Minesweeper' },
      backend: 'keyboard',
      auto_focus: true,
      safety: { allowed: true, reasons: [] },
      actions_total: 12,
      attach_actions: 4,
    },
  )
  assert.match(statusBlock.text, /backend: keyboard;/)
  assert.match(statusBlock.text, /auto_focus: on;/)
  assert.match(statusBlock.text, /actions: 4 \(total 12\);/)

  const [stopBlock] = tool(ctx, 'game_stop').output.render(
    {},
    { stopped: true, actions_total: 12, attach_actions: 4 },
  )
  assert.match(stopBlock.text, /actions this attach: 4/)
  assert.match(stopBlock.text, /total actions this session: 12/)

  const [relClickBlock] = tool(ctx, 'game_act').output.render(
    {},
    {
      action: { backend: 'keyboard', button: 'LEFT', duration_ms: 0, dry_run: false, mouse_click: true, x: 500, y: 350, rx: 0.5, ry: 0.25 },
      safety: { allowed: true, reasons: [] },
      actions_total: 12,
      attach_actions: 4,
    },
  )
  assert.match(relClickBlock.text, /Clicked LEFT at rel \(0\.5, 0\.25\) -> \(500, 350\)/)
  assert.match(relClickBlock.text, /\(this attach: 4\)/)

  // Schema compiles parameters under .properties; check rx/ry and snapshot controls are exposed.
  const actDef = tool(ctx, 'game_act')
  assert.ok(actDef.parameters.properties.rx && actDef.parameters.properties.ry)
  assert.ok(actDef.parameters.properties.to_rx && actDef.parameters.properties.to_ry)
  assert.ok(actDef.parameters.properties.action_type)
  const batchDef = tool(ctx, 'game_act_batch')
  assert.ok(batchDef.parameters.properties.steps)
  const [hoverBlock] = actDef.output.render(
    {},
    {
      action: { backend: 'keyboard', button: 'NONE', duration_ms: 0, dry_run: false, mouse_hover: true, x: 400, y: 300, rx: 0.5, ry: 0.5 },
      safety: { allowed: true, reasons: [] },
      actions_total: 13,
      attach_actions: 5,
    },
  )
  assert.match(hoverBlock.text, /Hovered at rel \(0\.5, 0\.5\) -> \(400, 300\)/)
  const [dragBlock] = actDef.output.render(
    {},
    {
      action: { backend: 'keyboard', button: 'LEFT', duration_ms: 200, dry_run: false, mouse_drag: true, x: 200, y: 500, rx: 0.25, ry: 0.8, to_x: 400, to_y: 300, to_rx: 0.5, to_ry: 0.5 },
      safety: { allowed: true, reasons: [] },
      actions_total: 14,
      attach_actions: 6,
    },
  )
  assert.match(dragBlock.text, /Dragged LEFT from rel \(0\.25, 0\.8\) -> \(200, 500\) to rel \(0\.5, 0\.5\) -> \(400, 300\)/)
  const [batchBlock] = batchDef.output.render(
    {},
    {
      executed: 2,
      requested: 3,
      stopped_reason: 'SAFETY_BLOCKED: F12 takeover',
      results: [],
      actions_total: 16,
      attach_actions: 8,
      safety: { allowed: false, reasons: ['F12 takeover'] },
    },
  )
  assert.match(batchBlock.text, /Batch: executed 2\/3 steps/)
  assert.match(batchBlock.text, /Stopped early: SAFETY_BLOCKED/)
  const snapDef = tool(ctx, 'game_snapshot')
  assert.ok(
    snapDef.parameters.properties.max_width &&
      snapDef.parameters.properties.ocr &&
      snapDef.parameters.properties.ocr_limit,
  )
  const attachDef = tool(ctx, 'game_attach')
  assert.ok(attachDef.parameters.properties.auto_focus)

  const boxes = normalizeOcrBoxes(
    [{ text: 'New Game', score: 0.98, left: 300, top: 200, right: 500, bottom: 240 }],
    1000,
    500,
  )
  assert.deepEqual(boxes, [{ text: 'New Game', score: 0.98, cx: 0.4, cy: 0.44, box: [0.3, 0.4, 0.5, 0.48] }])
})

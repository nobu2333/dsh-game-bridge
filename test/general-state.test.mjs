/**
 * Phase 1 通用状态基线的单元测试。
 *
 * 覆盖两块：
 *   1. `lib/profile-store.js` 纯逻辑（目录推导、id 校验、读写/列举/删除、
 *      坏 JSON 与注入 fs）——全部走临时目录或内存 fs，不碰用户真实 profile；
 *   2. `game_state` / `game_policy` / `game_memory` / `game_attach` 的渲染
 *      路径（用假值直接调 output.render，不启动引擎、不抓屏）。
 *
 * 公开仓库约束：这里不写本机绝对路径/用户名，临时目录一律 mkdtempSync。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// 渲染测试会 apply() 插件：显式关掉引擎自举，单元测试不联网、不建 venv。
process.env.DSH_GAME_BRIDGE_PYTHON = 'off'

import {
  ProfileStoreError,
  cacheRoot,
  deleteProfile,
  isValidProfileId,
  listProfiles,
  profilesDir,
  readProfile,
  validateProfileId,
  writeProfile,
} from '../lib/profile-store.js'

// 放在设置 env 之后动态导入，避免插件模块在导入期就去读自举配置。
const { apply } = await import('../lib/index.js')

/** 一次性临时 profile 目录（env 指向它，结束时整棵删除）。 */
function tempStore(prefix = 'dsh-game-bridge-general-') {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  return {
    dir,
    env: { DSH_GAME_BRIDGE_PROFILE_DIR: dir },
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  }
}

/** 与 m0 测试同形状的最小宿主桩：工具注册表 + 图片附件存储。 */
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
        assert.ok(data instanceof Uint8Array)
        return { attachmentId: 'att_general', mediaType, bytes: data.length, width: 16, height: 9 }
      },
    },
  }
}

/** 只注册一次插件，返回按名字取工具定义的辅助函数。 */
function toolset() {
  const ctx = fakeCtx()
  apply(ctx)
  return (name) => {
    const definition = ctx.registered.find((entry) => entry.name === name)
    assert.ok(definition, `tool ${name} was not registered`)
    return definition
  }
}

test('profilesDir prefers the explicit override and falls back to <cache-root>/profiles', () => {
  assert.equal(
    profilesDir({ DSH_GAME_BRIDGE_PROFILE_DIR: join('somewhere', 'profiles') }),
    join('somewhere', 'profiles'),
  )
  const cache = join('caches', 'dsh-game-bridge')
  assert.equal(
    profilesDir({ DSH_GAME_BRIDGE_CACHE_DIR: cache }, { platform: 'win32', home: 'unused' }),
    join(cache, 'profiles'),
  )
})

test('cacheRoot uses LOCALAPPDATA on Windows and platform cache dirs elsewhere', () => {
  assert.equal(
    cacheRoot({}, { platform: 'win32', home: join('home', 'example') }),
    join('home', 'example', 'dsh-game-bridge'),
  )
  assert.equal(
    cacheRoot({ LOCALAPPDATA: join('local', 'appdata') }, { platform: 'win32', home: 'unused' }),
    join('local', 'appdata', 'dsh-game-bridge'),
  )
  assert.equal(
    cacheRoot({}, { platform: 'darwin', home: join('home', 'example') }),
    join('home', 'example', 'Library', 'Caches', 'dsh-game-bridge'),
  )
  assert.equal(
    cacheRoot({ XDG_CACHE_HOME: join('xdg', 'cache') }, { platform: 'linux', home: 'unused' }),
    join('xdg', 'cache', 'dsh-game-bridge'),
  )
})

test('validateProfileId accepts safe ids and rejects traversal/invalid shapes', () => {
  for (const id of ['cuphead', 'boss-rush', 'slot_2', 'v1.2', 'a'.repeat(64)]) {
    assert.equal(validateProfileId(id), id)
    assert.equal(isValidProfileId(id), true)
  }
  assert.equal(validateProfileId('  cuphead  '), 'cuphead', 'surrounding whitespace is trimmed, not stored')

  const bad = ['', '   ', '.', '..', '../etc', 'a/b', 'a\\b', 'name with spaces', 'x'.repeat(65), 'semi;colon']
  for (const id of bad) {
    assert.throws(() => validateProfileId(id), /invalid profile id/, `id ${JSON.stringify(id)} must be rejected`)
    assert.equal(isValidProfileId(id), false)
  }
  assert.throws(() => validateProfileId(null), /must be a string/)
  assert.throws(() => validateProfileId(42), /must be a string/)
  assert.throws(() => validateProfileId(undefined), ProfileStoreError)
})

test('writeProfile/readProfile round-trips pretty JSON, injects the id and returns null when missing', () => {
  const store = tempStore()
  try {
    const written = writeProfile(store.env, 'cuphead', { name: 'Cuphead', controls: { jump: 'Z' } })
    assert.equal(written.id, 'cuphead')
    assert.ok(written.bytes > 0)

    const text = readFileSync(join(store.dir, 'cuphead.json'), 'utf8')
    assert.match(text, /^\{\n {2}"id": "cuphead",\n {2}"name": "Cuphead"/, 'id first, two-space pretty JSON')
    assert.ok(text.endsWith('\n'), 'file ends with a newline')

    assert.deepEqual(readProfile(store.env, 'cuphead'), {
      id: 'cuphead',
      name: 'Cuphead',
      controls: { jump: 'Z' },
    })
    assert.equal(readProfile(store.env, 'never-saved'), null)
  } finally {
    store.cleanup()
  }
})

test('writeProfile rejects bad data and a mismatched id', () => {
  const store = tempStore()
  try {
    assert.throws(() => writeProfile(store.env, 'cuphead', { id: 'other' }), /does not match/)
    assert.throws(() => writeProfile(store.env, 'cuphead', []), /JSON object/)
    assert.throws(() => writeProfile(store.env, 'cuphead', 'not-an-object'), /JSON object/)
    assert.throws(() => writeProfile(store.env, '../escape', {}), /invalid profile id/)
  } finally {
    store.cleanup()
  }
})

test('readProfile and listProfiles surface bad JSON without hiding healthy profiles', () => {
  const store = tempStore()
  try {
    writeProfile(store.env, 'cuphead', { name: 'Cuphead' })
    writeProfile(store.env, 'boss', { name: 'Boss Rush' })
    writeFileSync(join(store.dir, 'broken.json'), '{ this is not json')
    writeFileSync(join(store.dir, 'notes.txt'), 'not a profile')
    writeFileSync(join(store.dir, 'bad name.json'), '{}')

    assert.throws(() => readProfile(store.env, 'broken'), /not valid JSON/)
    assert.throws(() => readProfile(store.env, '../escape'), /invalid profile id/)

    const listing = listProfiles(store.env)
    assert.deepEqual(
      listing.profiles.map((entry) => entry.id),
      ['boss', 'cuphead'],
      'sorted by id; non-JSON and invalid names ignored',
    )
    assert.deepEqual(listing.errors.map((entry) => entry.id), ['broken'])
    assert.match(listing.errors[0].error, /not valid JSON/)
    assert.equal(listing.dir, store.dir)
  } finally {
    store.cleanup()
  }
})

test('listProfiles returns an empty list when the directory does not exist yet', () => {
  const store = tempStore()
  try {
    const listing = listProfiles({ DSH_GAME_BRIDGE_PROFILE_DIR: join(store.dir, 'not-created') })
    assert.deepEqual(listing.profiles, [])
    assert.deepEqual(listing.errors, [])
  } finally {
    store.cleanup()
  }
})

test('deleteProfile is idempotent and refuses ids outside the profile directory', () => {
  const store = tempStore()
  try {
    writeProfile(store.env, 'cuphead', { name: 'Cuphead' })
    assert.deepEqual(deleteProfile(store.env, 'cuphead'), { id: 'cuphead', deleted: true })
    assert.deepEqual(deleteProfile(store.env, 'cuphead'), { id: 'cuphead', deleted: false })
    assert.throws(() => deleteProfile(store.env, '../outside'), /invalid profile id/)
    assert.equal(readProfile(store.env, 'cuphead'), null)
  } finally {
    store.cleanup()
  }
})

test('store functions accept injected fs dependencies', () => {
  /** @type {Map<string, string>} */
  const memory = new Map()
  const fsDeps = {
    existsSync: (path) => memory.has(path),
    mkdirSync: () => {},
    readFileSync: (path) => {
      if (!memory.has(path)) {
        const error = new Error(`ENOENT: ${path}`)
        error.code = 'ENOENT'
        throw error
      }
      return memory.get(path)
    },
    readdirSync: () =>
      [...memory.keys()].map((path) => ({
        name: path.split(/[\\/]/).pop(),
        isFile: () => true,
      })),
    rmSync: (path) => memory.delete(path),
    writeFileSync: (path, text) => memory.set(path, text),
  }
  const env = { DSH_GAME_BRIDGE_PROFILE_DIR: 'in-memory-profiles' }

  assert.equal(readProfile(env, 'missing', fsDeps), null)
  const written = writeProfile(env, 'cuphead', { name: 'Cuphead' }, fsDeps)
  assert.equal(written.id, 'cuphead')
  assert.equal(readProfile(env, 'cuphead', fsDeps).name, 'Cuphead')
  assert.deepEqual(listProfiles(env, fsDeps).profiles, [{ id: 'cuphead', name: 'Cuphead' }])
  assert.deepEqual(deleteProfile(env, 'cuphead', fsDeps), { id: 'cuphead', deleted: true })
  assert.equal(memory.size, 0)
})

test('game_state render summarizes the WorldState and warns about profile/occlusion/foreground', () => {
  const tool = toolset()
  const state = {
    schema: 1,
    scene: 'gameplay',
    confidence: 0.82,
    player: { x: 0.3, y: 0.7, hp: 3, max_hp: 3, state: 'idle' },
    entities: [{ kind: 'threat' }, { kind: 'parry' }],
    ui: { prompt: 'CONFIRM Z' },
    foreground: { hwnd: 11, title: 'Fixture Game' },
    occluded: {
      available: true,
      occluded_ratio: 0.62,
      occluded: true,
      covered_by: [{ hwnd: 22, title: 'Editor', ratio: 0.62 }],
    },
    game: { profile: 'cuphead', provider: 'vision' },
  }
  const [block] = tool('game_state').output.render({}, {
    state,
    profile: { id: 'cuphead', found: true, warning: null },
  })
  assert.equal(block.type, 'text')
  assert.ok(block.text.startsWith('scene=gameplay, hp=3/3, entities=2, prompt=CONFIRM Z.'))
  assert.match(block.text, /Profile: cuphead/)
  assert.match(block.text, /Foreground: Fixture Game \(hwnd 11\)/)
  assert.match(block.text, /⚠ target window is 62% occluded \(mostly by Editor\)/)
})

test('game_state render degrades to unknown defaults and surfaces a missing profile', () => {
  const tool = toolset()
  const [block] = tool('game_state').output.render({}, {
    state: { scene: 'unknown', player: { hp: null }, entities: [], ui: {} },
    profile: {
      id: 'cuphead',
      found: false,
      warning: 'profile "cuphead" was not found in the profile store; falling back to engine defaults',
    },
  })
  assert.ok(block.text.startsWith('scene=unknown, hp=unknown, entities=0, prompt=none.'))
  assert.match(block.text, /⚠ profile "cuphead" was not found/)
})

test('game_attach render reports the selected profile and still renders without one', () => {
  const tool = toolset()
  const base = {
    attached: { window: 'Fixture Game' },
    backend: 'dry-run',
    safety: { allowed: true, reasons: [] },
  }
  const [loaded] = tool('game_attach').output.render({}, {
    ...base,
    profile: { id: 'cuphead', found: true, warning: null },
  })
  assert.ok(loaded.text.startsWith('Attached to Fixture Game'))
  assert.match(loaded.text, /Profile: cuphead \(loaded\)/)
  assert.match(loaded.text, /Safety: allowed/)

  const [noProfile] = tool('game_attach').output.render({}, base)
  assert.doesNotMatch(noProfile.text, /Profile:/)

  const [missing] = tool('game_attach').output.render({}, {
    ...base,
    profile: {
      id: 'cuphead',
      found: false,
      warning: 'profile "cuphead" was not found in the profile store; falling back to engine defaults',
    },
  })
  assert.match(missing.text, /Profile: cuphead \(⚠ profile "cuphead" was not found/)
})

test('game_policy render reports running, stopped and idle states', () => {
  const tool = toolset()
  const policy = {
    running: true,
    ticks: 6,
    hz: 60,
    actions: 12,
    escapes: 1,
    stop_reason: null,
    scene: 'gameplay',
    last_entities: 2,
  }
  const [started] = tool('game_policy').output.render({}, { action: 'start', policy })
  assert.match(
    started.text,
    /^Policy start: running=yes, ticks=6, hz=60, actions=12, escapes=1, scene=gameplay, entities=2\./,
  )

  const [stopped] = tool('game_policy').output.render(
    {},
    {
      action: 'stop',
      policy: { ...policy, running: false, stop_reason: 'safety gate: anticheat detected' },
    },
  )
  assert.match(stopped.text, /^Policy stop: running=no/)
  assert.match(stopped.text, /stop_reason=safety gate: anticheat detected/)

  const [idle] = tool('game_policy').output.render({}, { action: 'status', policy: null })
  assert.match(idle.text, /^Policy status: not running\./)
})

test('game_memory render covers list/get/save/delete/use results', () => {
  const tool = toolset()
  const render = (result) => tool('game_memory').output.render({}, { result })[0]

  const list = render({
    action: 'list',
    profiles: [
      { id: 'cuphead', name: 'Cuphead' },
      { id: 'boss', name: null },
    ],
    errors: [],
  })
  assert.match(list.text, /^Profiles \(2\): cuphead \(Cuphead\), boss\./)

  const empty = render({ action: 'list', profiles: [], errors: [] })
  assert.match(empty.text, /No profiles saved\./)

  const withError = render({ action: 'list', profiles: [], errors: [{ id: 'broken', error: 'not valid JSON' }] })
  assert.match(withError.text, /⚠ broken: not valid JSON/)

  const found = render({ action: 'get', id: 'cuphead', found: true, profile: { name: 'Cuphead' } })
  assert.match(found.text, /^Profile cuphead: found \(Cuphead\)\./)

  const missing = render({ action: 'get', id: 'cuphead', found: false, profile: null })
  assert.match(missing.text, /^Profile cuphead: not found\./)

  const saved = render({ action: 'save', id: 'cuphead', saved: true, bytes: 321 })
  assert.match(saved.text, /^Saved profile cuphead \(321 bytes\)\./)

  const deleted = render({ action: 'delete', id: 'cuphead', deleted: true })
  assert.match(deleted.text, /^Deleted profile cuphead\./)

  const notThere = render({ action: 'delete', id: 'cuphead', deleted: false })
  assert.match(notThere.text, /^Profile cuphead was not in the store\./)

  const used = render({
    action: 'use',
    id: 'cuphead',
    active: true,
    found: false,
    warning: 'profile "cuphead" was not found; it will be used if you save it later',
  })
  assert.match(used.text, /^Active profile: cuphead\./)
  assert.match(used.text, /⚠ profile "cuphead" was not found/)
})

test('game_memory save rejects a non-object payload and a missing id', async () => {
  const tool = toolset()
  const store = tempStore()
  try {
    process.env.DSH_GAME_BRIDGE_PROFILE_DIR = store.dir
    await assert.rejects(
      () => tool('game_memory').execute({ action: 'save', id: 'cuphead', data: ['not', 'an', 'object'] }, {}),
      /needs data: a JSON object/,
    )
    await assert.rejects(() => tool('game_memory').execute({ action: 'save', data: {} }, {}), /must be a string/)
    await assert.rejects(
      () => tool('game_memory').execute({ action: 'get', id: '../escape' }, {}),
      /invalid profile id/,
    )
  } finally {
    delete process.env.DSH_GAME_BRIDGE_PROFILE_DIR
    store.cleanup()
  }
})

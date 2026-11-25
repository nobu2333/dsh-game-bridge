/**
 * 用户 profile 存储：把「游戏差异」放在插件自己的缓存目录里，而不是写进引擎。
 *
 * 设计要点：
 * - **位置可注入**：`DSH_GAME_BRIDGE_PROFILE_DIR` 直接指定目录（测试/隔离环境用），
 *   否则落在引擎缓存根下的 `profiles/`（`%LOCALAPPDATA%/dsh-game-bridge` 或
 *   `DSH_GAME_BRIDGE_CACHE_DIR`）；
 * - **id 是安全边界**：只接受 `[A-Za-z0-9._-]{1,64}` 且显式拒绝 `.`/`..`，
 *   文件名固定为 `<id>.json`，写入前再做一次「解析后仍在目录内」的检查；
 * - **fs 可注入**：单元测试用内存 fs 或临时目录，无需碰用户真实目录；
 * - **失败语义清晰**：缺文件返回 null，坏 JSON / 坏形状抛 `ProfileStoreError`，
 *   调用方（工具）把消息转成一行警告，而不是悄悄吞掉。
 *
 * 这里只存公开、可分享的游戏资料（键位/HUD 框/颜色阈值）；内存偏移、作弊数据
 * 不进入仓库，也建议用户不要通过本工具分享。
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { isAbsolute, join, relative, resolve } from 'node:path'

/** profile id 的合法形状：文件名安全、无路径分隔符、长度有界。 */
export const PROFILE_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/
/** 存储文件后缀（读取时同后缀的文件才会被列出）。 */
export const PROFILE_EXTENSION = '.json'
export const NOTES_MAX_LINES = 200
export const NOTES_MAX_BYTES = 16384
export const NOTES_WRITE_MAX_BYTES = 65536
export const RUNS_DEFAULT_LIMIT = 10

const SECRET_PATTERNS = [
  /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/g,
  /\b(?:sk|pk|rk|ghp|gho|ghu|ghs|glpat)-[A-Za-z0-9_-]{12,}\b/g,
  /\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*['"]?[^\s'"]{6,}['"]?/gi,
]

/** profile 存储错误：`code` 供调用方区分「不是 JSON」「读失败」等原因。 */
export class ProfileStoreError extends Error {
  /**
   * @param {string} message
   * @param {string} [code]
   */
  constructor(message, code = 'PROFILE_STORE_ERROR') {
    super(message)
    this.name = 'ProfileStoreError'
    this.code = code
  }
}

/** 默认 fs 依赖；测试可整体替换（只要实现同样几个方法）。 */
const defaultFs = {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
}

/**
 * 引擎/插件的缓存根目录（不追加 `engine` 子目录）。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {{ platform?: string, home?: string }} [options]
 * @returns {string}
 */
export function cacheRoot(env = process.env, { platform = process.platform, home = homedir() } = {}) {
  if (env.DSH_GAME_BRIDGE_CACHE_DIR) return String(env.DSH_GAME_BRIDGE_CACHE_DIR)
  if (platform === 'win32') return join(env.LOCALAPPDATA || home, 'dsh-game-bridge')
  if (platform === 'darwin') return join(home, 'Library', 'Caches', 'dsh-game-bridge')
  return join(env.XDG_CACHE_HOME || join(home, '.cache'), 'dsh-game-bridge')
}

/**
 * profile 目录：`$DSH_GAME_BRIDGE_PROFILE_DIR` 优先，否则 `<cache-root>/profiles`。
 * 只做路径推导，不创建目录。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {{ platform?: string, home?: string }} [options]
 * @returns {string}
 */
export function profilesDir(env = process.env, options = {}) {
  if (env.DSH_GAME_BRIDGE_PROFILE_DIR) return String(env.DSH_GAME_BRIDGE_PROFILE_DIR)
  return join(cacheRoot(env, options), 'profiles')
}

/**
 * 校验 profile id；合法时返回去空白后的 id，非法时抛 `ProfileStoreError`。
 *
 * @param {unknown} id
 * @returns {string}
 */
export function validateProfileId(id) {
  if (typeof id !== 'string') throw new ProfileStoreError('profile id must be a string', 'PROFILE_BAD_ID')
  const value = id.trim()
  // 显式拒绝路径穿越：形状里虽然不含分隔符，但 `.`/`..` 本身是合法字符。
  if (value === '.' || value === '..' || !PROFILE_ID_PATTERN.test(value)) {
    throw new ProfileStoreError(
      `invalid profile id ${JSON.stringify(id)}: expected 1..64 characters from [A-Za-z0-9._-] with no path traversal`,
      'PROFILE_BAD_ID',
    )
  }
  return value
}

/**
 * id 是否合法（不抛版本，便于工具做条件判断）。
 * @param {unknown} id
 * @returns {boolean}
 */
export function isValidProfileId(id) {
  try {
    validateProfileId(id)
    return true
  } catch {
    return false
  }
}

/**
 * 解析 profile 的存储路径，并再次确认解析结果没有跑出 profile 目录。
 *
 * @param {Record<string, string | undefined>} env
 * @param {unknown} id
 * @returns {{ dir: string, file: string, id: string }}
 */
function profilePath(env, id) {
  const safeId = validateProfileId(id)
  const dir = profilesDir(env)
  const root = resolve(dir)
  const file = resolve(root, `${safeId}${PROFILE_EXTENSION}`)
  const rel = relative(root, file)
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) {
    throw new ProfileStoreError(`profile id ${JSON.stringify(safeId)} escapes the profile directory`, 'PROFILE_BAD_ID')
  }
  return { dir, file, id: safeId }
}

/**
 * 列出 profile 目录里的 profile 摘要（按 id 排序）。
 * 目录不存在 -> 空列表；坏 JSON 归入 `errors`，不阻断其它条目。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {typeof defaultFs} [fsDeps]
 * @returns {{ dir: string, profiles: {id: string, name: string | null}[], errors: {id: string, error: string}[] }}
 */
export function listProfiles(env = process.env, fsDeps = defaultFs) {
  const dir = profilesDir(env)
  /** @type {import('node:fs').Dirent[] | string[]} */
  let entries
  try {
    entries = fsDeps.readdirSync(dir, { withFileTypes: true })
  } catch (error) {
    if (error?.code === 'ENOENT') return { dir, profiles: [], errors: [] }
    throw new ProfileStoreError(`cannot list profiles in ${dir}: ${error.message}`, 'PROFILE_LIST_FAILED')
  }
  const profiles = []
  const errors = []
  for (const entry of entries) {
    const name = typeof entry === 'string' ? entry : entry?.name
    if (typeof name !== 'string') continue
    if (typeof entry !== 'string' && typeof entry?.isFile === 'function' && !entry.isFile()) continue
    if (!name.toLowerCase().endsWith(PROFILE_EXTENSION)) continue
    const id = name.slice(0, -PROFILE_EXTENSION.length)
    if (!isValidProfileId(id)) continue
    try {
      const profile = readProfile(env, id, fsDeps)
      if (!profile) continue
      profiles.push({ id, name: typeof profile.name === 'string' ? profile.name : null })
    } catch (error) {
      errors.push({ id, error: error.message })
    }
  }
  profiles.sort((a, b) => a.id.localeCompare(b.id))
  errors.sort((a, b) => a.id.localeCompare(b.id))
  return { dir, profiles, errors }
}

/**
 * 读取一个 profile；文件不存在返回 null，坏 JSON / 非对象抛 `ProfileStoreError`。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {unknown} id
 * @param {typeof defaultFs} [fsDeps]
 * @returns {Record<string, unknown> | null}
 */
export function readProfile(env = process.env, id, fsDeps = defaultFs) {
  const { file, id: safeId } = profilePath(env, id)
  let text
  try {
    text = fsDeps.readFileSync(file, 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw new ProfileStoreError(`cannot read profile ${JSON.stringify(safeId)}: ${error.message}`, 'PROFILE_READ_FAILED')
  }
  let parsed
  try {
    parsed = JSON.parse(String(text).replace(/^\uFEFF/, ''))
  } catch (error) {
    throw new ProfileStoreError(
      `profile ${JSON.stringify(safeId)} is not valid JSON: ${error.message}`,
      'PROFILE_BAD_JSON',
    )
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new ProfileStoreError(`profile ${JSON.stringify(safeId)} must be a JSON object`, 'PROFILE_BAD_SHAPE')
  }
  return parsed
}

/**
 * 写入一个 profile（创建目录、pretty JSON、末尾换行）。
 * `id` 会补进数据（若数据自带 id 则必须一致），避免文件内容与文件名脱节。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {unknown} id
 * @param {unknown} data
 * @param {typeof defaultFs} [fsDeps]
 * @returns {{ id: string, bytes: number }}
 */
export function writeProfile(env = process.env, id, data, fsDeps = defaultFs) {
  const { dir, file, id: safeId } = profilePath(env, id)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new ProfileStoreError('profile data must be a JSON object', 'PROFILE_BAD_DATA')
  }
  if (data.id != null && data.id !== safeId) {
    throw new ProfileStoreError(
      `profile data id ${JSON.stringify(data.id)} does not match the requested id ${JSON.stringify(safeId)}`,
      'PROFILE_BAD_DATA',
    )
  }
  const record = data.id == null ? { id: safeId, ...data } : data
  let serialized
  try {
    serialized = `${JSON.stringify(record, null, 2)}\n`
  } catch (error) {
    throw new ProfileStoreError(`profile ${JSON.stringify(safeId)} is not serializable: ${error.message}`, 'PROFILE_BAD_DATA')
  }
  try {
    fsDeps.mkdirSync(dir, { recursive: true })
    fsDeps.writeFileSync(file, serialized, 'utf8')
  } catch (error) {
    throw new ProfileStoreError(`cannot write profile ${JSON.stringify(safeId)}: ${error.message}`, 'PROFILE_WRITE_FAILED')
  }
  return { id: safeId, bytes: Buffer.byteLength(serialized, 'utf8') }
}

/**
 * 删除一个 profile；文件本就不存在时返回 `{ deleted: false }`（删除是幂等的）。
 *
 * @param {Record<string, string | undefined>} [env]
 * @param {unknown} id
 * @param {typeof defaultFs} [fsDeps]
 * @returns {{ id: string, deleted: boolean }}
 */
export function deleteProfile(env = process.env, id, fsDeps = defaultFs) {
  const { file, id: safeId } = profilePath(env, id)
  try {
    if (!fsDeps.existsSync(file)) return { id: safeId, deleted: false }
    fsDeps.rmSync(file, { force: true })
  } catch (error) {
    throw new ProfileStoreError(`cannot delete profile ${JSON.stringify(safeId)}: ${error.message}`, 'PROFILE_DELETE_FAILED')
  }
  return { id: safeId, deleted: true }
}

/**
 * 脱敏明显凭据/私钥，防止模型把敏感文本写进游戏笔记。
 * @param {unknown} text
 * @returns {string}
 */
export function redactSecrets(text) {
  let out = String(text ?? '')
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, '«redacted»')
  }
  return out
}

/**
 * 游戏笔记/单局摘要目录：`$DSH_GAME_BRIDGE_DATA_DIR/games`，测试覆盖
 * `$DSH_GAME_BRIDGE_PROFILE_DIR` 时放在其 `_games` 子目录以保持隔离，否则 `<cache-root>/games`。
 */
export function gamesDir(env = process.env, options = {}) {
  if (env.DSH_GAME_BRIDGE_DATA_DIR) return join(String(env.DSH_GAME_BRIDGE_DATA_DIR), 'games')
  if (env.DSH_GAME_BRIDGE_PROFILE_DIR) return join(String(env.DSH_GAME_BRIDGE_PROFILE_DIR), '_games')
  return join(cacheRoot(env, options), 'games')
}

function gameDirPath(env, id) {
  const safeId = validateProfileId(id)
  const root = resolve(gamesDir(env))
  const dir = resolve(root, safeId)
  const rel = relative(root, dir)
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) {
    throw new ProfileStoreError(`game id ${JSON.stringify(safeId)} escapes the games directory`, 'PROFILE_BAD_ID')
  }
  return { id: safeId, dir, notesFile: join(dir, 'notes.md'), runsFile: join(dir, 'runs.jsonl') }
}

/**
 * 读取 `<games>/<id>/notes.md`（按行/字节预算截断，防止爆上下文）。
 */
export function readGameNotes(
  env = process.env,
  id,
  { maxLines = NOTES_MAX_LINES, maxBytes = NOTES_MAX_BYTES } = {},
  fsDeps = defaultFs,
) {
  const { id: safeId, notesFile } = gameDirPath(env, id)
  let raw
  try {
    raw = fsDeps.readFileSync(notesFile, 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { id: safeId, found: false, text: '', total_lines: 0, total_bytes: 0, truncated: false }
    }
    throw new ProfileStoreError(`cannot read notes for ${JSON.stringify(safeId)}: ${error.message}`, 'NOTES_READ_FAILED')
  }
  const clean = String(raw).replace(/^\uFEFF/, '').replace(/\r?\n$/, '')
  const lines = clean ? clean.split(/\r?\n/) : []
  const totalBytes = Buffer.byteLength(clean, 'utf8')
  const lineCap = Math.max(1, Number(maxLines) || NOTES_MAX_LINES)
  const byteCap = Math.max(128, Number(maxBytes) || NOTES_MAX_BYTES)
  const kept = []
  let usedBytes = 0
  let truncated = false
  for (const line of lines) {
    if (kept.length >= lineCap) {
      truncated = true
      break
    }
    const lineBytes = Buffer.byteLength(line, 'utf8') + (kept.length ? 1 : 0)
    if (usedBytes + lineBytes > byteCap) {
      truncated = true
      break
    }
    kept.push(line)
    usedBytes += lineBytes
  }
  return {
    id: safeId,
    found: true,
    text: kept.join('\n').trimEnd(),
    total_lines: lines.length,
    total_bytes: totalBytes,
    truncated,
  }
}

/** 覆盖写入 `<games>/<id>/notes.md`（自动脱敏 + 大小上限）。 */
export function writeGameNotes(env = process.env, id, text, fsDeps = defaultFs) {
  if (typeof text !== 'string') {
    throw new ProfileStoreError('notes content must be a string', 'NOTES_BAD_DATA')
  }
  const { id: safeId, dir, notesFile } = gameDirPath(env, id)
  const sanitized = redactSecrets(text).replace(/\r\n/g, '\n').trimEnd()
  const serialized = sanitized ? `${sanitized}\n` : ''
  const bytes = Buffer.byteLength(serialized, 'utf8')
  if (bytes > NOTES_WRITE_MAX_BYTES) {
    throw new ProfileStoreError(`notes for ${JSON.stringify(safeId)} exceed ${NOTES_WRITE_MAX_BYTES} bytes`, 'NOTES_TOO_LARGE')
  }
  try {
    fsDeps.mkdirSync(dir, { recursive: true })
    fsDeps.writeFileSync(notesFile, serialized, 'utf8')
  } catch (error) {
    throw new ProfileStoreError(`cannot write notes for ${JSON.stringify(safeId)}: ${error.message}`, 'NOTES_WRITE_FAILED')
  }
  return { id: safeId, bytes }
}

/** 追加一条带 M4 元信息（date/source/confidence）的游戏笔记。 */
export function appendGameNote(
  env = process.env,
  id,
  note,
  { source = 'model', confidence = 0.7, date = new Date().toISOString().slice(0, 10) } = {},
  fsDeps = defaultFs,
) {
  const cleanNote = redactSecrets(String(note ?? '')).replace(/[\r\n]+/g, ' ').trim()
  if (!cleanNote) {
    throw new ProfileStoreError('note must be a non-empty string', 'NOTES_BAD_DATA')
  }
  const confNum = Number(confidence)
  const conf = Number.isFinite(confNum) ? Math.max(0, Math.min(1, Number(confNum.toFixed(2)))) : 0.7
  const cleanSource = String(source || 'model').replace(/[^\w.-]/g, '').slice(0, 24) || 'model'
  const cleanDate = String(date || new Date().toISOString().slice(0, 10)).slice(0, 16)
  const entry = `- [${cleanDate} | source:${cleanSource} | conf:${conf}] ${cleanNote.slice(0, 800)}`
  const existing = readGameNotes(env, id, { maxLines: 10000, maxBytes: NOTES_WRITE_MAX_BYTES }, fsDeps)
  const nextText = existing.found && existing.text ? `${existing.text}\n${entry}` : `# ${existing.id} Notes\n\n${entry}`
  const written = writeGameNotes(env, id, nextText, fsDeps)
  return { id: existing.id, entry, bytes: written.bytes }
}

/** 追加一条紧凑单局摘要（M0 run summary）到 `<games>/<id>/runs.jsonl`。 */
export function appendGameRun(env = process.env, id, run, fsDeps = defaultFs) {
  if (!run || typeof run !== 'object' || Array.isArray(run)) {
    throw new ProfileStoreError('run summary must be a JSON object', 'RUN_BAD_DATA')
  }
  const { id: safeId, dir, runsFile } = gameDirPath(env, id)
  const cleanLessons = Array.isArray(run.lessons)
    ? run.lessons.slice(0, 8).map((item) => redactSecrets(String(item ?? '')).slice(0, 240)).filter(Boolean)
    : []
  const record = {
    run_id: String(run.run_id || `run-${Date.now()}`).slice(0, 64),
    date: String(run.date || new Date().toISOString().slice(0, 10)).slice(0, 24),
    result: String(run.result || 'unknown').slice(0, 32),
    ...(run.score != null && Number.isFinite(Number(run.score)) ? { score: Number(run.score) } : {}),
    ...(run.steps != null && Number.isFinite(Number(run.steps)) ? { steps: Number(run.steps) } : {}),
    ...(run.end_reason ? { end_reason: String(run.end_reason).slice(0, 64) } : {}),
    ...(run.summary ? { summary: redactSecrets(String(run.summary)).slice(0, 600) } : {}),
    ...(cleanLessons.length ? { lessons: cleanLessons } : {}),
  }
  const line = `${JSON.stringify(record)}\n`
  try {
    fsDeps.mkdirSync(dir, { recursive: true })
    fsDeps.appendFileSync(runsFile, line, 'utf8')
  } catch (error) {
    throw new ProfileStoreError(`cannot save run for ${JSON.stringify(safeId)}: ${error.message}`, 'RUN_WRITE_FAILED')
  }
  return { id: safeId, record, bytes: Buffer.byteLength(line, 'utf8') }
}

/** 列出最近 N 条紧凑单局摘要（最新在前）。 */
export function listGameRuns(env = process.env, id, { limit = RUNS_DEFAULT_LIMIT } = {}, fsDeps = defaultFs) {
  const { id: safeId, runsFile } = gameDirPath(env, id)
  let raw
  try {
    raw = fsDeps.readFileSync(runsFile, 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return { id: safeId, total: 0, runs: [] }
    throw new ProfileStoreError(`cannot read runs for ${JSON.stringify(safeId)}: ${error.message}`, 'RUN_READ_FAILED')
  }
  const cap = Math.max(1, Math.min(30, Math.round(Number(limit) || RUNS_DEFAULT_LIMIT)))
  const parsed = []
  for (const line of String(raw).split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed) continue
    try {
      const obj = JSON.parse(trimmed)
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) parsed.push(obj)
    } catch {
      /* ignore malformed lines */
    }
  }
  return { id: safeId, total: parsed.length, runs: parsed.slice(-cap).reverse() }
}

/**
 * 版本一致性：插件版本、引擎版本、自举 pin 必须是同一个值。
 *
 * 这三处分开写是必要的（npm 包与 PyPI 包各自有元数据、运行时要知道 pin），
 * 但一旦漂移就会出现「自举装错引擎版本」这种只在用户机器上炸的问题。
 * 所以用测试把它们钉在一起；发布前改版本时先看到这条红。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..')

function read(relative) {
  return readFileSync(resolve(repo, relative), 'utf8')
}

test('plugin, engine and bootstrap pin share one version', () => {
  const pkg = JSON.parse(read('package.json')).version
  const bootstrap = /export const ENGINE_VERSION = '([^']+)'/.exec(read('lib/bootstrap.js'))?.[1]
  const pyproject = /^version = "([^"]+)"/m.exec(read('engine/pyproject.toml'))?.[1]
  const moduleVersion = /__version__ = "([^"]+)"/.exec(read('engine/dsh_game_core/__init__.py'))?.[1]

  assert.equal(bootstrap, pkg, 'lib/bootstrap.js ENGINE_VERSION must match package.json')
  assert.equal(pyproject, pkg, 'engine/pyproject.toml version must match package.json')
  assert.equal(moduleVersion, pkg, 'engine __version__ must match package.json')
})

test('engine declares MIT and ships its license file', () => {
  const pyproject = read('engine/pyproject.toml')
  assert.match(pyproject, /license = \{ text = "MIT" \}/)
  assert.ok(read('engine/LICENSE').includes('MIT License'))
})

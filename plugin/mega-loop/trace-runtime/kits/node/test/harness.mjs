/**
 * Start an app, drive it, and grade what it emitted with the validator the skills use.
 *
 * Grading goes through `scripts/validate_traces.py --file` rather than a re-implementation of the
 * contract here: a second copy of the checks could pass while the real one fails.
 */

import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const KIT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const VALIDATOR = resolve(KIT_DIR, '../../scripts/validate_traces.py')

export async function freePort() {
  const server = createServer()
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  const { port } = server.address()
  await new Promise((r) => server.close(r))
  return port
}

/** Every process the tests start, so a failed assertion never leaves a server running. */
const running = new Set()
process.on('exit', () => running.forEach((child) => child.kill('SIGKILL')))

export function startApp(command, args, { cwd, env }) {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, OTEL_BSP_SCHEDULE_DELAY: '200', ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  child.stdout.on('data', (d) => (output += d))
  child.stderr.on('data', (d) => (output += d))
  running.add(child)
  child.on('exit', () => running.delete(child))
  return {
    child,
    output: () => output,
    async ready(url, { timeoutMs = 60_000 } = {}) {
      const deadline = Date.now() + timeoutMs
      for (;;) {
        if (child.exitCode !== null) throw new Error(`app exited early:\n${output}`)
        try {
          if ((await fetch(url)).ok) return
        } catch {
          // not listening yet
        }
        if (Date.now() > deadline) throw new Error(`app never became ready at ${url}:\n${output}`)
        await new Promise((r) => setTimeout(r, 200))
      }
    },
    async stop() {
      if (child.exitCode !== null) return
      const exited = new Promise((r) => child.once('exit', r))
      child.kill('SIGTERM')
      await exited
    },
  }
}

export function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async (r) => {
    if (!r.ok) throw new Error(`${url} → ${r.status}: ${await r.text()}`)
    return r.json()
  })
}

/** Run the skills' validator over these spans. `exitCode` 0 means every trace is seatable. */
export function grade(spans) {
  const file = join(mkdtempSync(join(tmpdir(), 'kit-e2e-')), 'spans.json')
  writeFileSync(file, JSON.stringify(spans, null, 2))
  const run = spawnSync('uv', ['run', '--quiet', VALIDATOR, '--file', file, '--json'], {
    encoding: 'utf8',
  })
  if (run.error) throw run.error
  if (!run.stdout.trim()) throw new Error(`validator printed nothing:\n${run.stderr}`)
  return { exitCode: run.status, report: JSON.parse(run.stdout), file }
}

export function traceIds(spans) {
  return [...new Set(spans.map((s) => s.trace_id))]
}

export function rootOf(spans) {
  const roots = spans.filter((s) => !s.parent_id)
  if (roots.length !== 1) {
    throw new Error(`expected one root, got ${roots.length}: ${roots.map((s) => s.name)}`)
  }
  return roots[0]
}

/**
 * The spans of the one request under test: the trace whose root is a POST. Readiness probes
 * (GETs) and startup spans are separate traces and fall away. Two POST roots means a service
 * started its own trace instead of continuing the caller's — propagation is broken.
 */
export function requestTrace(spans) {
  const roots = spans.filter((s) => !s.parent_id && /^POST\b/.test(s.name))
  if (roots.length !== 1) {
    throw new Error(`expected one POST root, got ${roots.length}: ` +
      JSON.stringify(roots.map((s) => `${s.service}:${s.name}`)))
  }
  return spans.filter((s) => s.trace_id === roots[0].trace_id)
}

/** Install a fixture's dependencies once, then run its build — the steps a user would take. */
export function prepareFixture(dir, buildArgs) {
  const npm = (args) => {
    const run = spawnSync('npm', args, { cwd: dir, encoding: 'utf8' })
    if (run.status !== 0) throw new Error(`npm ${args.join(' ')} failed in ${dir}:\n${run.stdout}${run.stderr}`)
  }
  if (!existsSync(join(dir, 'node_modules'))) npm(['install', '--no-audit', '--no-fund'])
  npm(buildArgs)
}
